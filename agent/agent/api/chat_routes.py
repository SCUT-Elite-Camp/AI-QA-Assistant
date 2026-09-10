from typing import Optional
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from agent.schemas.chat import ChatRequest, ChatResponse, Citation
from agent.agent import Agent
from agent.auth import verify_agent_key
from agent.config.settings import settings
from agent.streaming.sse import build_sse_event

router = APIRouter()


def get_agent() -> Agent:
    """Dependency provider for Agent."""
    return Agent()


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    agent: Agent = Depends(get_agent),
    _: None = Depends(verify_agent_key),
) -> ChatResponse:
    return agent.chat(request)


@router.get("/chat/history")
def chat_history(
    limit: int = 50,
    agent: Agent = Depends(get_agent),
    _: None = Depends(verify_agent_key),
) -> list[dict]:
    return agent.get_history(limit)


@router.delete("/chat/memory/{session_id}")
def clear_chat_memory(
    session_id: str,
    agent: Agent = Depends(get_agent),
    _: None = Depends(verify_agent_key),
) -> dict[str, str]:
    """Clears conversation memory for the given session_id."""
    agent.memory.clear(session_id)
    return {"status": "ok", "session_id": session_id}



@router.get("/tools")
def list_available_tools(
    agent: Agent = Depends(get_agent),
    _: None = Depends(verify_agent_key),
) -> list[dict]:
    """Returns public metadata for all tools registered with the Agent."""
    return agent.registry.list_tool_metadata()

from toolset.tool_layer import SearchTool
from agent.schemas.common import StatusCode
from agent.runtime.state import AgentState

@router.post("/chat/stream")
def chat_stream(
    request: ChatRequest,
    agent: Agent = Depends(get_agent),
    _: None = Depends(verify_agent_key),
) -> StreamingResponse:
    def event_stream():
        trace_id = agent.trace_service.start_trace()
        start_time = agent.audit_service.start_timer()
        try:
            import re

            # =========================================================================
            # FAST MODE: Independent direct RAG pipeline without agent multi-turn loops
            # =========================================================================
            if request.weight_mode == "fast":
                # 1. Direct Knowledge Base Search (0 pre-LLM overhead)
                search_tool = agent.registry.get_tool("search_documents")
                results = []
                if isinstance(search_tool, SearchTool):
                    results = search_tool.search(
                        query=request.query,
                        top_k=request.top_k or 5,
                        mode=request.retrieval_mode or "hybrid",
                        topic_doc_ids=request.topic_doc_ids,
                        topic_titles=request.topic_titles,
                        weight_mode="fast",
                        consecutive_no_new_docs_count=request.consecutive_no_new_docs_count or 0,
                    )

                # 2. Immediately yield citations event
                citations = [
                    Citation(
                        citation_id=idx,
                        doc_id=str(r.get("doc_id", "") or ""),
                        chunk_id=str(r.get("chunk_id", "") or ""),
                        title=str(r.get("title", f"Document {idx}") or f"Document {idx}"),
                        source_url=r.get("source_url", None),
                        score=float(r.get("score", 0.0)) if r.get("score") is not None else None,
                        snippet=str(r.get("chunk_text", r.get("snippet", r.get("content", ""))) or ""),
                    )
                    for idx, r in enumerate(results, start=1)
                ]
                yield build_sse_event("citations", [c.model_dump() for c in citations])

                # 3. Build reference context
                context_blocks = []
                for idx, c in enumerate(citations, start=1):
                    context_blocks.append(f"[{idx}] 标题: {c.title}\n内容: {c.snippet}")
                context_text = "\n\n".join(context_blocks) if context_blocks else "无相关参考文档"

                # 4. Construct direct conversation prompt with context
                history = agent.orchestrator._read_history(request.session_id)
                is_first = request.is_first_message if request.is_first_message is not None else (len(history) == 0)
                title_directive = (
                    "\n\n【极重要指令】：这是本对话的第一个提问。请务必在最终回答的第一行输出您总结的对话标题，格式必须为：[TITLE: 3-10字精炼标题]，然后再换行输出正文回答。"
                    if is_first
                    else ""
                )

                system_prompt = (
                    "你是一个高效、精准的智能知识库问答助手。请根据提供的【参考上下文】详细回答用户的问题。\n"
                    "回答要求：\n"
                    "1. 事实严格基于参考上下文，条理清晰、层次分明；\n"
                    "2. 如果参考上下文未包含答案，请如实说明，并结合已知通用常识给出清晰提示；\n"
                    "3. 在引用上下文事实的地方，可适当标注引用编号（如 [1]、[2]）；\n"
                    "4. 直接输出最终回答，不要输出任何工具调用代码或标签。"
                    f"{title_directive}"
                )

                fast_messages = [{"role": "system", "content": system_prompt}]
                for msg in (history or []):
                    if msg.get("role") in ("user", "assistant") and msg.get("content"):
                        fast_messages.append({"role": msg["role"], "content": msg["content"]})
                
                fast_messages.append({
                    "role": "user",
                    "content": f"【参考上下文】:\n{context_text}\n\n【用户问题】:\n{request.query}"
                })

                # 5. Stream response directly from LLM
                accumulated_answer = ""
                for delta in agent.llm.stream_chat(fast_messages):
                    reasoning = delta.get("reasoning_content")
                    content = delta.get("content")
                    if reasoning:
                        yield build_sse_event("reasoning", {"content": reasoning})
                    if content:
                        clean_content = re.sub(r"<longcat_.*?/?>|</longcat_.*?>", "", content)
                        if clean_content:
                            accumulated_answer += clean_content
                            yield build_sse_event("token", {"content": clean_content})

                # 6. Separate title and answer
                extracted_title, clean_answer = agent._separate_title_and_answer(accumulated_answer)
                chat_title = extracted_title
                if not chat_title and is_first:
                    chat_title = agent._generate_fallback_title(request.query)

                agent.orchestrator.memory.add_message(request.session_id, "user", request.query)
                agent.orchestrator.memory.add_message(request.session_id, "assistant", clean_answer)

                yield build_sse_event(
                    "done",
                    {
                        "trace_id": trace_id,
                        "status": "success",
                        "citations_count": len(citations),
                        "chat_title": chat_title,
                    },
                )
                return

            # =========================================================================
            # THINKING / AUTO MODE: Full Agent Planning & Reasoning Pipeline
            # =========================================================================
            search_tool = agent.registry.get_tool("search_documents")
            if isinstance(search_tool, SearchTool):
                search_tool.topic_doc_ids = request.topic_doc_ids
                search_tool.topic_titles = request.topic_titles
                search_tool.weight_mode = request.weight_mode or "auto"
                search_tool.consecutive_no_new_docs_count = request.consecutive_no_new_docs_count or 0

            history = agent.orchestrator._read_history(request.session_id)
            plan = agent.orchestrator._resolve_query_plan(request, None, history)
            policy = agent.orchestrator.policy_router.route(plan)
            retrieval_mode, top_k = agent.orchestrator._effective_retrieval_options(request, policy)
            is_first = request.is_first_message if request.is_first_message is not None else (len(history) == 0)

            state = AgentState(
                trace_id=trace_id,
                query_plan=plan,
                messages=agent.orchestrator.runner._build_messages(
                    plan,
                    history or [],
                    is_first_message=is_first,
                    soul_content=request.soul_content,
                ),
            )

            # 1. Execute tool calling for retrieval (supports multi-turn retrieval iterations)
            for iteration in range(1, 3):
                schemas = agent.orchestrator.runner._tool_schemas(policy)
                initial_res = agent.llm.chat(state.messages, tools=schemas)
                tool_calls = initial_res.get("tool_calls") or []

                # Handle raw longcat tool call text format if emitted
                content_str = initial_res.get("content") or ""
                if not tool_calls and "<longcat_tool_call>" in content_str:
                    match = re.search(r"<longcat_tool_call>(\w+)(.*?)</longcat_tool_call>", content_str, re.DOTALL)
                    if match:
                        t_name = match.group(1).strip()
                        args_raw = match.group(2)
                        arg_matches = re.findall(r"<longcat_arg_key>(\w+)</longcat_arg_key>\s*<longcat_arg_value>(.*?)</longcat_arg_value>", args_raw, re.DOTALL)
                        t_args = {k: v.strip() for k, v in arg_matches}
                        import json as pyjson
                        tool_calls = [{"id": f"call_longcat_{iteration}", "type": "function", "function": {"name": t_name, "arguments": pyjson.dumps(t_args)}}]

                if not tool_calls:
                    break

                state.messages.append(agent.orchestrator.runner._assistant_tool_call_message(initial_res, tool_calls))
                for raw_call in tool_calls:
                    call_id, tool_name, arguments = agent.orchestrator.runner._parse_tool_call(raw_call)
                    arguments = agent.orchestrator.runner._apply_execution_constraints(
                        tool_name=tool_name,
                        arguments=arguments,
                        query_plan=plan,
                        mode=retrieval_mode,
                        top_k=top_k,
                    )
                    tool = agent.orchestrator.runner._get_tool(tool_name, policy)
                    if tool:
                        observation, evidence, is_retrieval = agent.orchestrator.runner._execute_tool(
                            tool=tool,
                            tool_name=tool_name,
                            arguments=arguments,
                            query_plan=plan,
                            trace_id=trace_id,
                            tool_call_id=call_id,
                            tool_executor=agent.orchestrator.tool_executor,
                            retrieval_attempt=iteration,
                        )
                        if evidence:
                            state.evidence.extend(evidence)
                        state.messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": tool_name,
                            "content": observation,
                        })

            # Build and yield citations immediately so client displays retrieved document chunks
            def _get_ev(item, key, default=None):
                if isinstance(item, dict):
                    return item.get(key, default)
                return getattr(item, key, default)

            citations = [
                Citation(
                    citation_id=idx,
                    doc_id=str(_get_ev(ev, "doc_id", "") or ""),
                    chunk_id=str(_get_ev(ev, "chunk_id", "") or ""),
                    title=_get_ev(ev, "title", f"Document {idx}") or f"Document {idx}",
                    source_url=_get_ev(ev, "source_url", None),
                    score=float(_get_ev(ev, "score", 0.0)) if _get_ev(ev, "score") is not None else None,
                    snippet=str(_get_ev(ev, "chunk_text", _get_ev(ev, "snippet", _get_ev(ev, "content", ""))) or ""),
                )
                for idx, ev in enumerate(state.evidence, start=1)
            ]
            yield build_sse_event(
                "citations",
                [c.model_dump() for c in citations],
            )

            # 2. Add final response guidance and stream tokens directly from LLM
            state.messages.append({
                "role": "system",
                "content": "请基于已检索到的知识库事实与文档，直接给出完整、条理清晰的最终解答。不要输出任何工具调用标签。"
            })

            accumulated_answer = ""
            for delta in agent.llm.stream_chat(state.messages):
                reasoning = delta.get("reasoning_content")
                content = delta.get("content")
                if reasoning:
                    yield build_sse_event("reasoning", {"content": reasoning})
                if content:
                    # Filter out any leaked tool call tags
                    clean_content = re.sub(r"<longcat_.*?/?>|</longcat_.*?>", "", content)
                    if clean_content:
                        accumulated_answer += clean_content
                        yield build_sse_event("token", {"content": clean_content})

            # Separate title and answer if generated
            extracted_title, clean_answer = agent._separate_title_and_answer(accumulated_answer)
            chat_title = extracted_title
            if not chat_title and is_first:
                chat_title = agent._generate_fallback_title(request.query)

            # 3. Yield done event
            yield build_sse_event(
                "done",
                {
                    "trace_id": trace_id,
                    "status": "success",
                    "citations_count": len(citations),
                    "chat_title": chat_title,
                },
            )

            # Save turn to conversation memory
            resp_obj = ChatResponse(
                trace_id=trace_id,
                query=request.query,
                status=StatusCode.SUCCESS,
                answer=clean_answer or accumulated_answer,
                message="",
                citations=citations,
                chat_title=chat_title,
            )
            agent._save_conversation_turn(
                session_id=request.session_id,
                query=plan.original_query,
                response=resp_obj,
            )

        except Exception as exc:
            yield build_sse_event("error", {"message": str(exc)})
        finally:
            agent.trace_service.clear_trace()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


from pydantic import BaseModel
from services.summarizer.topic_summarizer import TopicSummarizer

class SummarizeTopicRequest(BaseModel):
    topic_id: str
    discussion_text: str
    custom_title: Optional[str] = None
    existing_info: Optional[dict] = None

@router.post("/topics/summarize")
def summarize_topic(
    req: SummarizeTopicRequest,
    _: None = Depends(verify_agent_key),
):
    """
    Triggers Data Persistence Layer Summarizer Service.
    Generates Title, Description, Soul Cognition (Soul.md), and Content Tags,
    and directly writes artifacts into data-persistence/data/topics/<topic_id>/
    """
    result = TopicSummarizer.summarize_and_persist(
        topic_id=req.topic_id,
        discussion_text=req.discussion_text,
        custom_title=req.custom_title,
        existing_info=req.existing_info
    )
    return result


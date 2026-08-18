from typing import Optional
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from agent.schemas.chat import ChatRequest, ChatResponse, Citation
from agent.agent import Agent
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
) -> ChatResponse:
    return agent.chat(request)


@router.get("/chat/history")
def chat_history(
    limit: int = 50,
    agent: Agent = Depends(get_agent),
) -> list[dict]:
    return agent.get_history(limit)


@router.delete("/chat/memory/{session_id}")
def clear_chat_memory(
    session_id: str,
    agent: Agent = Depends(get_agent),
) -> dict[str, str]:
    """Clears conversation memory for the given session_id."""
    agent.memory.clear(session_id)
    return {"status": "ok", "session_id": session_id}



@router.get("/tools")
def list_available_tools(
    agent: Agent = Depends(get_agent),
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
) -> StreamingResponse:
    def event_stream():
        trace_id = agent.trace_service.start_trace()
        start_time = agent.audit_service.start_timer()
        try:
            # 1. Execute query plan & knowledge retrieval tools
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

            # Execute tool calling for retrieval
            schemas = agent.orchestrator.runner._tool_schemas(policy)
            initial_res = agent.llm.chat(state.messages, tools=schemas)
            tool_calls = initial_res.get("tool_calls") or []

            if tool_calls:
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
                    observation, evidence, is_retrieval = agent.orchestrator.runner._execute_tool(
                        tool=tool,
                        tool_name=tool_name,
                        arguments=arguments,
                        query_plan=plan,
                        trace_id=trace_id,
                        tool_call_id=call_id,
                        tool_executor=agent.orchestrator.tool_executor,
                        retrieval_attempt=1,
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
            citations = [
                Citation(
                    citation_id=idx,
                    doc_id=ev.doc_id,
                    chunk_id=ev.chunk_id,
                    title=ev.title or f"Document {idx}",
                    source_url=ev.source_url,
                    score=ev.score,
                    snippet=getattr(ev, 'chunk_text', getattr(ev, 'snippet', ''))
                )
                for idx, ev in enumerate(state.evidence, start=1)
            ]
            yield build_sse_event(
                "citations",
                [c.model_dump() for c in citations],
            )

            # 2. Stream tokens directly from LLM (reasoning_content and content tokens)
            accumulated_answer = ""
            for delta in agent.llm.stream_chat(state.messages):
                reasoning = delta.get("reasoning_content")
                content = delta.get("content")
                if reasoning:
                    yield build_sse_event("reasoning", {"content": reasoning})
                if content:
                    accumulated_answer += content
                    yield build_sse_event("token", {"content": content})

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
def summarize_topic(req: SummarizeTopicRequest):
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


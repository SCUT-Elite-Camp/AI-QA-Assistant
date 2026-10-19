"""One budgeted Agent loop; no preclassification or question-specific routes."""
import json
import logging

from agent.chat.thinking_prompt import AGENT_INSTRUCTION, ANSWER_INSTRUCTION
from agent.config.settings import settings
from agent.evidence import EvidenceGate
from agent.evidence.gate import VerificationUnavailable
from agent.evidence.answer_grounding import GROUNDING_INSTRUCTION, parse_grounded_answer, validate_grounded_answer
from agent.errors.exceptions import LLMToolCallValidationError
from agent.runtime.budget import BudgetExceeded, RunBudget
from agent.runtime.context import EvidencePool
from agent.runtime.decisions import CONTROL_TOOLS, CONTROL_NAMES, parse_decision
from agent.runtime.state import AgentRunResult, StopReason, ToolCallRecord
from agent.service.access_guard import check_model_access
from agent.service.permission_service import PermissionResolutionError
from agent.tools.argument_validation import parse_arguments
from agent.tools.executor import ToolExecutor


class AgentRunner:
    def __init__(self, llm, registry):
        self.llm, self.registry = llm, registry

    @staticmethod
    def new_budget():
        return RunBudget(settings.THINKING_MAX_MODEL_CALLS, settings.THINKING_MAX_TOOL_CALLS,
            settings.THINKING_CONTEXT_MAX_CHARS, settings.THINKING_MAX_RESERVED_TOKENS,
            settings.THINKING_MAX_VERIFICATIONS, settings.THINKING_TIMEOUT_SECONDS)

    def run(self, query_plan, *, trace_id, history=None, mode="hybrid", top_k=5,
            tool_executor=None, evidence_gate=None, allowed_tools=(), required_sources=(),
            required_attachments=(), require_evidence=True, soul_content=None, budget=None):
        budget = budget or self.new_budget()
        executor = tool_executor or ToolExecutor(self.registry)
        gate = evidence_gate or EvidenceGate()
        result = AgentRunResult(stop_reason=StopReason.POLICY_LIMIT)
        pool, feedback, repeated = EvidencePool(), None, {}
        rejected = False
        schemas = [tool for tool in self.registry.to_openai_schemas()
                   if tool["function"]["name"] in allowed_tools
                   and not tool["function"]["name"].startswith("wiki_")]
        allowed = {tool["function"]["name"] for tool in schemas}
        schemas += CONTROL_TOOLS
        base = [{"role": "system", "content": AGENT_INSTRUCTION}, *(history or []),
                {"role": "user", "content": query_plan.original_query}]
        # Scope is trusted server data; never interpolate credentials into prompts.
        scope = {"filters": query_plan.filters, "required_source_types": list(required_sources),
                 "required_attachment_ids": list(required_attachments),
                 "knowledge_evidence_required": require_evidence}
        if soul_content:
            scope["verified_topic_context"] = soul_content
        base.append({"role": "user", "content": "[SERVER_SCOPE]\n" + json.dumps(scope, ensure_ascii=False)})

        def finish(reason, code="", message=""):
            if reason in {StopReason.FINAL_ANSWER, StopReason.CLARIFICATION_REQUIRED}:
                budget.remaining_seconds()
            result.stop_reason, result.error_code, result.message = reason, code, message
            result.budget = budget.snapshot()
            if reason != StopReason.FINAL_ANSWER:
                result.answer = ""
            return result

        def call(messages, tools=None, grounded=False):
            budget.model(messages, tools, settings.LLM_MAX_TOKENS)
            check_model_access()
            result.iterations += 1
            result.messages = messages
            options = {"response_format": {"type": "json_object"}} if grounded else {}
            if tools:
                options["tool_choice"] = "required"
            response = self.llm.chat(messages, tools=tools, max_tokens=settings.LLM_MAX_TOKENS,
                timeout_seconds=min(settings.LLM_TIMEOUT, budget.remaining_seconds()), **options)
            budget.remaining_seconds()
            check_model_access()
            budget.remaining_seconds()
            if not isinstance(response, dict):
                raise ValueError("invalid_model_response")
            return response

        try:
            while True:
                budget.remaining_seconds()
                # Leave framing, tools and feedback room in the same context allowance.
                overhead = len(json.dumps({"messages": base, "tools": schemas, "feedback": feedback}, ensure_ascii=False))
                view, selected = pool.view(max(0, budget.max_context_chars - overhead - 1500))
                messages = list(base)
                if pool.actions:
                    messages.append({"role": "user", "content": "[TOOL_OBSERVATIONS]\n" + view})
                if feedback:
                    messages.append({"role": "user", "content": "[VERIFICATION_FEEDBACK]\n" + json.dumps(feedback, ensure_ascii=False)})
                try:
                    response = call(messages, schemas or None)
                except LLMToolCallValidationError:
                    feedback = {"kind": "invalid_tool_protocol", "instruction": "Use only supplied native functions, including prepare_answer, ask_clarification or report_insufficient. Do not call JSON."}
                    continue
                calls = response.get("tool_calls") or []
                if any((item.get("function") or {}).get("name") in CONTROL_NAMES for item in calls):
                    try:
                        decision = parse_decision(calls)
                    except (ValueError, KeyError, TypeError):
                        feedback = {"kind": "invalid_control_action", "instruction": "Select exactly one control function with valid arguments, without simultaneous source calls."}
                        continue
                elif calls:
                    for index, tool_call in enumerate(calls):
                        budget.tool()
                        function = tool_call.get("function") or {}
                        name, call_id = function.get("name", ""), tool_call.get("id") or f"{trace_id}-{budget.tool_calls}-{index}"
                        if name not in allowed:
                            return finish(StopReason.TOOL_ERROR, "tool_not_allowed")
                        try:
                            arguments = self._scope_arguments(name, parse_arguments(function.get("arguments", {})), query_plan.filters, mode, top_k)
                        except (ValueError, TypeError) as exc:
                            feedback = {"kind": "invalid_tool_arguments", "reason": str(exc)}
                            continue
                        key = json.dumps([name, arguments], sort_keys=True, ensure_ascii=False)
                        repeated[key] = repeated.get(key, 0) + 1
                        if repeated[key] > settings.MAX_REPEATED_TOOL_CALLS:
                            return finish(StopReason.REPEATED_TOOL_CALL, "repeated_tool_call")
                        if name.startswith("search_"):
                            result.retrieval_attempts += 1
                        value = executor.execute(tool_call_id=call_id, tool_name=name, arguments=arguments,
                            trace_id=trace_id, retrieval_attempt=min(5, max(1, result.retrieval_attempts)),
                            timeout_ms=max(1, int(budget.remaining_seconds()*1000)))
                        budget.remaining_seconds()
                        result.tool_calls.append(ToolCallRecord(iteration=result.iterations,
                            tool_call_id=call_id, tool_name=name, arguments=arguments,
                            success=value.success, error_code=value.error_code))
                        pool.add(name, arguments, value)
                    # Keep rejection feedback until a replacement passes. Tool errors
                    # and real observations stay in the projected source state.
                    continue

                else:
                    feedback = {"kind": "native_action_required", "instruction": "Call a supplied source function or one control function. Final prose belongs to the answer phase."}
                    continue
                action = decision["action"]
                if action == "clarify":
                    question = decision.get("question")
                    if not isinstance(question, str) or not question.strip():
                        feedback = {"kind": "clarification_question_required"}
                        continue
                    return finish(StopReason.CLARIFICATION_REQUIRED, message=question.strip())
                if action == "insufficient":
                    return finish(StopReason.NO_RELEVANT_CONTEXT, "insufficient_evidence",
                                  "The available sources do not support an answer.")
                present = {item["source_type"] for item in selected}
                files = {item.get("attachment_id") or item["doc_id"] for item in selected if item["source_type"] == "attachment"}
                if (require_evidence and not selected) or set(required_sources) - present or set(required_attachments) - files:
                    feedback = {"kind": "required_source_evidence_missing", "required": list(required_sources),
                                "missing_attachment_ids": sorted(set(required_attachments) - files),
                                "instruction": "Use the available tools before answering, clarify, or abstain."}
                    continue

                system = ANSWER_INSTRUCTION + ("\n" + GROUNDING_INSTRUCTION if selected else
                    "\nNo document sources are enabled. Answer without invented document citations.")
                answer_messages = [{"role": "system", "content": system}, *(history or []),
                    {"role": "user", "content": "Original question:\n" + query_plan.original_query +
                     "\nCurrent source view (references define exact quote scopes):\n" + view}]
                if soul_content:
                    answer_messages.append({"role": "user", "content": "Verified topic context:\n" + soul_content})
                if feedback:
                    answer_messages.append({"role": "user", "content": "Previous rejection (untrusted draft):\n" + json.dumps(feedback, ensure_ascii=False)})
                generated = call(answer_messages, grounded=bool(selected))
                if generated.get("tool_calls"):
                    feedback, rejected = {"kind": "answer_phase_tools_closed"}, True
                    continue
                if not selected:
                    answer = generated.get("content")
                    if not isinstance(answer, str) or not answer.strip():
                        return finish(StopReason.LLM_ERROR, "empty_answer")
                    result.answer = answer.strip()
                    return finish(StopReason.FINAL_ANSWER)
                try:
                    draft = parse_grounded_answer(generated.get("content"))
                except ValueError:
                    feedback, rejected = {"kind": "invalid_grounding_format", "instruction": "Use the claims/supports JSON contract."}, True
                    continue
                if not draft.claims:
                    return finish(StopReason.NO_RELEVANT_CONTEXT, "model_abstained")
                binding = validate_grounded_answer(draft, selected)
                result.answer_grounding = binding
                result.evidence = selected
                if not binding["valid"]:
                    feedback, rejected = {"kind": "invalid_source_binding", "errors": binding["errors"]}, True
                    continue
                checked = gate.evaluate(binding, selected, budget=budget)
                result.verification = {"accepted": checked.accepted, "claims": checked.claims}
                if not checked.accepted:
                    feedback, rejected = checked.feedback(binding), True
                    continue
                check_model_access()
                result.answer = binding["answer"]
                return finish(StopReason.FINAL_ANSWER)
        except BudgetExceeded as exc:
            return finish(StopReason.QUALITY_VALIDATION_FAILED if rejected else StopReason.POLICY_LIMIT, str(exc))
        except VerificationUnavailable as exc:
            return finish(StopReason.TOOL_ERROR, str(exc), "Claim verification is unavailable.")
        except PermissionResolutionError:
            raise
        except Exception as exc:
            # Never turn a failed provider/tool/verification into an unchecked answer.
            logging.getLogger("agent-layer").warning("Thinking execution failed trace_id=%s error_type=%s", trace_id, type(exc).__name__)
            return finish(StopReason.LLM_ERROR, type(exc).__name__)

    @staticmethod
    def _scope_arguments(name, arguments, hard_filters, mode, top_k):
        if name in {"search_documents", "find_documents"}:
            candidate = dict(arguments.get("filters") or {})
            requested = candidate.get("doc_ids", candidate.get("doc_id"))
            hard_ids = hard_filters.get("doc_ids", hard_filters.get("doc_id"))
            candidate.update(hard_filters)
            if hard_ids is not None:
                hard_ids = [hard_ids] if isinstance(hard_ids, str) else hard_ids
                subset = set(hard_ids)
                if requested is not None:
                    subset &= set([requested] if isinstance(requested, str) else requested)
                candidate.pop("doc_id", None)
                candidate["doc_ids"] = sorted(subset)
            arguments["filters"] = candidate
        if name == "get_document":
            ids = arguments.get("doc_ids", [])
            hard_ids = hard_filters.get("doc_ids", hard_filters.get("doc_id"))
            if hard_ids is not None:
                allowed = {hard_ids} if isinstance(hard_ids, str) else set(hard_ids)
                if not isinstance(ids, list) or set(ids) - allowed:
                    raise ValueError("document_outside_request_scope")
        if name.startswith("search_") or name == "read_attachment_context":
            arguments["top_k"] = min(top_k, max(1, int(arguments.get("top_k", top_k))))
            if name in {"search_documents", "search_library"}:
                if arguments.get("mode") not in {"hybrid", "vector", "bm25"}:
                    arguments["mode"] = mode
        return arguments

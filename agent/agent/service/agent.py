import json
from typing import List, Dict, Any
from agent.llm.base import BaseLLM
from toolset.tool_layer.base_tool import BaseTool


class Agent:
    """A unified Agent class implementing a ReAct-style loop with tool execution."""

    def __init__(self, llm: BaseLLM, tools: List[BaseTool], system_prompt: str = ""):
        self.llm = llm
        self.tools = {t.name: t for t in tools}
        self.system_prompt = system_prompt

    def run(self, query: str, max_iterations: int = 5) -> str:
        """Runs the agent loop to completion, calling tools as decided by the LLM."""
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": query})

        # Pre-convert tools to OpenAI schema format
        openai_tools = [t.to_openai_schema() for t in self.tools.values()]

        for _ in range(max_iterations):
            # 1. Ask the LLM what to do
            response = self.llm.chat(messages, tools=openai_tools if openai_tools else None)

            # 2. Check if the LLM wants to call tools
            tool_calls = response.get("tool_calls")
            if tool_calls:
                # Add the assistant's decision to messages
                messages.append(response)

                # Execute all requested tool calls
                for tc in tool_calls:
                    function_info = tc.get("function", {})
                    name = function_info.get("name")
                    arguments_str = function_info.get("arguments", "{}")

                    try:
                        args = json.loads(arguments_str) if arguments_str else {}
                    except Exception:
                        args = {}

                    tool = self.tools.get(name)
                    if tool:
                        result = tool.execute(**args)
                    else:
                        result = f"Error: Tool {name} not found."

                    # Append tool response
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "name": name,
                        "content": str(result)
                    })
            else:
                # 3. No more tool calls: return final content
                return response.get("content") or ""

        # Fallback if iterations exceed limit
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg.get("content")
        return "Agent execution exceeded maximum iterations without a final answer."

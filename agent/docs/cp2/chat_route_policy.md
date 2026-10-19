# Chat execution boundary

Updated 2026-10-19: there is no ChatRoutePolicy, semantic intent classifier or
L0/L1/L2 dispatcher. The user explicitly chooses Fast or Thinking; auto aliases
Thinking. See the [current mode contract](../chat_mode_contract.md).

Thinking begins with the original question and permitted native tools in one
budgeted Agent loop. Its Prompt handles clarification, rewriting and strategy.
Source tools and native control actions cannot create Research jobs, widen
server scope or change retrieval to a Research mode. Research remains its
separate approved API. Production source guards and the Thinking loop are
covered by test_chat_modes.py and test_chat_research_boundary.py.

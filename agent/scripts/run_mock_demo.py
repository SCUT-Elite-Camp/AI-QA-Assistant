import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.schemas.chat import ChatRequest
from agent.service.chat_service import ChatService


def main() -> None:
    service = ChatService()
    response = service.chat(ChatRequest(query="项目 Q1 阶段需要完成哪些功能？"))
    print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

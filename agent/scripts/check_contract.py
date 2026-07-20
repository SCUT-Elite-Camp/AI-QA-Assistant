import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.schemas.chat import ChatRequest, ChatResponse


def main() -> None:
    request_schema = ChatRequest.model_json_schema()
    response_schema = ChatResponse.model_json_schema()
    print("ChatRequest fields:", sorted(request_schema["properties"].keys()))
    print("ChatResponse fields:", sorted(response_schema["properties"].keys()))


if __name__ == "__main__":
    main()

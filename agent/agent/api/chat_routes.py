from fastapi import APIRouter

from agent.schemas.chat import ChatRequest, ChatResponse
from agent.service.chat_service import ChatService

router = APIRouter()
chat_service = ChatService()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    return chat_service.chat(request)


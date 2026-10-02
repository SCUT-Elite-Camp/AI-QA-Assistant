"""Agent Layer 服务认证。

Agent 服务仅接受 Web 可信端的调用（内网单向可信链路）。通过共享密钥
（Bearer token）校验请求来源，防止外部直连 agent 端口伪造 user_id 绕过
Web 层权限隔离。

使用方式（FastAPI dependency）：

    @router.post("/chat")
    def chat(..., _: None = Depends(verify_agent_key)):
        ...

校验逻辑：
- AGENT_API_KEY 未配置 -> 503（服务拒绝启动认证，明确失败而非放行）
- Authorization 头缺失或格式不正确 -> 401
- 值不匹配 -> 401（使用 secrets.compare_digest 恒定时间比较，防时序攻击）
"""

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agent.config.settings import settings

_bearer = HTTPBearer(auto_error=False)


def verify_agent_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """FastAPI dependency：校验 Agent 接口调用方是否持有有效共享密钥。"""
    if not settings.AGENT_API_KEY:
        # 密钥未配置：显式拒绝服务，避免“无认证可用”的静默放行。
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent service is not configured with AGENT_API_KEY.",
        )

    # HTTPBearer(auto_error=False) 在缺少/非法头时注入 None。
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
        )

    import secrets

    if not secrets.compare_digest(credentials.credentials, settings.AGENT_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )

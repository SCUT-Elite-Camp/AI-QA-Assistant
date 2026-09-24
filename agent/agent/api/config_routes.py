import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from agent.auth import verify_agent_key
from agent.config.settings import settings
import agent.api.chat_routes as chat_routes

router = APIRouter(prefix="/api/config", tags=["config"])


class LLMConfigResponse(BaseModel):
    llm_api_base: str
    llm_model: str
    llm_api_key_masked: str
    has_api_key: bool
    llm_http_proxy: Optional[str] = None
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2000
    llm_timeout: int = 60


class LLMTestRequest(BaseModel):
    llm_api_base: str
    llm_model: str
    llm_api_key: Optional[str] = None
    llm_http_proxy: Optional[str] = None
    llm_temperature: Optional[float] = 0.1
    llm_timeout: Optional[int] = 30


class LLMTestResponse(BaseModel):
    success: bool
    latency_ms: int
    reply: Optional[str] = None
    model: str
    error: Optional[str] = None


class LLMSaveRequest(BaseModel):
    llm_api_base: str
    llm_model: str
    llm_api_key: Optional[str] = None
    llm_http_proxy: Optional[str] = None
    llm_temperature: Optional[float] = 0.1
    llm_max_tokens: Optional[int] = 2000
    llm_timeout: Optional[int] = 60


class LLMSaveResponse(BaseModel):
    success: bool
    message: str


def _mask_key(key: str) -> str:
    if not key:
        return ""
    key = key.strip()
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def _update_env_file(filepath: Path, updates: dict[str, str]) -> None:
    """Updates key-value pairs in a .env file while preserving comments and existing structure."""
    if not filepath.exists():
        filepath.parent.mkdir(parents=True, exist_ok=True)
        content = ""
    else:
        content = filepath.read_text(encoding="utf-8")

    lines = content.splitlines()
    found_keys = set()
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue

        matched_key = None
        for key in updates.keys():
            if re.match(rf"^{re.escape(key)}\s*=", stripped):
                matched_key = key
                break

        if matched_key:
            new_lines.append(f"{matched_key}={updates[matched_key]}")
            found_keys.add(matched_key)
        else:
            new_lines.append(line)

    for key, val in updates.items():
        if key not in found_keys:
            new_lines.append(f"{key}={val}")

    filepath.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


@router.get("/llm", response_model=LLMConfigResponse)
def get_llm_config(_: None = Depends(verify_agent_key)) -> LLMConfigResponse:
    """Get current LLM configuration with masked API key."""
    proxy = os.getenv("LLM_HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or ""
    return LLMConfigResponse(
        llm_api_base=settings.LLM_API_BASE,
        llm_model=settings.LLM_MODEL,
        llm_api_key_masked=_mask_key(settings.LLM_API_KEY),
        has_api_key=bool(settings.LLM_API_KEY),
        llm_http_proxy=proxy,
        llm_temperature=settings.LLM_TEMPERATURE,
        llm_max_tokens=settings.LLM_MAX_TOKENS,
        llm_timeout=settings.LLM_TIMEOUT,
    )


@router.post("/llm/test", response_model=LLMTestResponse)
def test_llm_connection(
    payload: LLMTestRequest,
    _: None = Depends(verify_agent_key),
) -> LLMTestResponse:
    """Test LLM API connectivity with specified credentials and parameters."""
    api_key = payload.llm_api_key.strip() if payload.llm_api_key and payload.llm_api_key.strip() else settings.LLM_API_KEY
    endpoint = f"{payload.llm_api_base.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = {
        "model": payload.llm_model.strip(),
        "messages": [
            {"role": "user", "content": "Respond with 'Hello, API connection is successful.' in one short sentence."}
        ],
        "temperature": payload.llm_temperature if payload.llm_temperature is not None else 0.1,
        "max_tokens": 100,
    }

    session = requests.Session()
    proxy = payload.llm_http_proxy.strip() if payload.llm_http_proxy and payload.llm_http_proxy.strip() else (os.getenv("LLM_HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY"))
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    else:
        session.trust_env = True

    timeout = payload.llm_timeout or 15
    start_time = time.perf_counter()

    try:
        resp = session.post(endpoint, json=body, headers=headers, timeout=timeout)
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        if resp.status_code == 200:
            data = resp.json()
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            return LLMTestResponse(
                success=True,
                latency_ms=elapsed_ms,
                reply=reply or "连接成功，收到有效响应",
                model=payload.llm_model,
            )

        err_detail = resp.text
        try:
            err_json = resp.json()
            if "error" in err_json:
                err_detail = err_json["error"].get("message") or str(err_json["error"])
        except Exception:
            pass

        return LLMTestResponse(
            success=False,
            latency_ms=elapsed_ms,
            model=payload.llm_model,
            error=f"HTTP {resp.status_code}: {err_detail[:300]}",
        )
    except requests.Timeout:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return LLMTestResponse(
            success=False,
            latency_ms=elapsed_ms,
            model=payload.llm_model,
            error=f"请求超时（超过 {timeout} 秒），请检查 API 地址或代理设置",
        )
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return LLMTestResponse(
            success=False,
            latency_ms=elapsed_ms,
            model=payload.llm_model,
            error=f"网络或连接异常: {str(exc)}",
        )


@router.post("/llm/save", response_model=LLMSaveResponse)
def save_llm_config(
    payload: LLMSaveRequest,
    _: None = Depends(verify_agent_key),
) -> LLMSaveResponse:
    """Save LLM configuration to agent/.env and apply it to runtime immediately."""
    api_key = payload.llm_api_key.strip() if payload.llm_api_key and payload.llm_api_key.strip() else settings.LLM_API_KEY
    proxy = payload.llm_http_proxy.strip() if payload.llm_http_proxy is not None else (os.getenv("LLM_HTTP_PROXY") or "")

    updates = {
        "LLM_API_BASE": payload.llm_api_base.strip(),
        "LLM_MODEL": payload.llm_model.strip(),
        "LLM_API_KEY": api_key,
        "LLM_HTTP_PROXY": proxy,
        "LLM_TEMPERATURE": str(payload.llm_temperature if payload.llm_temperature is not None else 0.1),
        "LLM_MAX_TOKENS": str(payload.llm_max_tokens if payload.llm_max_tokens is not None else 2000),
        "LLM_TIMEOUT": str(payload.llm_timeout if payload.llm_timeout is not None else 60),
    }

    # 1. Update agent/.env
    agent_dir = Path(__file__).resolve().parents[2]
    agent_env = agent_dir / ".env"
    _update_env_file(agent_env, updates)

    # 2. Update root .env if it exists
    root_env = agent_dir.parent / ".env"
    if root_env.exists():
        _update_env_file(root_env, updates)

    # 3. Apply to runtime settings
    settings.LLM_API_BASE = updates["LLM_API_BASE"]
    settings.LLM_MODEL = updates["LLM_MODEL"]
    settings.LLM_API_KEY = updates["LLM_API_KEY"]
    if updates["LLM_HTTP_PROXY"]:
        os.environ["LLM_HTTP_PROXY"] = updates["LLM_HTTP_PROXY"]
    elif "LLM_HTTP_PROXY" in os.environ:
        del os.environ["LLM_HTTP_PROXY"]

    settings.LLM_TEMPERATURE = float(updates["LLM_TEMPERATURE"])
    settings.LLM_MAX_TOKENS = int(updates["LLM_MAX_TOKENS"])
    settings.LLM_TIMEOUT = int(updates["LLM_TIMEOUT"])

    # 4. Reset singleton Agent instance so newly configured client is created on next request
    chat_routes._agent_instance = None

    return LLMSaveResponse(
        success=True,
        message="LLM API 配置已成功保存至 .env 并即时生效！",
    )

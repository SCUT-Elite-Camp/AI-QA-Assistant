"""
文本向量化模块。

支持两种显式配置的模式：
1. EMBEDDING_PROVIDER=api — 使用 OpenAI 兼容接口
2. EMBEDDING_PROVIDER=local — 使用本地 BGE 模型（默认）

本地模式优先通过 HuggingFace（或 HF_ENDPOINT 镜像）下载模型，
若失败则回退到 ModelScope 下载。模型缓存到本地，仅首次运行需联网。
"""

import gc
import os
from functools import lru_cache

# ─── 本地模型常量 ───────────────────────────────────────

_LOCAL_MODEL_NAME = os.environ.get("LOCAL_EMBEDDING_MODEL_NAME", "BAAI/bge-m3")
_LOCAL_MODEL_DIM = int(os.environ.get("LOCAL_EMBEDDING_MODEL_DIM", "1024"))
# ModelScope 上对应的模型 ID
_MODELSCOPE_MODEL_ID = os.environ.get(
    "MODELSCOPE_EMBEDDING_MODEL_ID",
    _LOCAL_MODEL_NAME,
)


def _is_offline_mode() -> bool:
    """Whether to force offline model loading."""
    flags = (
        os.environ.get("TRANSFORMERS_OFFLINE", ""),
        os.environ.get("HF_HUB_OFFLINE", ""),
    )
    return any(v.strip().lower() in {"1", "true", "yes"} for v in flags)

# ─── 客户端构建 ──────────────────────────────────────────

def _build_openai_client():
    """根据环境变量构建 OpenAI 兼容客户端"""
    from openai import OpenAI
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL")
    if not api_key:
        raise RuntimeError("环境变量 OPENAI_API_KEY 未设置")

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)

def _use_api() -> bool:
    """Use an embedding API only when production configuration explicitly selects it."""
    provider = os.environ.get("EMBEDDING_PROVIDER", "local").strip().lower()
    if provider not in {"local", "api"}:
        raise RuntimeError("EMBEDDING_PROVIDER must be 'local' or 'api'")
    return provider == "api"

def _download_via_modelscope() -> str:
    """通过 ModelScope 下载模型并返回本地路径"""
    from modelscope import snapshot_download

    print(f"正在通过 ModelScope 下载模型 {_MODELSCOPE_MODEL_ID}（首次约 95MB）...")
    model_dir = snapshot_download(_MODELSCOPE_MODEL_ID)
    print(f"模型已下载到: {model_dir}")
    return model_dir

@lru_cache(maxsize=1)
def _get_local_model():
    """
    懒加载本地 BGE 模型（只加载一次，后续调用命中缓存）。

    下载策略：先尝试 HuggingFace（或 hf-mirror 镜像），
    若不可达则走 ModelScope，模型文件缓存后下次秒加载。

    返回 sentence-transformers 模型实例。
    """
    from sentence_transformers import SentenceTransformer

    local_model_path = os.environ.get("LOCAL_EMBEDDING_MODEL_PATH", "").strip()
    configured_device = os.environ.get("LOCAL_EMBEDDING_DEVICE", "").strip()
    model_kwargs = {"device": configured_device} if configured_device else {}
    offline = _is_offline_mode()

    if local_model_path:
        if not os.path.exists(local_model_path):
            raise RuntimeError(f"LOCAL_EMBEDDING_MODEL_PATH 不存在: {local_model_path}")
        model = SentenceTransformer(local_model_path, local_files_only=True, **model_kwargs)
        dim = model.get_sentence_embedding_dimension()
        _validate_local_dimension(dim)
        print(f"本地模型已加载: {local_model_path}（{dim} 维）")
        return model

    # 先尝试直接加载（走 HF / HF_ENDPOINT 镜像）
    try:
        model = SentenceTransformer(_LOCAL_MODEL_NAME, local_files_only=offline, **model_kwargs)
    except Exception as e:
        if offline:
            raise RuntimeError(
                f"离线模式下未能从本地缓存加载模型 {_LOCAL_MODEL_NAME}，"
                "请设置 LOCAL_EMBEDDING_MODEL_PATH 到本地模型目录"
            ) from e
        print(f"HuggingFace 加载失败 ({e})，切换到 ModelScope 下载...")
        local_path = _download_via_modelscope()
        model = SentenceTransformer(local_path, **model_kwargs)

    dim = model.get_sentence_embedding_dimension()
    _validate_local_dimension(dim)
    print(f"本地模型已加载: {_LOCAL_MODEL_NAME}（{dim} 维）")
    return model

# ─── 公共接口 ────────────────────────────────────────────

def embed_texts(texts: list[str], model: str = "text-embedding-3-small") -> list[list[float]]:
    """
    批量文本向量化。

    默认使用本地 BGE-M3。仅当 EMBEDDING_PROVIDER=api 时使用兼容接口。

    Args:
        texts: 待向量化的文本列表
        model: 嵌入模型名称（仅 API 模式使用，本地模式忽略）

    Returns:
        向量列表；本地 BGE-M3 默认输出 1024 维归一化向量
    """
    if not texts:
        return []

    if _use_api():
        client = _build_openai_client()
        response = client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in response.data]
    else:
        local_model = _get_local_model()
        result = local_model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [vec.tolist() for vec in result]


def release_local_model() -> None:
    """Release this process's lazy local embedding model before a GPU handoff."""
    _get_local_model.cache_clear()
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _validate_local_dimension(actual: int) -> None:
    if int(actual) != _LOCAL_MODEL_DIM:
        raise RuntimeError(
            "local embedding dimension mismatch: "
            f"configured {_LOCAL_MODEL_DIM}, model returned {actual}"
        )



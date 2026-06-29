"""
文本向量化模块。

支持两种模式，自动选择：
1. OpenAI 兼容接口 — 当 OPENAI_API_KEY 已设置时使用
2. 本地 BGE 模型   — 无需外部服务，离线可用

本地模式优先通过 HuggingFace（或 HF_ENDPOINT 镜像）下载模型，
若失败则回退到 ModelScope 下载。模型缓存到本地，仅首次运行需联网。
"""

import os
from functools import lru_cache

from openai import OpenAI


# ─── 本地模型常量 ───────────────────────────────────────

_LOCAL_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
_LOCAL_MODEL_DIM = 512
# ModelScope 上对应的模型 ID
_MODELSCOPE_MODEL_ID = "BAAI/bge-small-zh-v1.5"


# ─── 客户端构建 ──────────────────────────────────────────

def _build_openai_client() -> OpenAI:
    """根据环境变量构建 OpenAI 兼容客户端"""
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL")
    if not api_key:
        raise RuntimeError("环境变量 OPENAI_API_KEY 未设置")

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _use_api() -> bool:
    """判断是否使用 API（有 Key 则用，无 Key 则走本地模型）"""
    return bool(os.environ.get("OPENAI_API_KEY"))


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

    # 先尝试直接加载（走 HF / HF_ENDPOINT 镜像）
    try:
        model = SentenceTransformer(_LOCAL_MODEL_NAME)
    except Exception as e:
        print(f"HuggingFace 加载失败 ({e})，切换到 ModelScope 下载...")
        local_path = _download_via_modelscope()
        model = SentenceTransformer(local_path)

    dim = model.get_sentence_embedding_dimension()
    print(f"本地模型已加载: {_LOCAL_MODEL_NAME}（{dim} 维）")
    return model


# ─── 公共接口 ────────────────────────────────────────────

def embed_texts(texts: list[str], model: str = "text-embedding-3-small") -> list[list[float]]:
    """
    批量文本向量化。

    当 OPENAI_API_KEY 已设置时使用 OpenAI 兼容接口；
    否则自动 fallback 到本地 BGE 模型（BAAI/bge-small-zh-v1.5, 512 维）。

    Args:
        texts: 待向量化的文本列表
        model: 嵌入模型名称（仅 API 模式使用，本地模式忽略）

    Returns:
        向量列表，API 模式 1536 维，本地模式 512 维
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


def embedding_dim() -> int:
    """返回当前使用的向量维度"""
    if _use_api():
        return 1536
    else:
        return _LOCAL_MODEL_DIM

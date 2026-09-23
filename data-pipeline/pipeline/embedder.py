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

def _is_model_dir_valid(path_str: str) -> bool:
    if not path_str or not os.path.isdir(path_str):
        return False
    has_config = os.path.exists(os.path.join(path_str, "config.json"))
    has_weights = (
        os.path.exists(os.path.join(path_str, "model.safetensors"))
        or os.path.exists(os.path.join(path_str, "pytorch_model.bin"))
        or os.path.exists(os.path.join(path_str, "modules.json"))
    )
    return has_config and has_weights


def _download_via_modelscope(target_dir: str | None = None) -> str:
    """Download model via ModelScope and return local path."""
    from modelscope import snapshot_download

    print(f"[ModelLoader] Downloading model {_MODELSCOPE_MODEL_ID} via ModelScope...")
    kwargs = {"model_id": _MODELSCOPE_MODEL_ID}
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)
        kwargs["local_dir"] = target_dir
    model_dir = snapshot_download(**kwargs)
    print(f"[ModelLoader] Model downloaded to: {model_dir}")
    return model_dir


@lru_cache(maxsize=1)
def _get_local_model():
    """
    Load local BGE model from LOCAL_EMBEDDING_MODEL_PATH.
    If missing or incomplete, automatically downloads weights.
    """
    from sentence_transformers import SentenceTransformer

    local_model_path = os.environ.get("LOCAL_EMBEDDING_MODEL_PATH", "").strip()
    if not local_model_path:
        workspace_model_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "data-persistence", "models", "bge-small-en-v1.5")
        )
        local_model_path = workspace_model_dir

    configured_device = os.environ.get("LOCAL_EMBEDDING_DEVICE", "").strip()
    model_kwargs = {"device": configured_device} if configured_device else {}

    if not _is_model_dir_valid(local_model_path):
        print(f"[ModelLoader] Local model weights missing at: {local_model_path}. Starting automatic download...")
        try:
            _download_via_modelscope(target_dir=local_model_path)
        except Exception as dl_err:
            print(f"[ModelLoader] ModelScope download failed ({dl_err}), trying HuggingFace Hub mirror...")
            try:
                if "HF_ENDPOINT" not in os.environ:
                    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
                from huggingface_hub import snapshot_download as hf_download
                hf_download(
                    repo_id=_LOCAL_MODEL_NAME,
                    local_dir=local_model_path,
                    local_dir_use_symlinks=False,
                    resume_download=True,
                )
            except Exception as hf_err:
                raise RuntimeError(
                    f"Failed to auto-download embedding model: {dl_err} / {hf_err}. Please place model weights in {local_model_path}"
                )

    model = SentenceTransformer(local_model_path, local_files_only=True, **model_kwargs)
    dim = getattr(model, "get_sentence_embedding_dimension", getattr(model, "get_embedding_dimension", lambda: 384))()
    _validate_local_dimension(dim)
    print(f"[ModelLoader] Local model loaded: {local_model_path} ({dim} dims)")
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



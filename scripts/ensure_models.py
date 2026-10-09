import os
import sys
import logging
from pathlib import Path

logger = logging.getLogger("model-loader")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DEFAULT_MODEL_ID = "BAAI/bge-small-en-v1.5"
MODELSCOPE_ID = "BAAI/bge-small-en-v1.5"

def is_model_directory_valid(model_path: str | Path) -> bool:
    """Check if the directory contains essential HuggingFace/SentenceTransformers model files."""
    path = Path(model_path)
    if not path.exists() or not path.is_dir():
        return False
    
    # Must have config.json and at least one weights file or tokenizer file
    has_config = (path / "config.json").exists()
    has_weights = (
        (path / "model.safetensors").exists()
        or (path / "pytorch_model.bin").exists()
        or (path / "modules.json").exists()
    )
    return has_config and has_weights

def download_embedding_model(target_dir: str | Path, model_id: str = DEFAULT_MODEL_ID) -> str:
    """
    Download the embedding model weights to target_dir.
    Tries ModelScope first (fast in China), then falls back to Hugging Face (with mirror support).
    """
    target_path = Path(target_dir).resolve()
    target_path.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Downloading embedding model '{model_id}' to: {target_path}")
    
    # Strategy 1: Try ModelScope (fastest for domestic networks)
    try:
        logger.info("Attempting download via ModelScope...")
        from modelscope import snapshot_download as ms_download
        downloaded_dir = ms_download(model_id=MODELSCOPE_ID, local_dir=str(target_path))
        if is_model_directory_valid(downloaded_dir):
            logger.info(f"ModelScope download successful: {downloaded_dir}")
            return str(downloaded_dir)
    except Exception as e:
        logger.warning(f"ModelScope download failed: {e}. Trying Hugging Face mirror fallback...")

    # Strategy 2: Try Hugging Face with hf-mirror.com endpoint
    try:
        logger.info("Attempting download via Hugging Face Hub (hf-mirror.com)...")
        if "HF_ENDPOINT" not in os.environ:
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        
        from huggingface_hub import snapshot_download as hf_download
        downloaded_dir = hf_download(
            repo_id=model_id,
            local_dir=str(target_path),
            local_dir_use_symlinks=False,
            resume_download=True,
        )
        if is_model_directory_valid(downloaded_dir):
            logger.info(f"Hugging Face download successful: {downloaded_dir}")
            return str(downloaded_dir)
    except Exception as e:
        logger.error(f"Hugging Face download failed: {e}")

    raise RuntimeError(
        f"Failed to download embedding model '{model_id}'. "
        "Please check your internet connection or manually place model weights in "
        f"{target_path}"
    )

def ensure_embedding_model(target_dir: str | Path | None = None) -> str:
    """
    Ensure the embedding model is available locally. If missing, automatically downloads it.
    Returns the absolute local path to the model.
    """
    if target_dir is None:
        target_dir = os.environ.get("LOCAL_EMBEDDING_MODEL_PATH")
    
    if not target_dir:
        # Default to data-persistence/models/bge-small-en-v1.5
        project_root = Path(__file__).resolve().parent.parent
        target_dir = project_root / "data-persistence" / "models" / "bge-small-en-v1.5"
    
    target_path = Path(target_dir).resolve()
    
    if is_model_directory_valid(target_path):
        logger.info(f"Embedding model already present and verified: {target_path}")
        return str(target_path)
    
    logger.info(f"Embedding model missing or incomplete at {target_path}. Starting automatic download...")
    return download_embedding_model(target_path)

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    res = ensure_embedding_model(path)
    print(f"MODEL_PATH={res}")

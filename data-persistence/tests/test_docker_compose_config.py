from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_minio_uses_available_official_quay_registry():
    compose = (ROOT / "data-persistence" / "docker-compose.yml").read_text(
        encoding="utf-8"
    )

    assert "image: quay.io/minio/minio:RELEASE.2023-03-20T20-16-18Z" in compose
    assert "image: minio/minio:" not in compose

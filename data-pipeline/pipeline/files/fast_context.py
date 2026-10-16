"""Prepare parsed excerpts and original images without any model invocation.

The Agent authorizes every requested file before entering this internal tool.
No HTTP self-call, raw path supplied by a caller, or generated OCR fallback.
"""

import base64
import hashlib
from io import BytesIO
from pathlib import Path

from data_persistence.file_crypto import decrypt_bytes


def fast_file_context(body, store, settings):
    items, images, seen = [], [], set()
    image_bytes = 0
    for attachment_id in body.attachment_ids:
        record = store.get_attachment(attachment_id)
        if not record or record["status"] not in {"ready", "needs_review"}:
            raise RuntimeError("attachment_not_ready")
        parsed = [item for item in store.list_evidence([attachment_id])
                  if item.get("source_type") != "vision_analysis"]
        # The selected files themselves are the scope; no query expansion or retry.
        for item in parsed[:body.top_k]:
            item = {**item, "filename": record["filename"], "score": 1.0}
            items.append(item)
        if not str(record.get("mime_type", "")).startswith("image/"):
            if not parsed:
                raise RuntimeError("attachment_parsed_context_unavailable")
            continue
        if attachment_id in seen:
            continue
        seen.add(attachment_id)
        if len(images) >= 8 or record["size_bytes"] + image_bytes > settings.max_image_bytes:
            raise RuntimeError("fast_image_budget_exceeded")
        raw = decrypt_bytes(Path(record["blob_path"]), settings.encryption_key,
                            f"{record['dedupe_domain']}:{record['sha256']}".encode())
        if hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise RuntimeError("attachment_hash_changed")
        from PIL import Image
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > settings.max_image_pixels:
                raise RuntimeError("fast_image_budget_exceeded")
            output = BytesIO()
            image.convert("RGB").save(output, format="PNG")
        content = output.getvalue()
        image_bytes += len(content)
        if image_bytes > settings.max_image_bytes:
            raise RuntimeError("fast_image_budget_exceeded")
        images.append({"attachment_id": attachment_id,
                       "image_url": "data:image/png;base64," + base64.b64encode(content).decode("ascii")})
        reference = "ev_" + hashlib.sha256(
            f"{attachment_id}:original:{record['evidence_version']}:{record['sha256']}".encode()).hexdigest()[:32]
        items.insert(0, {
            "attachment_id": attachment_id, "evidence_id": f"{attachment_id}:original",
            "filename": record["filename"], "content": "Original image: " + record["filename"],
            "score": 1.0, "content_kind": "file", "content_hash": record["sha256"],
            "source_content_hash": record["sha256"], "source_version": record["evidence_version"],
            "version": record["evidence_version"], "read_status": "original_image_loaded",
            "evidence_ref": reference, "locator": {"kind": "original_file"},
        })
    return {"items": items, "images": images}

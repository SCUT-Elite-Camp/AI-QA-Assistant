from __future__ import annotations

from pathlib import Path
from typing import Any


def prepare_vision_image(
    source: Path,
    extension: str,
    page: int | None,
    bbox: list[float] | None,
    output: Path,
) -> dict[str, Any]:
    """Render and optionally crop a vision input without service-global state."""
    locator: dict[str, Any] = {"page": page, "bbox": bbox}
    if bbox is not None:
        if (
            len(bbox) != 4
            or any(value < 0 or value > 1 for value in bbox)
            or bbox[0] >= bbox[2]
            or bbox[1] >= bbox[3]
        ):
            raise ValueError("invalid_bbox")
    if extension == ".pdf":
        import fitz

        document = fitz.open(source)
        try:
            page_number = page or 1
            if page_number > len(document):
                raise ValueError("page_out_of_range")
            pixmap = document[page_number - 1].get_pixmap(
                matrix=fitz.Matrix(2, 2), alpha=False,
            )
            pixmap.save(output)
            locator["page"] = page_number
        finally:
            document.close()
    else:
        if page not in {None, 1}:
            raise ValueError("page_out_of_range")
        from PIL import Image

        with Image.open(source) as image:
            image.convert("RGB").save(output, format="PNG")
        locator["page"] = None
    if bbox is not None:
        from PIL import Image

        with Image.open(output) as image:
            width, height = image.size
            crop = (
                round(bbox[0] * width), round(bbox[1] * height),
                round(bbox[2] * width), round(bbox[3] * height),
            )
            image.crop(crop).save(output, format="PNG")
    return locator

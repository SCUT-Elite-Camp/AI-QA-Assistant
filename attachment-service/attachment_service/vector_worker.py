from __future__ import annotations

import json
import sys

from .vector_index import AttachmentVectorIndex


def main() -> int:
    try:
        request = json.load(sys.stdin)
        AttachmentVectorIndex()._replace_in_process(
            str(request["attachment_id"]),
            list(request["items"]),
        )
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

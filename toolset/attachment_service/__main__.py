import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "attachment_service.app:app",
        host=os.getenv("ATTACHMENT_HOST", "127.0.0.1"),
        port=int(os.getenv("ATTACHMENT_PORT", "8200")),
        reload=False,
    )

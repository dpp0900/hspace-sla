from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("SLA_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("SLA_WEB_PORT", "8000"))
    uvicorn.run("sla_app.web.app:create_app", host=host, port=port, factory=True)


if __name__ == "__main__":
    main()

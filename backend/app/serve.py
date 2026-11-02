"""Serve the app on HTTPS. HTTP stays up so ZKTeco push can still reach /iclock."""

from __future__ import annotations

import asyncio
import logging
import os

import uvicorn

from app.config import http_port, https_port
from app.tls import ca_file, ensure_certs

log = logging.getLogger("espressolab")


async def _run() -> None:
    os.environ.setdefault("FORCE_HTTPS", "1")
    cert, key = ensure_certs()
    from app.main import app

    host = os.environ.get("HOST", "0.0.0.0")
    https = uvicorn.Server(
        uvicorn.Config(
            app,
            host=host,
            port=https_port(),
            ssl_certfile=str(cert),
            ssl_keyfile=str(key),
            proxy_headers=True,
            forwarded_allow_ips="*",
            log_level="info",
        )
    )
    http = uvicorn.Server(
        uvicorn.Config(
            app,
            host=host,
            port=http_port(),
            proxy_headers=True,
            forwarded_allow_ips="*",
            log_level="info",
            lifespan="off",
        )
    )

    async def serve_http() -> None:
        while not https.started:
            await asyncio.sleep(0.05)
        log.info("Open https://127.0.0.1:%s — trust %s in the OS certificate store to skip the browser warning", https_port(), ca_file())
        await http.serve()

    await asyncio.gather(https.serve(), serve_http())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()

"""Production-like static server for the built SmartDesk React application."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse


def default_dist_dir() -> Path:
    configured = os.environ.get("SMARTDESK_FRONTEND_DIST", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parent / "frontend" / "dist").resolve()


def create_app(dist_dir: Path | None = None) -> FastAPI:
    root = (dist_dir or default_dist_dir()).resolve()
    application = FastAPI(
        title="SmartDesk Frontend",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.get("/health")
    def health():
        index = root / "index.html"
        status = "ok" if index.is_file() else "not_ready"
        code = 200 if index.is_file() else 503
        return JSONResponse(
            {"status": status, "dist": index.is_file()},
            status_code=code,
        )

    @application.get("/{requested_path:path}")
    def serve_spa(requested_path: str):
        index = root / "index.html"
        if not index.is_file():
            raise HTTPException(
                status_code=503,
                detail="Frontend build is missing. Run npm run build.",
            )

        candidate = (root / requested_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise HTTPException(status_code=404) from error
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)

    return application


app = create_app()


__all__ = ["app", "create_app", "default_dist_dir"]

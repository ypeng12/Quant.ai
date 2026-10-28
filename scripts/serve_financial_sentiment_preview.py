#!/usr/bin/env python3
"""Serve the built Quant.ai research UI with read-only local report routes.

Never imports main_api, configuration, collectors, brokerage, or trading runner.
All mutation requests are rejected. Browser connections are restricted to this
origin so a frontend build cannot accidentally contact a production API.
"""
import argparse
from pathlib import Path
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.financial_sentiment_comparison import router as comparison_router
from app.financial_sentiment_research import router as research_router
from app.financial_sentiment_context import router as context_router
from app.financial_sentiment_signals import router as signals_router


def create_app():
    app = FastAPI(title="Read-only Quant.ai research preview")

    @app.middleware("http")
    async def read_only(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            response = JSONResponse({"detail": "This research preview is read-only."}, status_code=405)
        else:
            response = await call_next(request)
        response.headers["Content-Security-Policy"] = "connect-src 'self'; frame-src 'none'; object-src 'none'"
        return response

    app.include_router(comparison_router)
    app.include_router(research_router)
    app.include_router(context_router)
    app.include_router(signals_router)
    dist = ROOT / "frontend/dist"
    if not (dist / "index.html").is_file():
        raise RuntimeError("Build the existing frontend first")
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def index(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Only saved research reports are available in this preview.")
        return FileResponse(dist / "index.html")
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8138)
    args = parser.parse_args()
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="warning")

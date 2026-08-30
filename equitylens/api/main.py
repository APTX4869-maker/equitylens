"""FastAPI application entrypoint.

Run:  uv run uvicorn equitylens.api.main:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from equitylens.api.routes import router

app = FastAPI(
    title="EquityLens API",
    version="0.1.0",
    description="Local-first US equity research API. Facts from SEC, "
                "calculations from deterministic code, opinions from evidence.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root():
    return {"service": "EquityLens API", "docs": "/docs", "api": "/api/v1"}

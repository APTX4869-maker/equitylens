"""FastAPI application entrypoint.

Run:  uv run uvicorn equitylens.api.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from equitylens.api.company_routes import router as company_router
from equitylens.api.routes import router


def _warm_risk_free() -> None:
    """Pre-warm the risk-free-rate cache so the first valuation call is fast."""
    try:
        from equitylens.valuation.rates import risk_free_rate

        risk_free_rate()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    from equitylens.api import routes as routes_module
    from equitylens.onboarding.repository import OnboardingRepository
    from equitylens.onboarding.pipeline import OnboardingPipeline
    from equitylens.onboarding.runner import OnboardingExecutor, OnboardingRunner
    from equitylens.storage.writer import writer_for

    store = routes_module._store()
    writer = writer_for(store)
    writer.start()
    repository = OnboardingRepository(store)
    pipeline = OnboardingPipeline(store, repository)
    executor = OnboardingExecutor(
        OnboardingRunner(store, repository, handlers=pipeline.handlers())
    )
    executor.start()
    app.state.onboarding_executor = executor
    threading.Thread(target=_warm_risk_free, daemon=True).start()
    try:
        yield
    finally:
        executor.close()
        pipeline.close()
        writer.close()


app = FastAPI(
    title="EquityLens API",
    version="0.1.0",
    description="Local-first US equity research API. Facts from SEC, "
                "calculations from deterministic code, opinions from evidence.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(company_router)
app.include_router(router)


@app.get("/")
def root():
    return {"service": "EquityLens API", "docs": "/docs", "api": "/api/v1"}

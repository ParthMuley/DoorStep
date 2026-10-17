"""FastAPI app factory. Run: uvicorn doorstep.api.app:app (with PYTHONPATH=src)."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from doorstep.services.db import Database
from doorstep.services.engine import DoorstepService
from doorstep.services.errors import DomainError

from .routes import router

log = logging.getLogger("doorstep.api")


def create_app(db_path: str | None = None, seed: bool | None = None) -> FastAPI:
    if os.environ.get("SIMULATION_MODE", "true").lower() != "true":
        raise RuntimeError("Doorstep backend only runs with SIMULATION_MODE=true")
    app = FastAPI(title="Doorstep backend (SIMULATION)", version="0.1.0",
                  description="Synthetic-data simulation. Not an emergency service.")
    service = DoorstepService(Database(db_path))
    should_seed = seed if seed is not None else not service.store.list_residents()
    if should_seed:
        service.reset()
    app.state.service = service

    @app.exception_handler(DomainError)
    def domain_error(_: Request, exc: DomainError):
        # Log the error class and code only -- no resident details.
        log.info("domain_error code=%s status=%s", exc.code, exc.status_code)
        return JSONResponse(status_code=exc.status_code,
                            content={"error": exc.code, "message": exc.message, "reasons": exc.reasons})

    @app.exception_handler(ValueError)
    def value_error(_: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"error": "invalid_value", "message": str(exc), "reasons": []})

    app.include_router(router)
    return app


def __getattr__(name: str):
    # Lazy module-level ``app`` so importing this module in tests has no side effects.
    if name == "app":
        global app
        app = create_app()
        return app
    raise AttributeError(name)

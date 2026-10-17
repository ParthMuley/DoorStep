"""FastAPI app factory. Run: uvicorn doorstep.api.app:app (with PYTHONPATH=src)."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from doorstep.models import SCHEMA_VERSION
from doorstep.services.db import Database
from doorstep.services.engine import DoorstepService
from doorstep.services.errors import DomainError

from .routes import router

log = logging.getLogger("doorstep.api")

try:  # python-dotenv is in A's pyproject; optional for local runs
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def _error(request: Request, status: int, code: str, detail: str, reasons: list[str] | None = None) -> JSONResponse:
    corr = request.headers.get("X-Correlation-ID")
    body = {"schema_version": SCHEMA_VERSION, "error": code, "detail": detail, "correlation_id": corr}
    if reasons:
        body["reasons"] = reasons
    return JSONResponse(status_code=status, content=body)


def create_app(db_path: str | None = None, seed: bool | None = None) -> FastAPI:
    if os.environ.get("SIMULATION_MODE", "true").lower() != "true":
        raise RuntimeError("Doorstep backend only runs with SIMULATION_MODE=true")
    app = FastAPI(title="Doorstep backend (SIMULATION)", version="0.2.0",
                  description="Synthetic-data simulation. Not an emergency service. Contract v1.0.")
    service = DoorstepService(Database(db_path))
    should_seed = seed if seed is not None else not service.store.list_residents()
    if should_seed:
        service.reset()
    app.state.service = service

    @app.middleware("http")
    async def echo_correlation(request: Request, call_next):
        response = await call_next(request)
        corr = request.headers.get("X-Correlation-ID")
        if corr:
            response.headers["X-Correlation-ID"] = corr
        return response

    @app.exception_handler(DomainError)
    def domain_error(request: Request, exc: DomainError):
        # Log the error class and code only -- no resident details.
        log.info("domain_error code=%s status=%s", exc.code, exc.status_code)
        return _error(request, exc.status_code, exc.code, exc.message, exc.reasons)

    @app.exception_handler(StarletteHTTPException)
    def http_error(request: Request, exc: StarletteHTTPException):
        code = {401: "UNAUTHORIZED", 403: "UNAUTHORIZED", 404: "NOT_FOUND"}.get(exc.status_code, "HTTP_ERROR")
        return _error(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    def validation_error(request: Request, exc: RequestValidationError):
        fields = [".".join(str(p) for p in e.get("loc", [])) for e in exc.errors()]
        return _error(request, 422, "VALIDATION_ERROR", "Request body failed validation", fields)

    @app.exception_handler(ValueError)
    def value_error(request: Request, exc: ValueError):
        return _error(request, 422, "VALIDATION_ERROR", str(exc))

    app.include_router(router)
    return app


def __getattr__(name: str):
    # Lazy module-level ``app`` so importing this module in tests has no side effects.
    if name == "app":
        global app
        app = create_app()
        return app
    raise AttributeError(name)

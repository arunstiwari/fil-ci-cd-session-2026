"""FastAPI application exposing a health check and two calculator endpoints."""

from fastapi import FastAPI, HTTPException

from app import __version__
from app.calculator import add, divide

app = FastAPI(title="python-app", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the container and the CI smoke test."""
    return {"status": "ok", "version": __version__}


@app.get("/add")
def add_endpoint(a: float, b: float) -> dict[str, float]:
    """Add two numbers supplied as query parameters."""
    return {"result": add(a, b)}


@app.get("/divide")
def divide_endpoint(a: float, b: float) -> dict[str, float]:
    """Divide a by b, returning 400 when b is zero."""
    try:
        return {"result": divide(a, b)}
    except ZeroDivisionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

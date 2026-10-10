from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import get_settings
from .database.connection import Base, engine, get_db, initialize_database
from . import models  # Register all table metadata before creating the schema.
from .routers import admin, auth, incidents, teams, users, workspaces


settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield
    engine.dispose()


app = FastAPI(
    title="ResQ Kerala — Week 1", version=settings.app_version,
    description="Week 1 accounts, citizen reports, admin review and manual response-team assignment.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.allowed_origins,
    allow_credentials=False, allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def response_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(SQLAlchemyError)
async def database_error(_request: Request, _error: SQLAlchemyError):
    # Connection strings and driver diagnostics can contain credentials.
    return JSONResponse(status_code=503, content={"detail": "The database is temporarily unavailable. Please try again."})


@app.get("/health", tags=["System"])
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={
            "status": "unhealthy", "version": settings.app_version, "database": "unavailable",
        })
    return {"status": "ok", "version": settings.app_version, "database": "connected"}


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(workspaces.router)
app.include_router(incidents.router)
app.include_router(admin.router)
app.include_router(teams.router)


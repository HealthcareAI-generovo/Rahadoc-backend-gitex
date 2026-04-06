"""
FastAPI backend for RahaDoc AI features.
Handles MedScribe, Clinical Copilot, Rx Guard, Patient 360, and Smart Alerts.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import time
import logging

from app.api.v1.router import api_router
from app.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """
    Application lifespan manager.

    On startup:  auto-start simulation engine if SIMULATION_MODE=True.
    On shutdown: cleanly stop the simulation background loop.
    """
    if settings.SIMULATION_MODE:
        logger.info("[SIM] SIMULATION_MODE=True — starting simulation engine on startup.")
        from app.epidemiology.simulation import start_simulation
        await start_simulation()

    yield

    # Shutdown — stop simulation loop if running
    from app.epidemiology.simulation import get_simulation_state, stop_simulation
    if get_simulation_state().running:
        logger.info("[SIM] Shutting down simulation engine...")
        await stop_simulation()


app = FastAPI(
    title="RahaDoc AI Backend",
    description="AI-powered medical assistant features for RahaDoc",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# CORS middleware (allow Next.js frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000  # ms
    response.headers["X-Process-Time"] = str(process_time)
    return response

# Exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": str(type(exc).__name__)}
    )

# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint for Railway."""
    return {
        "status": "healthy",
        "service": "rahadoc-ai-backend",
        "version": "1.0.0"
    }

# Mount API router
app.include_router(api_router, prefix="/api/v1")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )

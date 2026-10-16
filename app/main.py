from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import logging
from contextlib import asynccontextmanager

from .deps import init_deps, close_deps, get_db, get_scanner_service
from .api import api_router
from .api.auth import router as auth_router
from .pages.home import router as pages_router
from .legado.source import router as legado_router
from .middleware import ErrorHandlerMiddleware, RequestLoggingMiddleware

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def background_scanner():
    """Background scanner that respects live config changes.

    Checks auto_scan and book_dirs before each scan cycle.
    If auto_scan is disabled or book_dirs is empty, sleeps without scanning.
    Re-reads config every cycle, so UI changes take effect immediately.
    """
    while True:
        try:
            db = await get_db()
            auto_scan = await db.config.get("auto_scan", "true")
            should_scan = auto_scan if isinstance(auto_scan, bool) else str(auto_scan).lower() == "true"

            if should_scan:
                book_dirs = await db.config.get("book_dirs", ["/books"])
                if book_dirs:
                    scanner = get_scanner_service()
                    await scanner.scan_all()
        except Exception as e:
            logger.error(f"Background scan error: {e}", exc_info=True)

        # Wait 60s before next check — config changes take effect within 60s
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_deps()

    task = asyncio.create_task(background_scanner())
    task.add_done_callback(lambda t: t.exception() and logger.error("Scan task failed", exc_info=t.exception()))

    yield
    await close_deps()


app = FastAPI(
    title="Legado Local Server",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan
)

# ── Middleware (order matters: first added = outermost) ──
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(ErrorHandlerMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8086", "http://127.0.0.1:8086"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router)
app.include_router(pages_router)
app.include_router(api_router, prefix="/api")
app.include_router(legado_router)


@app.get("/health")
async def health():
    return {"status": "ok"}

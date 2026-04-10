from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ai_scraper_bot.config import load_settings
from ai_scraper_bot.parsers.file_parser import SUPPORTED_FILE_TYPES
from ai_scraper_bot.utils.runtime_diary import install_runtime_diary_handler
from ai_scraper_bot.web.service import WebChatService
from ai_scraper_bot.web.store import WebChatStore


LOGGER = logging.getLogger(__name__)
PACKAGE_ROOT = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_ROOT / "web" / "static"
WEBAPP_DB_PATH = Path(os.getenv("WEBAPP_DB_PATH", "./.webapp/webapp.sqlite")).resolve()

install_runtime_diary_handler()
SETTINGS = load_settings()
STORE = WebChatStore(WEBAPP_DB_PATH)
SERVICE = WebChatService(SETTINGS, STORE)


class RenameChatPayload(BaseModel):
    title: str


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    await SERVICE.startup()
    LOGGER.info("Web app is ready.")
    yield


app = FastAPI(title="AI Website Scraper + Summarizer", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, object]:
    return {
        "ok": True,
        "minimax_configured": bool(SETTINGS.minimax_api_key and SETTINGS.minimax_api_url),
        "downloads_dir": str(SETTINGS.downloads_dir),
    }


@app.get("/api/bootstrap")
async def bootstrap() -> dict[str, object]:
    chats = await SERVICE.list_chats()
    return {
        "chats": chats,
        "active_jobs": await SERVICE.list_active_jobs(),
        "max_chats": 10,
        "supported_file_types": sorted(SUPPORTED_FILE_TYPES),
        "max_file_size_mb": SETTINGS.max_file_size_mb,
    }


@app.post("/api/chats")
async def create_chat() -> dict[str, object]:
    try:
        return {"chat": await SERVICE.create_chat()}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/chats/{chat_id}")
async def rename_chat(chat_id: int, payload: RenameChatPayload) -> dict[str, object]:
    try:
        return {"chat": await SERVICE.rename_chat(chat_id, payload.title)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/chats/{chat_id}/clear")
async def clear_chat(chat_id: int) -> dict[str, object]:
    try:
        return {"chat": await SERVICE.clear_chat(chat_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/chats/clear-all")
async def clear_all_chats() -> dict[str, object]:
    await SERVICE.clear_all_chats()
    return {"ok": True}


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: int) -> dict[str, object]:
    try:
        await SERVICE.delete_chat(chat_id)
        return {"ok": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/chats/{chat_id}")
async def get_chat(chat_id: int) -> dict[str, object]:
    try:
        return await SERVICE.get_chat_bundle(chat_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/chats/{chat_id}/messages")
async def post_message(
    chat_id: int,
    text: str = Form(default=""),
    file: UploadFile | None = File(default=None),
) -> dict[str, object]:
    try:
        return await SERVICE.start_message(chat_id=chat_id, text=text, uploaded_file=file)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, object]:
    try:
        return {"job": await SERVICE.get_job(job_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, object]:
    try:
        return {"job": await SERVICE.cancel_job(job_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def main() -> None:
    import uvicorn

    host = os.getenv("WEBAPP_HOST", "127.0.0.1")
    port = int(os.getenv("WEBAPP_PORT", "8000"))
    uvicorn.run(
        "ai_scraper_bot.webapp:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()

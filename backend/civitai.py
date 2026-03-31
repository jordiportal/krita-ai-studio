"""
CivitAI integration: search, download, and manage models.
"""

import asyncio
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api")

DB_PATH: Path = Path()
MODELS_DIR: Path = Path()

CIVITAI_API = "https://civitai.com/api/v1"

TYPE_DIRS = {
    "Checkpoint": "checkpoints",
    "LORA": "loras",
    "LoCon": "loras",
    "Controlnet": "controlnet",
    "VAE": "vae",
    "TextualInversion": "embeddings",
    "Hypernetwork": "hypernetworks",
    "Upscaler": "upscale_models",
}


def configure(db_path: Path, models_dir: Path):
    global DB_PATH, MODELS_DIR
    DB_PATH = db_path
    MODELS_DIR = models_dir
    for d in set(TYPE_DIRS.values()):
        (models_dir / d).mkdir(parents=True, exist_ok=True)
    (models_dir / "other").mkdir(parents=True, exist_ok=True)


def _get_civitai_key() -> str:
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT value FROM config WHERE key = 'civitai_api_key'"
    ).fetchone()
    conn.close()
    return row[0] if row else ""


def _get_nsfw_level() -> int:
    """Bitmask: 1=PG, 2=PG-13, 4=R, 8=X, 16=XXX.
    Default 31 (all enabled, like CivitAI). Value 0 = no filter."""
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT value FROM config WHERE key = 'civitai_nsfw_level'"
    ).fetchone()
    conn.close()
    if row and row[0]:
        try:
            return int(row[0])
        except ValueError:
            pass
    return 31


def _apply_content_filter(items: list, allowed: int) -> list:
    """Filter images within each model by nsfwLevel, like CivitAI does.
    Models are shown if they have at least one image matching the allowed
    levels. Images that don't match are removed from the response."""
    if allowed <= 0:
        return items

    filtered = []
    for model in items:
        versions = model.get("modelVersions") or []
        has_visible_image = False
        for version in versions:
            images = version.get("images") or []
            visible = [
                img for img in images
                if (img.get("nsfwLevel", 1) & allowed)
            ]
            version["images"] = visible
            if visible:
                has_visible_image = True
        if has_visible_image:
            filtered.append(model)
    return filtered


def _civitai_headers() -> dict:
    key = _get_civitai_key()
    h: dict = {}
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


# ─── In-memory download tracker ─────────────────────────────────────────────

_active_downloads: Dict[str, Dict[str, Any]] = {}


# ─── DB helpers for model_cache ──────────────────────────────────────────────

def _db_insert_cache(entry: dict):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "INSERT OR REPLACE INTO model_cache "
        "(id, civitai_model_id, civitai_version_id, name, type, filename, "
        " size_bytes, downloaded_at, status, progress, download_url, metadata) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            entry["id"], entry.get("civitai_model_id", 0),
            entry.get("civitai_version_id", 0), entry["name"], entry["type"],
            entry["filename"], entry.get("size_bytes", 0),
            entry.get("downloaded_at", time.time()),
            entry.get("status", "downloading"), entry.get("progress", 0),
            entry.get("download_url", ""), entry.get("metadata", "{}"),
        ),
    )
    conn.commit()
    conn.close()


def _db_update_cache(cache_id: str, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [cache_id]
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(f"UPDATE model_cache SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()


def _db_list_cache() -> List[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM model_cache ORDER BY downloaded_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _db_get_cache(cache_id: str) -> Optional[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM model_cache WHERE id = ?", (cache_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _db_delete_cache(cache_id: str) -> Optional[dict]:
    entry = _db_get_cache(cache_id)
    if not entry:
        return None
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM model_cache WHERE id = ?", (cache_id,))
    conn.commit()
    conn.close()
    return entry


# ─── Background download task ────────────────────────────────────────────────

async def _download_task(
    download_id: str, url: str, save_path: Path,
    civitai_key: str, total_hint: int = 0,
):
    _active_downloads[download_id] = {
        "status": "downloading", "progress": 0,
        "downloaded": 0, "total": total_hint, "speed": 0,
    }
    downloaded = 0

    try:
        headers: dict = {}
        if civitai_key:
            headers["Authorization"] = f"Bearer {civitai_key}"

        timeout = httpx.Timeout(600.0, connect=30.0)
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=timeout
        ) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code != 200:
                    raise Exception(f"HTTP {resp.status_code}")

                total = int(resp.headers.get("content-length", 0)) or total_hint
                t0 = time.time()

                save_path.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        elapsed = max(time.time() - t0, 0.01)
                        _active_downloads[download_id].update({
                            "progress": round(downloaded / total * 100, 1) if total else 0,
                            "downloaded": downloaded,
                            "total": total,
                            "speed": round(downloaded / elapsed),
                        })

        _active_downloads[download_id].update(
            {"status": "completed", "progress": 100}
        )
        _db_update_cache(
            download_id, status="completed", progress=100, size_bytes=downloaded
        )
        print(f"Download completed: {save_path.name} ({downloaded} bytes)")

    except Exception as e:
        _active_downloads[download_id].update(
            {"status": "error", "error": str(e)}
        )
        _db_update_cache(download_id, status="error")
        if save_path.exists():
            save_path.unlink()
        print(f"Download error {download_id}: {e}")


# ─── Schemas ─────────────────────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    civitai_model_id: int
    civitai_version_id: int
    download_url: str
    name: str
    type: str = "Checkpoint"
    filename: str = ""
    size_bytes: int = 0
    metadata: str = "{}"


# ─── CivitAI Proxy Endpoints ────────────────────────────────────────────────

@router.get("/civitai/search")
async def civitai_search(
    query: str = "",
    types: str = "",
    sort: str = "Most Downloaded",
    period: str = "AllTime",
    page: int = 1,
    limit: int = 20,
    nsfw: bool = False,
    cursor: str = "",
):
    nsfw_level = _get_nsfw_level()
    has_mature = nsfw_level & 0b11100  # R(4), X(8), or XXX(16)

    params: Dict[str, Any] = {
        "limit": min(limit, 100),
        "sort": sort,
        "period": period,
    }
    if query:
        params["query"] = query
    if types:
        params["types"] = types
    if has_mature:
        params["nsfw"] = "true"
    if cursor:
        params["cursor"] = cursor
    elif not query:
        params["page"] = page

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{CIVITAI_API}/models",
                params=params,
                headers=_civitai_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                if nsfw_level > 0:
                    data["items"] = _apply_content_filter(
                        data.get("items", []), nsfw_level
                    )
                return data
            return {
                "items": [], "metadata": {},
                "error": f"CivitAI HTTP {resp.status_code}",
            }
    except Exception as e:
        return {"items": [], "metadata": {}, "error": str(e)}


@router.get("/civitai/models/{model_id}")
async def civitai_model_detail(model_id: int):
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{CIVITAI_API}/models/{model_id}",
                headers=_civitai_headers(),
            )
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(
                status_code=resp.status_code, detail="CivitAI error"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ─── Download Endpoints ──────────────────────────────────────────────────────

@router.post("/civitai/download")
async def start_download(req: DownloadRequest):
    download_id = uuid.uuid4().hex[:12]
    subdir = TYPE_DIRS.get(req.type, "other")
    filename = req.filename or f"{req.name.replace(' ', '_')}.safetensors"
    save_path = MODELS_DIR / subdir / filename

    entry = {
        "id": download_id,
        "civitai_model_id": req.civitai_model_id,
        "civitai_version_id": req.civitai_version_id,
        "name": req.name,
        "type": req.type,
        "filename": filename,
        "size_bytes": req.size_bytes,
        "downloaded_at": time.time(),
        "status": "downloading",
        "progress": 0,
        "download_url": req.download_url,
        "metadata": req.metadata,
    }
    _db_insert_cache(entry)

    civitai_key = _get_civitai_key()
    asyncio.create_task(
        _download_task(
            download_id, req.download_url, save_path,
            civitai_key, req.size_bytes,
        )
    )

    return {"download_id": download_id, "status": "started"}


@router.get("/civitai/downloads")
async def get_downloads():
    items = _db_list_cache()
    for item in items:
        live = _active_downloads.get(item["id"])
        if live:
            item["progress"] = live.get("progress", item.get("progress", 0))
            item["status"] = live.get("status", item.get("status"))
            item["speed"] = live.get("speed", 0)
            item["downloaded"] = live.get("downloaded", 0)
    return {"items": items}


# ─── Cache Endpoints ─────────────────────────────────────────────────────────

@router.get("/cache")
async def list_cache():
    items = _db_list_cache()
    for item in items:
        live = _active_downloads.get(item["id"])
        if live:
            item["progress"] = live.get("progress", item.get("progress", 0))
            item["status"] = live.get("status", item.get("status"))
            item["speed"] = live.get("speed", 0)
    return {"items": items}


@router.delete("/cache/{cache_id}")
async def delete_cached_model(cache_id: str):
    entry = _db_delete_cache(cache_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Not found")

    subdir = TYPE_DIRS.get(entry["type"], "other")
    filepath = MODELS_DIR / subdir / entry["filename"]
    if filepath.exists():
        filepath.unlink()

    _active_downloads.pop(cache_id, None)
    return {"status": "ok"}

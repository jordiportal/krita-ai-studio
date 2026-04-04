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
COMFYUI_URL: str = ""


def get_comfyui_url() -> str:
    """Obtiene la URL de ComfyUI desde la configuracion."""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.execute("SELECT key, value FROM config WHERE key IN ('comfyui_host', 'comfyui_port', 'comfyui_secure')")
    cfg = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()

    host = cfg.get("comfyui_host", "localhost")
    port = cfg.get("comfyui_port", "8188")
    secure = cfg.get("comfyui_secure", "false").lower() == "true"
    return f"{'https' if secure else 'http'}://{host}:{port}"

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


_NSFW_LABEL_MAP = {
    "None": 1, "PG": 1, "Soft": 2, "PG-13": 2,
    "Mature": 4, "R": 4, "X": 8, "XXX": 16,
}


def _parse_nsfw_level(raw) -> int:
    """Parse nsfwLevel from CivitAI (int bitmask, string label, or absent)."""
    if raw is None:
        return 1
    if isinstance(raw, int):
        return raw
    label = str(raw).strip()
    if label in _NSFW_LABEL_MAP:
        return _NSFW_LABEL_MAP[label]
    try:
        return int(label)
    except (ValueError, TypeError):
        return 1


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
                if (_parse_nsfw_level(img.get("nsfwLevel")) & allowed)
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

async def _poll_plugin_download(
    cache_id: str,
    plugin_download_id: str,
    comfy_url: str,
):
    """Polling del progreso de descarga en el plugin ComfyUI."""
    try:
        async with httpx.AsyncClient() as client:
            while True:
                await asyncio.sleep(2)

                try:
                    resp = await client.get(
                        f"{comfy_url}/api/kas/downloads/{plugin_download_id}",
                        timeout=10.0,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        download = data.get("download", {})

                        status = download.get("status", "downloading")
                        progress = download.get("progress", 0)

                        _db_update_cache(cache_id, status=status, progress=progress)

                        if status in ["completed", "error", "cancelled"]:
                            break

                except Exception:
                    pass

    except Exception as e:
        print(f"[civitai] Error en polling de descarga: {e}")
        _db_update_cache(cache_id, status="error", error=str(e))


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


@router.get("/civitai/version-images/{version_id}")
async def civitai_version_images(version_id: int, limit: int = 20):
    """Fetch images with full generation metadata for a model version."""
    return await _fetch_civitai_images(modelVersionId=version_id, limit=limit)


@router.get("/civitai/images")
async def civitai_browse_images(
    sort: str = "Most Reactions",
    period: str = "Week",
    page: int = 0,
    cursor: str = "",
    limit: int = 20,
    modelId: int = 0,
    username: str = "",
):
    """Browse CivitAI images feed with filters."""
    return await _fetch_civitai_images(
        sort=sort, period=period, page=page, cursor=cursor,
        limit=limit, modelId=modelId or None, username=username or None,
    )


async def _fetch_civitai_images(
    *,
    modelVersionId: int = 0,
    modelId: Optional[int] = None,
    username: Optional[str] = None,
    sort: str = "",
    period: str = "",
    page: int = 0,
    cursor: str = "",
    limit: int = 20,
) -> dict:
    """Shared helper to query CivitAI /api/v1/images with content filtering."""
    nsfw_level = _get_nsfw_level()
    has_mature = nsfw_level & 0b11100

    params: Dict[str, Any] = {"limit": min(limit, 100)}
    if modelVersionId:
        params["modelVersionId"] = modelVersionId
    if modelId:
        params["modelId"] = modelId
    if username:
        params["username"] = username
    if sort:
        params["sort"] = sort
    if period:
        params["period"] = period
    if has_mature:
        params["nsfw"] = "true"
    if cursor:
        params["cursor"] = cursor
    elif page > 0:
        params["page"] = page

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{CIVITAI_API}/images",
                params=params,
                headers=_civitai_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                if nsfw_level > 0:
                    items = [
                        img for img in items
                        if (_parse_nsfw_level(img.get("nsfwLevel")) & nsfw_level)
                    ]
                metadata = data.get("metadata", {})
                return {"items": items, "metadata": metadata}
            return {
                "items": [], "metadata": {},
                "error": f"CivitAI HTTP {resp.status_code}",
            }
    except Exception as e:
        return {"items": [], "metadata": {}, "error": str(e)}


# ─── Download Endpoints ──────────────────────────────────────────────────────

@router.post("/civitai/download")
async def start_download(req: DownloadRequest):
    """
    Inicia descarga de modelo desde CivitAI.
    Con el plugin comfyui-kas, redirige la descarga al servidor ComfyUI.
    """
    download_id = uuid.uuid4().hex[:12]
    filename = req.filename or f"{req.name.replace(' ', '_')}.safetensors"

    # Guardar registro en SQLite (metadatos, historial)
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

    # Intentar usar el plugin comfyui-kas para descargar directamente en ComfyUI
    comfy_url = get_comfyui_url()
    civitai_key = _get_civitai_key()

    try:
        # Llamar al endpoint del plugin para iniciar descarga
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "download_url": req.download_url,
                "filename": filename,
                "type": req.type,
                "civitai_model_id": req.civitai_model_id,
                "civitai_version_id": req.civitai_version_id,
                "api_key": civitai_key if civitai_key else None,
            }
            headers = {}
            if civitai_key:
                headers["X-Civitai-Api-Key"] = civitai_key

            resp = await client.post(
                f"{comfy_url}/api/kas/models/download",
                json=payload,
                headers=headers,
            )

            if resp.status_code == 200:
                result = resp.json()
                if result.get("status") == "ok":
                    # El plugin acepto la descarga
                    plugin_download_id = result.get("download", {}).get("id", download_id)
                    _db_update_cache(download_id, status="downloading", progress=0)

                    # Iniciar tarea de polling del progreso
                    asyncio.create_task(
                        _poll_plugin_download(download_id, plugin_download_id, comfy_url)
                    )

                    return {"download_id": download_id, "status": "started", "via_plugin": True}

    except Exception as e:
        print(f"[civitai] Plugin no disponible ({e}), usando descarga local fallback")

    # Fallback: descarga local (comportamiento anterior)
    subdir = TYPE_DIRS.get(req.type, "other")
    save_path = MODELS_DIR / subdir / filename

    civitai_key = _get_civitai_key()
    asyncio.create_task(
        _download_task(
            download_id, req.download_url, save_path,
            civitai_key, req.size_bytes,
        )
    )

    return {"download_id": download_id, "status": "started", "via_plugin": False}


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

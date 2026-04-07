"""
Krita AI Studio Backend - FastAPI
Replica EXACTAMENTE el comportamiento de krita-ai-diffusion
Usa ETN_SaveImageCache (no PreviewImage) + /api/etn/image/{id}
SQLite para persistir configuración del usuario, conexión ComfyUI y galería
JWT auth con pantalla de login
"""

import os
import base64
import hashlib
import random
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
import httpx
import jwt

from workflow_krita import create_txt2img_workflow_krita, create_txt2video_workflow, parse_lora_tags, resolve_lora_filename
from civitai import router as civitai_router, configure as configure_civitai

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
DB_PATH = DATA_DIR / "krita_ai.db"
GALLERY_DIR = DATA_DIR / "gallery"
MODELS_DIR = DATA_DIR / "models"


# ─── SQLite helpers ───────────────────────────────────────────────────────────

def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    GALLERY_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))

    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_cache (
            id                  TEXT PRIMARY KEY,
            civitai_model_id    INTEGER NOT NULL DEFAULT 0,
            civitai_version_id  INTEGER NOT NULL DEFAULT 0,
            name                TEXT NOT NULL DEFAULT '',
            type                TEXT NOT NULL DEFAULT 'Checkpoint',
            filename            TEXT NOT NULL DEFAULT '',
            size_bytes          INTEGER NOT NULL DEFAULT 0,
            downloaded_at       REAL NOT NULL DEFAULT 0,
            status              TEXT NOT NULL DEFAULT 'downloading',
            progress            REAL NOT NULL DEFAULT 0,
            download_url        TEXT NOT NULL DEFAULT '',
            metadata            TEXT NOT NULL DEFAULT '{}'
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS gallery (
            id         TEXT PRIMARY KEY,
            prompt     TEXT NOT NULL DEFAULT '',
            neg_prompt TEXT NOT NULL DEFAULT '',
            checkpoint TEXT NOT NULL DEFAULT '',
            width      INTEGER NOT NULL DEFAULT 0,
            height     INTEGER NOT NULL DEFAULT 0,
            filename   TEXT NOT NULL,
            created_at REAL NOT NULL,
            seed       INTEGER NOT NULL DEFAULT 0,
            sampler    TEXT NOT NULL DEFAULT '',
            scheduler  TEXT NOT NULL DEFAULT '',
            steps      INTEGER NOT NULL DEFAULT 0,
            cfg        REAL NOT NULL DEFAULT 0,
            strength   REAL NOT NULL DEFAULT 0
        )
    """)

    # Migration: add missing columns to existing gallery table
    try:
        conn.execute("ALTER TABLE gallery ADD COLUMN seed INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        conn.execute("ALTER TABLE gallery ADD COLUMN sampler TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE gallery ADD COLUMN scheduler TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE gallery ADD COLUMN steps INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE gallery ADD COLUMN cfg REAL NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE gallery ADD COLUMN strength REAL NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    setting_defaults = {
        "checkpoint": "novaAnimeXL_ilV125.safetensors",
        "sampler": "",
        "scheduler": "",
        "steps": "0",
        "cfg": "0",
        "width": "1024",
        "height": "1024",
        "negative_prompt": "nsfw, explicit, worst quality, worst aesthetic, bad quality, average quality, oldest, old, very displeasing, displeasing",
        "strength": "1.0",
    }
    for k, v in setting_defaults.items():
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = ? WHERE value = ''",
            (k, v, v),
        )

    config_defaults = {
        "comfyui_host": os.getenv("COMFYUI_HOST", "comfyui.khlloreda.com"),
        "comfyui_port": os.getenv("COMFYUI_PORT", "80"),
        "comfyui_secure": os.getenv("COMFYUI_SECURE", "false"),
        "auth_user": "",
        "auth_pass": "",
        "jwt_secret": "",
        "civitai_api_key": "",
        "civitai_nsfw_level": "31",
    }
    for k, v in config_defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (k, v)
        )

    conn.commit()
    conn.close()


def _query_table(table: str) -> Dict[str, str]:
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(f"SELECT key, value FROM {table}").fetchall()
    conn.close()
    return {k: v for k, v in rows}


def _update_table(table: str, data: Dict[str, str]):
    conn = sqlite3.connect(str(DB_PATH))
    for k, v in data.items():
        conn.execute(
            f"INSERT INTO {table} (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (k, str(v)),
        )
    conn.commit()
    conn.close()


def get_all_settings() -> Dict[str, str]:
    return _query_table("settings")


def update_settings(data: Dict[str, str]):
    _update_table("settings", data)


def get_comfyui_config() -> Dict[str, str]:
    return _query_table("config")


def update_comfyui_config(data: Dict[str, str]):
    _update_table("config", data)


def get_comfyui_url() -> str:
    cfg = get_comfyui_config()
    host = cfg.get("comfyui_host", "localhost")
    port = cfg.get("comfyui_port", "8188")
    secure = cfg.get("comfyui_secure", "false").lower() == "true"
    return f"{'https' if secure else 'http'}://{host}:{port}"


def get_auth_credentials() -> tuple[str, str]:
    cfg = get_comfyui_config()
    return cfg.get("auth_user", ""), cfg.get("auth_pass", "")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    return salt.hex() + ":" + key.hex()


def verify_password(password: str, stored_hash: str) -> bool:
    if ":" not in stored_hash:
        if secrets.compare_digest(password, stored_hash):
            new_hash = hash_password(password)
            _update_table("config", {"auth_pass": new_hash})
            return True
        return False
    try:
        salt_hex, key_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
        return secrets.compare_digest(key.hex(), key_hex)
    except (ValueError, AttributeError):
        return False


def get_jwt_secret() -> str:
    cfg = get_comfyui_config()
    secret = cfg.get("jwt_secret", "")
    if not secret:
        secret = secrets.token_hex(32)
        _update_table("config", {"jwt_secret": secret})
    return secret


def create_token(username: str) -> str:
    secret = get_jwt_secret()
    payload = {
        "sub": username,
        "exp": datetime.utcnow() + timedelta(days=30),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_token(token: str) -> dict | None:
    secret = get_jwt_secret()
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None


def save_gallery_image(
    image_bytes: bytes, prompt: str, neg_prompt: str,
    checkpoint: str, width: int, height: int,
    seed: int = 0, sampler: str = "", scheduler: str = "",
    steps: int = 0, cfg: float = 0.0, strength: float = 0.0,
) -> Dict[str, Any]:
    img_id = uuid.uuid4().hex[:12]
    filename = f"{img_id}.png"
    filepath = GALLERY_DIR / filename
    filepath.write_bytes(image_bytes)

    now = time.time()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "INSERT INTO gallery (id, prompt, neg_prompt, checkpoint, width, height, filename, created_at, "
        "seed, sampler, scheduler, steps, cfg, strength) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (img_id, prompt, neg_prompt, checkpoint, width, height, filename, now,
         seed, sampler, scheduler, steps, cfg, strength),
    )
    conn.commit()
    conn.close()
    return {
        "id": img_id, "prompt": prompt, "checkpoint": checkpoint,
        "width": width, "height": height, "filename": filename, "created_at": now,
        "seed": seed, "sampler": sampler, "scheduler": scheduler,
        "steps": steps, "cfg": cfg, "strength": strength,
    }


def list_gallery(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM gallery ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_gallery() -> int:
    conn = sqlite3.connect(str(DB_PATH))
    count = conn.execute("SELECT COUNT(*) FROM gallery").fetchone()[0]
    conn.close()
    return count


def delete_gallery_image(img_id: str) -> bool:
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute("SELECT filename FROM gallery WHERE id = ?", (img_id,)).fetchone()
    if not row:
        conn.close()
        return False
    filepath = GALLERY_DIR / row[0]
    if filepath.exists():
        filepath.unlink()
    conn.execute("DELETE FROM gallery WHERE id = ?", (img_id,))
    conn.commit()
    conn.close()
    return True


# ─── In-memory job metadata (prompt info for gallery save) ───────────────────

_job_meta: Dict[str, Dict[str, Any]] = {}


# ─── JWT Auth Middleware ──────────────────────────────────────────────────────

_PUBLIC_API = {"/api/auth/status", "/api/auth/login", "/api/health"}


class JWTAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path.rstrip("/")

        if not path.startswith("/api"):
            return await call_next(request)

        if path in _PUBLIC_API:
            return await call_next(request)

        cfg = get_comfyui_config()
        if not (cfg.get("auth_user") and cfg.get("auth_pass")):
            return await call_next(request)

        token = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        if not token:
            token = request.query_params.get("token")

        if token and verify_token(token):
            return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )


# ─── Schemas ──────────────────────────────────────────────────────────────────

class GenerationRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    steps: int = 0
    cfg_scale: float = 0
    seed: int = -1
    sampler: str = ""
    scheduler: str = ""
    checkpoint: Optional[str] = None
    strength: float = 1.0


class MissingLoraResult(BaseModel):
    lora_tag: str
    strength_model: float
    strength_clip: float
    candidates: List[Dict[str, Any]] = []


class GenerationResponse(BaseModel):
    job_id: str
    status: str
    images: Optional[List[str]] = None
    error: Optional[str] = None
    missing_loras: Optional[List[MissingLoraResult]] = None


class GenerationVideoRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    width: int = 832
    height: int = 480
    length: int = 81  # frames de video
    fps: float = 8.0
    steps: int = 20
    cfg_scale: float = 7.0
    seed: int = -1
    sampler: str = ""
    scheduler: str = ""
    checkpoint: Optional[str] = None  # UNet/Checkpoint para Wan
    vae: Optional[str] = None  # VAE para Wan
    clip: Optional[str] = None  # T5/UMT5 para Wan


class SettingsPayload(BaseModel):
    checkpoint: Optional[str] = None
    sampler: Optional[str] = None
    scheduler: Optional[str] = None
    steps: Optional[int] = None
    cfg: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    negative_prompt: Optional[str] = None
    strength: Optional[float] = None


class ConfigPayload(BaseModel):
    comfyui_host: Optional[str] = None
    comfyui_port: Optional[str] = None
    comfyui_secure: Optional[str] = None
    auth_user: Optional[str] = None
    auth_pass: Optional[str] = None
    civitai_api_key: Optional[str] = None
    civitai_nsfw_level: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


# ─── App ──────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    configure_civitai(DB_PATH, MODELS_DIR)
    url = get_comfyui_url()
    user, pw = get_auth_credentials()
    print(f"Krita AI Studio Backend v3.1 iniciado")
    print(f"ComfyUI URL: {url}")
    print(f"Auth: {'JWT enabled' if user and pw else 'disabled (open)'}")
    print(f"Database: {DB_PATH}")
    print(f"Gallery: {GALLERY_DIR}")
    print(f"Models cache: {MODELS_DIR}")
    yield
    print("Cerrando Krita AI Studio Backend")


app = FastAPI(
    title="Krita AI Studio API",
    version="3.1.0",
    lifespan=lifespan,
)

app.add_middleware(JWTAuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(civitai_router)


# ─── Auth endpoints ──────────────────────────────────────────────────────────

@app.get("/api/auth/status")
async def auth_status(request: Request):
    cfg = get_comfyui_config()
    auth_enabled = bool(cfg.get("auth_user") and cfg.get("auth_pass"))

    logged_in = False
    if not auth_enabled:
        logged_in = True
    else:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if verify_token(token):
                logged_in = True

    return {
        "auth_enabled": auth_enabled,
        "logged_in": logged_in,
        "username": cfg.get("auth_user", "") if logged_in and auth_enabled else None,
    }


@app.post("/api/auth/login")
async def auth_login(payload: LoginRequest):
    cfg = get_comfyui_config()
    stored_user = cfg.get("auth_user", "")
    stored_hash = cfg.get("auth_pass", "")

    if not stored_user or not stored_hash:
        raise HTTPException(status_code=400, detail="Auth not configured")

    if not secrets.compare_digest(payload.username, stored_user):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(payload.password, stored_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(payload.username)
    return {"token": token, "username": stored_user}


# ─── Config endpoints (ComfyUI connection + auth) ────────────────────────────

@app.get("/api/config")
async def api_get_config():
    cfg = get_comfyui_config()
    url = get_comfyui_url()
    auth_enabled = bool(cfg.get("auth_user") and cfg.get("auth_pass"))
    safe_cfg = {**cfg, "comfyui_url": url, "auth_enabled": auth_enabled}
    if safe_cfg.get("auth_pass"):
        safe_cfg["auth_pass"] = "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"
    safe_cfg.pop("jwt_secret", None)
    return safe_cfg


@app.post("/api/config")
async def api_save_config(payload: ConfigPayload):
    old_cfg = get_comfyui_config()
    was_auth_enabled = bool(old_cfg.get("auth_user") and old_cfg.get("auth_pass"))

    data: Dict[str, str] = {}
    for field, val in payload.model_dump(exclude_none=True).items():
        if field == "auth_pass":
            if val == "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022":
                continue
            if val:
                data[field] = hash_password(val)
            else:
                data[field] = ""
        else:
            data[field] = str(val)
    if data:
        update_comfyui_config(data)

    cfg = get_comfyui_config()
    is_auth_enabled = bool(cfg.get("auth_user") and cfg.get("auth_pass"))
    auth_activated = is_auth_enabled and not was_auth_enabled

    url = get_comfyui_url()
    response: Dict[str, Any] = {
        **cfg,
        "comfyui_url": url,
        "auth_enabled": is_auth_enabled,
    }
    if response.get("auth_pass"):
        response["auth_pass"] = "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"
    response.pop("jwt_secret", None)

    if auth_activated:
        response["token"] = create_token(cfg.get("auth_user", ""))
        response["auth_activated"] = True

    return response


@app.post("/api/config/test")
async def api_test_connection(payload: ConfigPayload):
    host = payload.comfyui_host or "localhost"
    port = payload.comfyui_port or "8188"
    secure = (payload.comfyui_secure or "false").lower() == "true"
    url = f"{'https' if secure else 'http'}://{host}:{port}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{url}/system_stats", timeout=5.0)
            if resp.status_code == 200:
                stats = resp.json()
                vram = stats.get("devices", [{}])[0].get("vram_total", 0)
                vram_gb = round(vram / (1024**3), 1) if vram else 0
                return {
                    "status": "ok",
                    "url": url,
                    "vram_gb": vram_gb,
                    "message": f"Conectado ({vram_gb} GB VRAM)" if vram_gb else "Conectado",
                }
            return {"status": "error", "url": url, "message": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "url": url, "message": str(e)}


# ─── Settings endpoints ──────────────────────────────────────────────────────

@app.get("/api/settings")
async def api_get_settings():
    return get_all_settings()


@app.post("/api/settings")
async def api_save_settings(payload: SettingsPayload):
    data: Dict[str, str] = {}
    for field, val in payload.model_dump(exclude_none=True).items():
        data[field] = str(val)
    if data:
        update_settings(data)
    return get_all_settings()


# ─── Gallery endpoints ───────────────────────────────────────────────────────

@app.get("/api/gallery")
async def api_list_gallery(limit: int = 50, offset: int = 0):
    items = list_gallery(limit, offset)
    total = count_gallery()
    return {"items": items, "total": total}


@app.get("/api/gallery/{img_id}/image")
async def api_gallery_image(img_id: str):
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute("SELECT filename FROM gallery WHERE id = ?", (img_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")
    filepath = GALLERY_DIR / row[0]
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Image file missing")
    return FileResponse(str(filepath), media_type="image/png")


@app.delete("/api/gallery/{img_id}")
async def api_delete_gallery(img_id: str):
    if delete_gallery_image(img_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Image not found")


@app.get("/api/gallery/{img_id}/meta")
async def api_gallery_image_meta(img_id: str):
    """Get full generation metadata for a gallery image."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM gallery WHERE id = ?",
        (img_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")

    data = dict(row)
    # Format to match CivitAI meta structure for frontend reuse
    # Use .get() with defaults for backward compatibility with old images
    return {
        "id": data.get("id", ""),
        "url": f"/api/gallery/{img_id}/image",
        "prompt": data.get("prompt", ""),
        "neg_prompt": data.get("neg_prompt", ""),
        "checkpoint": data.get("checkpoint", ""),
        "width": data.get("width", 0),
        "height": data.get("height", 0),
        "seed": data.get("seed", 0),
        "sampler": data.get("sampler", ""),
        "scheduler": data.get("scheduler", ""),
        "steps": data.get("steps", 0),
        "cfg": data.get("cfg", 0),
        "strength": data.get("strength", 0),
        "created_at": data.get("created_at", 0),
        "meta": {
            "prompt": data.get("prompt", ""),
            "negativePrompt": data.get("neg_prompt", ""),
            "Model": data.get("checkpoint", ""),
            "Size": f"{data.get('width', 0)}x{data.get('height', 0)}",
            "seed": data.get("seed", 0),
            "sampler": data.get("sampler", ""),
            "scheduler": data.get("scheduler", ""),
            "steps": data.get("steps", 0),
            "cfg": data.get("cfg", 0),
            "strength": data.get("strength") if data.get("strength") else None,
        }
    }


# ─── Health / Models / Samplers ───────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    comfy_url = get_comfyui_url()
    comfy_status = "unknown"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{comfy_url}/system_stats", timeout=5.0)
            comfy_status = "ok" if response.status_code == 200 else "error"
    except Exception as e:
        comfy_status = f"error: {str(e)}"

    return {"status": "ok", "comfyui": comfy_status, "comfyui_url": comfy_url}


@app.get("/api/models")
async def get_models():
    """
    Lista modelos disponibles.
    Intenta usar el plugin comfyui-kas para obtener todos los tipos (checkpoints, loras, etc.)
    Fallback a object_info/CheckpointLoaderSimple si el plugin no esta disponible.
    """
    comfy_url = get_comfyui_url()

    # Intentar usar el plugin comfyui-kas primero
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{comfy_url}/api/kas/models",
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", {})

                # Transformar al formato esperado por el frontend
                checkpoints = [
                    {"name": m["filename"], "type": "checkpoint", **m}
                    for m in models.get("checkpoints", [])
                ]
                loras = [
                    {"name": m["filename"], "type": "lora", **m}
                    for m in models.get("loras", [])
                ]
                controlnets = [
                    {"name": m["filename"], "type": "controlnet", **m}
                    for m in models.get("controlnet", [])
                ]

                return {
                    "checkpoints": checkpoints,
                    "loras": loras,
                    "controlnets": controlnets,
                    "via_plugin": True,
                }
    except Exception as e:
        print(f"[models] Plugin no disponible ({e}), usando fallback")

    # Fallback: object_info/CheckpointLoaderSimple (solo checkpoints)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{comfy_url}/object_info/CheckpointLoaderSimple", timeout=5.0
            )
            if response.status_code == 200:
                info = response.json()
                models = (
                    info.get("CheckpointLoaderSimple", {})
                    .get("input", {})
                    .get("required", {})
                    .get("ckpt_name", [[]])[0]
                )
                return {
                    "checkpoints": [
                        {"name": m, "type": "checkpoint"} for m in models
                    ],
                    "loras": [],
                    "controlnets": [],
                    "via_plugin": False,
                }
    except Exception as e:
        print(f"[models] Error en fallback: {e}")

    return {
        "checkpoints": [],
        "loras": [],
        "controlnets": [],
        "via_plugin": False,
        "fallback": True,
    }


INVENTORY_CATEGORIES = {
    "image_models": {
        "label": "Modelos de Imagen",
        "icon": "cube",
        "folders": ["checkpoints"],
    },
    "loras": {
        "label": "LoRAs",
        "icon": "sparkles",
        "folders": ["loras"],
    },
    "video_models": {
        "label": "Modelos de Vídeo",
        "icon": "film",
        "folders": ["diffusion_models"],
    },
    "controlnet": {
        "label": "ControlNet",
        "icon": "sliders",
        "folders": ["controlnet"],
    },
    "components": {
        "label": "Componentes (VAE / CLIP / etc.)",
        "icon": "cog",
        "folders": ["vae", "text_encoders", "clip_vision"],
    },
    "upscalers": {
        "label": "Upscalers",
        "icon": "arrow-up",
        "folders": ["upscale_models"],
    },
    "other": {
        "label": "Otros",
        "icon": "folder",
        "folders": ["embeddings", "ipadapter", "inpaint", "gligen", "diffusers", "vae_approx"],
    },
}

BASE_MODEL_PATTERNS = [
    ("Hunyuan", ["hunyuan"]),
    ("LTX Video", ["ltx"]),
    ("Wan 2.1", ["wan"]),
    ("Illustrious XL", ["illustrious", "illu", "noobai", "novaanime"]),
    ("Flux", ["flux"]),
    ("SD 3", ["sd3", "stable_diffusion_3"]),
    ("SDXL", ["sdxl", "xl", "pony", "zavychroma", "realvis"]),
    ("SD 1.5", ["sd15", "sd1.", "v1-5", "revanimated", "dreamshaper"]),
]


def _detect_base_model(filename: str) -> str:
    name = filename.lower()
    for base, patterns in BASE_MODEL_PATTERNS:
        for p in patterns:
            if p in name:
                return base
    return ""


@app.get("/api/inventory")
async def get_inventory():
    """
    Inventario completo de modelos en ComfyUI, agrupado por uso funcional.
    Cruza con model_cache para enriquecer con metadata de CivitAI.
    """
    comfy_url = get_comfyui_url()

    # Cargar model_cache local para cruzar por filename
    civitai_map: Dict[str, Dict[str, Any]] = {}
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT filename, name, type, civitai_model_id, civitai_version_id, status "
            "FROM model_cache WHERE status = 'completed'"
        ).fetchall()
        for r in rows:
            civitai_map[r["filename"]] = dict(r)
        conn.close()
    except Exception:
        pass

    # Obtener modelos del plugin KAS
    all_models: Dict[str, list] = {}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{comfy_url}/api/kas/models", timeout=15.0)
            if resp.status_code == 200:
                all_models = resp.json().get("models", {})
    except Exception as e:
        return {"error": f"No se pudo conectar al plugin KAS: {e}", "categories": []}

    # Construir categorías
    categories = []
    total_size = 0
    total_files = 0
    assigned_folders: set = set()

    for cat_key, cat_cfg in INVENTORY_CATEGORIES.items():
        items = []
        cat_size = 0
        for folder_name in cat_cfg["folders"]:
            assigned_folders.add(folder_name)
            folder_models = all_models.get(folder_name, [])
            for m in folder_models:
                fname = m.get("filename", "")
                size = m.get("size_bytes", 0) or 0
                civitai_info = civitai_map.get(fname)
                base_model = _detect_base_model(fname)

                item = {
                    "filename": fname,
                    "folder": folder_name,
                    "size_bytes": size,
                    "base_model": base_model,
                    "from_civitai": civitai_info is not None,
                    "civitai_name": civitai_info["name"] if civitai_info else None,
                    "civitai_model_id": civitai_info["civitai_model_id"] if civitai_info else None,
                }
                items.append(item)
                cat_size += size

        if not items:
            continue

        items.sort(key=lambda x: x["filename"].lower())
        total_size += cat_size
        total_files += len(items)
        categories.append({
            "key": cat_key,
            "label": cat_cfg["label"],
            "icon": cat_cfg["icon"],
            "items": items,
            "count": len(items),
            "total_bytes": cat_size,
        })

    # Descargas activas
    active_downloads = []
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, type, filename, size_bytes, progress, status, download_url "
            "FROM model_cache WHERE status = 'downloading'"
        ).fetchall()
        active_downloads = [dict(r) for r in rows]
        conn.close()
    except Exception:
        pass

    return {
        "categories": categories,
        "total_files": total_files,
        "total_bytes": total_size,
        "active_downloads": active_downloads,
    }


@app.delete("/api/inventory/{folder}/{filename}")
async def delete_inventory_model(folder: str, filename: str):
    """Borra un modelo del ComfyUI remoto via plugin KAS."""
    comfy_url = get_comfyui_url()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{comfy_url}/api/kas/models/{folder}/{filename}",
                timeout=10.0,
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": resp.text, "status_code": resp.status_code}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _search_civitai_lora(name: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Busca LoRAs en CivitAI por nombre y retorna candidatos simplificados."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://civitai.com/api/v1/models",
                params={
                    "query": name,
                    "types": "LORA",
                    "sort": "Most Downloaded",
                    "limit": limit,
                },
            )
            if resp.status_code != 200:
                return []

            items = resp.json().get("items", [])
            results = []
            for item in items[:limit]:
                versions = item.get("modelVersions", [])
                version = versions[0] if versions else {}
                files = version.get("files", [])
                primary_file = next(
                    (f for f in files if f.get("primary")),
                    files[0] if files else {},
                )
                images = version.get("images", [])
                thumb = images[0].get("url", "") if images else ""

                results.append({
                    "civitai_model_id": item.get("id"),
                    "civitai_version_id": version.get("id"),
                    "name": item.get("name", ""),
                    "filename": primary_file.get("name", ""),
                    "size_bytes": primary_file.get("sizeKB", 0) * 1024,
                    "download_url": version.get("downloadUrl", ""),
                    "base_model": version.get("baseModel", ""),
                    "thumbnail": thumb,
                    "download_count": item.get("stats", {}).get("downloadCount", 0),
                    "rating": item.get("stats", {}).get("rating", 0),
                })
            return results
    except Exception as e:
        print(f"[search_lora] Error buscando '{name}': {e}")
        return []


class LoraDownloadRequest(BaseModel):
    civitai_model_id: int
    civitai_version_id: int
    name: str
    filename: str
    download_url: str
    size_bytes: float = 0


@app.post("/api/lora/download")
async def download_lora(req: LoraDownloadRequest):
    """Descarga un LoRA desde CivitAI directamente a ComfyUI via KAS plugin."""
    comfy_url = get_comfyui_url()
    civitai_key = ""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        row = conn.execute(
            "SELECT value FROM config WHERE key='civitai_api_key'"
        ).fetchone()
        if row and row[0]:
            civitai_key = row[0]
        conn.close()
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "download_url": req.download_url,
                "filename": req.filename,
                "type": "LORA",
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
                plugin_dl_id = result.get("download", {}).get("id", "")
                return {"status": "downloading", "download_id": plugin_dl_id}

            return {"status": "error", "detail": resp.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/lora/download-status/{download_id}")
async def lora_download_status(download_id: str):
    """Consulta el estado de una descarga de LoRA en el plugin KAS."""
    comfy_url = get_comfyui_url()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{comfy_url}/api/kas/downloads")
            if resp.status_code == 200:
                downloads = resp.json().get("downloads", [])
                for dl in downloads:
                    if dl.get("id") == download_id:
                        return {
                            "status": dl.get("status", "unknown"),
                            "progress": dl.get("progress", 0),
                            "error": dl.get("error"),
                            "filename": dl.get("filename", ""),
                        }
                return {"status": "not_found"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.get("/api/samplers")
async def get_samplers():
    samplers = [
        "euler_ancestral",
        "euler",
        "dpmpp_2m",
        "dpmpp_2m_sde",
        "dpmpp_2m_sde_gpu",
        "dpmpp_sde_gpu",
        "dpmpp_2s_ancestral",
        "uni_pc_bh2",
        "res_multistep",
        "heun",
        "dpm_2",
        "dpm_2_ancestral",
        "lms",
        "ddim",
    ]
    return {"samplers": samplers}


# ─── Generation ───────────────────────────────────────────────────────────────

@app.post("/api/generate/txt2img", response_model=GenerationResponse)
async def txt2img(request: GenerationRequest):
    comfy_url = get_comfyui_url()
    try:
        actual_seed = request.seed
        if actual_seed < 0:
            actual_seed = random.randint(0, 2**32 - 1)

        clean_prompt, lora_tags = parse_lora_tags(request.prompt)
        resolved_loras = None
        if lora_tags:
            available_loras = []
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(f"{comfy_url}/api/kas/models?folder=loras")
                    if resp.status_code == 200:
                        data = resp.json()
                        available_loras = [
                            m["filename"]
                            for m in data.get("models", {}).get("loras", [])
                        ]
            except Exception as e:
                print(f"[txt2img] No se pudo obtener lista de LoRAs: {e}")

            resolved_loras = []
            missing_loras = []
            for name, strength_model, strength_clip in lora_tags:
                filename = resolve_lora_filename(name, available_loras)
                if filename:
                    resolved_loras.append((filename, strength_model, strength_clip))
                    print(f"[txt2img] LoRA resuelto: {name} -> {filename} (model={strength_model}, clip={strength_clip})")
                else:
                    print(f"[txt2img] LoRA no encontrado: {name}")
                    missing_loras.append((name, strength_model, strength_clip))

            if missing_loras:
                candidates_list = []
                for lora_name, sm, sc in missing_loras:
                    candidates = await _search_civitai_lora(lora_name)
                    candidates_list.append(MissingLoraResult(
                        lora_tag=lora_name,
                        strength_model=sm,
                        strength_clip=sc,
                        candidates=candidates,
                    ))
                return GenerationResponse(
                    job_id="",
                    status="missing_loras",
                    missing_loras=candidates_list,
                )

        workflow = create_txt2img_workflow_krita(
            prompt=clean_prompt if lora_tags else request.prompt,
            negative_prompt=request.negative_prompt or "",
            checkpoint=request.checkpoint or "SDXL.safetensors",
            sampler=request.sampler or "",
            scheduler=request.scheduler or "",
            steps=request.steps,
            cfg=request.cfg_scale,
            seed=actual_seed,
            width=request.width,
            height=request.height,
            batch_size=1,
            loras=resolved_loras if resolved_loras else None,
        )
        print(f"Generating with seed={actual_seed}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{comfy_url}/prompt",
                json={"prompt": workflow},
                timeout=5.0,
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=500, detail=f"ComfyUI error: {response.text}"
                )

            result = response.json()
            prompt_id = result.get("prompt_id")

            _job_meta[prompt_id] = {
                "prompt": request.prompt,
                "neg_prompt": request.negative_prompt or "",
                "checkpoint": request.checkpoint or "",
                "width": request.width,
                "height": request.height,
                "seed": actual_seed,
                "sampler": request.sampler or "",
                "scheduler": request.scheduler or "",
                "steps": request.steps or 0,
                "cfg": request.cfg_scale or 0.0,
                "strength": request.strength or 0.0,
            }

            return GenerationResponse(job_id=prompt_id, status="queued", images=None)

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error en txt2img: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Job polling ──────────────────────────────────────────────────────────────

_saved_jobs: set = set()

@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    comfy_url = get_comfyui_url()
    try:
        async with httpx.AsyncClient() as client:
            queue_resp = await client.get(f"{comfy_url}/queue", timeout=5.0)
            if queue_resp.status_code == 200:
                queue_data = queue_resp.json()

                for job in queue_data.get("queue_running", []):
                    if (
                        isinstance(job, list)
                        and len(job) > 1
                        and isinstance(job[1], dict)
                    ):
                        if job[1].get("prompt_id") == job_id:
                            return {
                                "job_id": job_id,
                                "status": "processing",
                                "progress": 50,
                            }

                for job in queue_data.get("queue_pending", []):
                    if (
                        isinstance(job, list)
                        and len(job) > 1
                        and isinstance(job[1], dict)
                    ):
                        if job[1].get("prompt_id") == job_id:
                            return {
                                "job_id": job_id,
                                "status": "queued",
                                "progress": 0,
                            }

            response = await client.get(
                f"{comfy_url}/history/{job_id}", timeout=10.0
            )

            if response.status_code == 200:
                history = response.json()
                job_data = history.get(job_id, {})

                if job_data:
                    status_info = job_data.get("status", {})
                    status_str = status_info.get("status_str", "unknown")

                    if status_str == "error":
                        msgs = status_info.get("messages", [])
                        err_msg = (
                            str(msgs[-1]) if msgs else "ComfyUI execution error"
                        )
                        return {
                            "job_id": job_id,
                            "status": "error",
                            "error": err_msg,
                        }

                    outputs = job_data.get("outputs", {})
                    images_base64: List[str] = []
                    images_raw: List[bytes] = []
                    video_ids: List[str] = []

                    for node_id, node_output in outputs.items():
                        if not isinstance(node_output, dict):
                            continue
                        images = node_output.get("images", [])
                        for img in images:
                            if not isinstance(img, dict):
                                continue
                            if img.get("source") == "http":
                                img_id = img.get("id")
                                if img_id:
                                    # Verificar si es video (KAS_SaveVideoCache)
                                    # Los videos de KAS tienen ids que empiezan con "kas_"
                                    if img_id.startswith("kas_"):
                                        video_ids.append(img_id)
                                    else:
                                        # Es una imagen normal (ETN_SaveImageCache)
                                        img_resp = await client.get(
                                            f"{comfy_url}/api/etn/image/{img_id}",
                                            timeout=60.0,
                                        )
                                        if img_resp.status_code == 200:
                                            images_raw.append(img_resp.content)
                                            img_b64 = base64.b64encode(
                                                img_resp.content
                                            ).decode("utf-8")
                                            images_base64.append(img_b64)

                    # Manejar videos generados
                    if video_ids:
                        if job_id not in _saved_jobs:
                            _saved_jobs.add(job_id)
                            meta = _job_meta.pop(job_id, {})
                            print(f"Video job completed: {video_ids}")

                        return {
                            "job_id": job_id,
                            "status": "completed",
                            "videos": video_ids,
                            "video_ids": video_ids,
                            "progress": 100,
                            "is_video": True,
                        }

                    # Manejar imagenes generadas
                    if images_base64:
                        if job_id not in _saved_jobs:
                            _saved_jobs.add(job_id)
                            meta = _job_meta.pop(job_id, {})
                            gallery_ids = []
                            for raw in images_raw:
                                entry = save_gallery_image(
                                    image_bytes=raw,
                                    prompt=meta.get("prompt", ""),
                                    neg_prompt=meta.get("neg_prompt", ""),
                                    checkpoint=meta.get("checkpoint", ""),
                                    width=meta.get("width", 0),
                                    height=meta.get("height", 0),
                                    seed=meta.get("seed", 0),
                                    sampler=meta.get("sampler", ""),
                                    scheduler=meta.get("scheduler", ""),
                                    steps=meta.get("steps", 0),
                                    cfg=meta.get("cfg", 0.0),
                                    strength=meta.get("strength", 0.0),
                                )
                                gallery_ids.append(entry["id"])
                            print(f"Saved {len(gallery_ids)} images to gallery")

                        return {
                            "job_id": job_id,
                            "status": "completed",
                            "images": images_base64,
                            "progress": 100,
                            "is_video": False,
                        }

                    return {
                        "job_id": job_id,
                        "status": "completed",
                        "images": [],
                        "error": "No images in output",
                        "progress": 100,
                    }

            return {"job_id": job_id, "status": "processing", "progress": 25}

    except Exception as e:
        import traceback
        print(f"Error checking job {job_id}: {e}")
        traceback.print_exc()
        return {"job_id": job_id, "status": "error", "error": str(e)}


# ─── Video Proxy Endpoints ─────────────────────────────────────────────────────

@app.get("/api/video/{video_id}")
async def proxy_video(video_id: str):
    """Proxy para servir videos desde el cache del plugin ComfyUI."""
    comfy_url = get_comfyui_url()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{comfy_url}/api/kas/video/{video_id}",
                timeout=60.0,
            )
            if resp.status_code == 200:
                from fastapi.responses import Response
                return Response(
                    content=resp.content,
                    media_type=resp.headers.get("content-type", "video/webm"),
                    headers={
                        "Cache-Control": "no-cache",
                        "Accept-Ranges": "bytes",
                    },
                )
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Video not found or expired")
            raise HTTPException(status_code=resp.status_code, detail="ComfyUI error")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate/txt2video", response_model=GenerationResponse)
async def txt2video(request: GenerationVideoRequest):
    """Genera video usando Wan 2.1 T2V via workflow."""
    comfy_url = get_comfyui_url()
    try:
        actual_seed = request.seed
        if actual_seed < 0:
            actual_seed = random.randint(0, 2**32 - 1)

        VIDEO_UNET_DEFAULT = "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors"
        available_unets: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{comfy_url}/api/kas/models?folder=diffusion_models")
                if r.status_code == 200:
                    available_unets = [
                        m["filename"] for m in r.json().get("models", {}).get("diffusion_models", [])
                    ]
        except Exception:
            pass

        req_checkpoint = request.checkpoint or ""
        video_checkpoint = req_checkpoint if req_checkpoint in available_unets else VIDEO_UNET_DEFAULT

        workflow = create_txt2video_workflow(
            prompt=request.prompt,
            negative_prompt=request.negative_prompt or "",
            checkpoint=video_checkpoint,
            vae=request.vae or "wan_2.1_vae.safetensors",
            clip=request.clip or "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            sampler=request.sampler or "",
            scheduler=request.scheduler or "",
            steps=request.steps or 20,
            cfg=request.cfg_scale,
            seed=actual_seed,
            width=request.width,
            height=request.height,
            length=request.length,
            fps=request.fps,
            batch_size=1,
        )
        print(f"Generating video with seed={actual_seed}, length={request.length}, unet={video_checkpoint}, clip={request.clip or 'umt5_xxl_fp8_e4m3fn_scaled.safetensors'}")
        import json as _json
        print(f"[txt2video] Workflow nodes: {list(workflow.keys())}")
        for nid, node in workflow.items():
            print(f"  [{nid}] {node.get('class_type','?')}: {_json.dumps(node.get('inputs',{}), default=str)[:200]}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{comfy_url}/prompt",
                json={"prompt": workflow},
                timeout=5.0,
            )
            if response.status_code != 200:
                print(f"[txt2video] ComfyUI rejected: {response.text[:500]}")
                raise HTTPException(
                    status_code=500, detail=f"ComfyUI error: {response.text}"
                )

            result = response.json()
            prompt_id = result.get("prompt_id")

            _job_meta[prompt_id] = {
                "prompt": request.prompt,
                "neg_prompt": request.negative_prompt or "",
                "checkpoint": video_checkpoint,
                "width": request.width,
                "height": request.height,
                "length": request.length,
                "fps": request.fps,
                "seed": actual_seed,
                "sampler": request.sampler or "",
                "scheduler": request.scheduler or "",
                "steps": request.steps or 0,
                "cfg": request.cfg_scale or 0.0,
                "is_video": True,
            }

            return GenerationResponse(job_id=prompt_id, status="queued", images=None)

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error en txt2video: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Static frontend ─────────────────────────────────────────────────────────

frontend_path = Path(__file__).parent / "frontend" / "dist"
frontend_dir = str(frontend_path) if frontend_path.exists() else None
print(f"Frontend path: {frontend_path}, exists: {frontend_path.exists()}")

if frontend_dir:
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
else:

    @app.get("/")
    async def no_frontend():
        return {"error": "Frontend not built"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=3000)

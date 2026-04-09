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
import urllib.parse
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
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
import httpx
import jwt

from workflow_krita import (
    build_txt2img_workflow,
    build_txt2video_workflow,
    parse_lora_tags,
    resolve_lora_filename,
)
from architectures import get_arch_manager
from civitai import router as civitai_router, configure as configure_civitai, get_content_filter_info
from oauth_microsoft import (
    oauth_env_configured,
    build_authorize_url,
    exchange_code_for_tokens,
    validate_microsoft_id_token,
    get_app_public_url,
    allow_legacy_login,
    cookie_secure,
    get_oauth_admin_emails,
)

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
JWT_COOKIE_NAME = "kas_token"
MS_OAUTH_STATE_COOKIE = "ms_oauth_state"
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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_overrides (
            filename     TEXT PRIMARY KEY,
            architecture TEXT,
            sampling     TEXT DEFAULT '{}',
            clip         TEXT DEFAULT '{}',
            vae          TEXT,
            hidden       INTEGER DEFAULT 0,
            notes        TEXT DEFAULT ''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_favorites (
            folder      TEXT NOT NULL,
            filename    TEXT NOT NULL,
            label       TEXT NOT NULL DEFAULT '',
            sort_order  INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (folder, filename)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              TEXT PRIMARY KEY,
            microsoft_oid   TEXT UNIQUE NOT NULL,
            email           TEXT NOT NULL DEFAULT '',
            display_name    TEXT NOT NULL DEFAULT '',
            role            TEXT NOT NULL DEFAULT 'user',
            disabled        INTEGER NOT NULL DEFAULT 0,
            created_at      REAL NOT NULL,
            last_login      REAL NOT NULL DEFAULT 0
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_email ON users (email)"
    )

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
    try:
        conn.execute("ALTER TABLE gallery ADD COLUMN type TEXT NOT NULL DEFAULT 'image'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE gallery ADD COLUMN length INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE gallery ADD COLUMN fps REAL NOT NULL DEFAULT 0")
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
        "civitai_nsfw_level": "",
        "openai_api_base": os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
        "openai_model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "openai_organization": os.getenv("OPENAI_ORGANIZATION", ""),
        "llm_temperature": "0.7",
        "llm_max_tokens": "512",
        "llm_content_filter": "false",
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


def _content_filter_env_level() -> int:
    """Misma variable CONTENT_FILTER que CivitAI (civitai.py): 0 = sin restricción; otro = política activa."""
    try:
        return int(os.getenv("CONTENT_FILTER", "1"))
    except (ValueError, TypeError):
        return 1


def _llm_filter_mandatory() -> bool:
    """Si CONTENT_FILTER != 0, el filtro LLM previo a ComfyUI es obligatorio."""
    return _content_filter_env_level() != 0


def get_llm_filter_info(cfg: Dict[str, str]) -> Dict[str, Any]:
    mandatory = _llm_filter_mandatory()
    raw = (cfg.get("llm_content_filter") or "false").lower()
    user_on = raw in ("true", "1", "yes")
    effective = mandatory or user_on
    return {
        "mandatory": mandatory,
        "user_enabled": user_on,
        "effective": effective,
        "can_toggle": not mandatory,
        "content_filter_level": _content_filter_env_level(),
    }


def _llm_prompt_filter_effective(cfg: Dict[str, str]) -> bool:
    """¿Aplicar paso interno de filtrado del prompt antes de enviar a ComfyUI?"""
    if _llm_filter_mandatory():
        return True
    raw = (cfg.get("llm_content_filter") or "false").lower()
    return raw in ("true", "1", "yes")


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


def create_app_jwt_legacy(username: str) -> str:
    secret = get_jwt_secret()
    now = datetime.utcnow()
    payload = {
        "sub": username,
        "role": "admin",
        "typ": "legacy",
        "exp": now + timedelta(days=30),
        "iat": now,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def create_app_jwt_oauth(user_id: str, email: str, role: str) -> str:
    secret = get_jwt_secret()
    now = datetime.utcnow()
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "typ": "oauth",
        "exp": now + timedelta(days=30),
        "iat": now,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_token(token: str) -> dict | None:
    secret = get_jwt_secret()
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None


def app_auth_enabled(cfg: Optional[Dict[str, str]] = None) -> bool:
    if cfg is None:
        cfg = get_comfyui_config()
    if oauth_env_configured():
        return True
    return bool(cfg.get("auth_user") and cfg.get("auth_pass"))


def _count_active_admins() -> int:
    conn = sqlite3.connect(str(DB_PATH))
    n = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled = 0"
    ).fetchone()[0]
    conn.close()
    return int(n)


def user_is_disabled(user_id: str) -> bool:
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute("SELECT disabled FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return True
    return bool(row[0])


def user_upsert_oauth(microsoft_oid: str, email: str, display_name: str) -> tuple[str, str]:
    admin_emails = get_oauth_admin_emails()
    email_l = (email or "").strip().lower()
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT id, role FROM users WHERE microsoft_oid = ?", (microsoft_oid,)
    ).fetchone()
    now = time.time()
    if row:
        uid, role = row[0], row[1]
        conn.execute(
            "UPDATE users SET email = ?, display_name = ?, last_login = ? WHERE id = ?",
            (email or "", display_name or "", now, uid),
        )
        conn.commit()
        conn.close()
        return uid, role
    admins = _count_active_admins()
    if admins == 0:
        role = "admin"
    elif email_l and email_l in admin_emails:
        role = "admin"
    else:
        role = "user"
    uid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO users (id, microsoft_oid, email, display_name, role, disabled, "
        "created_at, last_login) VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
        (uid, microsoft_oid, email or "", display_name or "", role, now, now),
    )
    conn.commit()
    conn.close()
    return uid, role


def list_users_db() -> List[Dict[str, Any]]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, email, display_name, role, disabled, last_login FROM users ORDER BY email"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_user_db(
    user_id: str, role: Optional[str] = None, disabled: Optional[bool] = None
) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        conn.close()
        return None
    if role is not None:
        if role not in ("admin", "user"):
            conn.close()
            raise ValueError("Invalid role")
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    if disabled is not None:
        conn.execute(
            "UPDATE users SET disabled = ? WHERE id = ?", (1 if disabled else 0, user_id)
        )
    conn.commit()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, email, display_name, role, disabled, last_login FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def token_payload_allowed(payload: Dict[str, Any], cfg: Dict[str, str]) -> bool:
    if not payload:
        return False
    typ = payload.get("typ")
    if typ == "oauth":
        uid = payload.get("sub")
        if not uid or not isinstance(uid, str):
            return False
        return not user_is_disabled(uid)
    if typ == "legacy":
        return bool(
            cfg.get("auth_user")
            and secrets.compare_digest(str(payload.get("sub", "")), str(cfg.get("auth_user", "")))
        )
    u = cfg.get("auth_user", "")
    p = cfg.get("auth_pass", "")
    if u and p and payload.get("sub") == u:
        return True
    return False


def is_admin_payload(payload: Dict[str, Any], cfg: Dict[str, str]) -> bool:
    if not payload:
        return False
    typ = payload.get("typ")
    if typ == "oauth":
        return str(payload.get("role", "")).lower() == "admin"
    if typ == "legacy":
        return True
    u = cfg.get("auth_user", "")
    return bool(u and payload.get("sub") == u)


def attach_auth_cookie(response: JSONResponse | RedirectResponse, token: str) -> None:
    response.set_cookie(
        key=JWT_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=30 * 24 * 3600,
        samesite="lax",
        secure=cookie_secure(),
        path="/",
    )


def clear_auth_cookie(response: JSONResponse | RedirectResponse) -> None:
    response.delete_cookie(JWT_COOKIE_NAME, path="/")


def extract_token_from_request(request: Request) -> Optional[str]:
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        t = auth_header[7:].strip()
        if t:
            return t
    q = request.query_params.get("token")
    if q:
        return q
    c = request.cookies.get(JWT_COOKIE_NAME)
    return c if c else None


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


def save_gallery_video(
    video_bytes: bytes, prompt: str, neg_prompt: str,
    checkpoint: str, width: int, height: int,
    seed: int = 0, sampler: str = "", scheduler: str = "",
    steps: int = 0, cfg: float = 0.0, length: int = 0, fps: float = 0.0,
) -> Dict[str, Any]:
    vid_id = uuid.uuid4().hex[:12]
    if len(video_bytes) >= 4 and video_bytes[:4] == b"RIFF":
        ext = ".webp"
    elif len(video_bytes) >= 3 and video_bytes[:3] == b"GIF":
        ext = ".gif"
    elif len(video_bytes) >= 4 and video_bytes[:4] == b"\x1aE\xdf\xa3":
        ext = ".webm"
    else:
        ext = ".webp"
    filename = f"{vid_id}{ext}"
    filepath = GALLERY_DIR / filename
    filepath.write_bytes(video_bytes)

    now = time.time()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "INSERT INTO gallery (id, prompt, neg_prompt, checkpoint, width, height, filename, created_at, "
        "seed, sampler, scheduler, steps, cfg, strength, type, length, fps) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'video', ?, ?)",
        (vid_id, prompt, neg_prompt, checkpoint, width, height, filename, now,
         seed, sampler, scheduler, steps, cfg, length, fps),
    )
    conn.commit()
    conn.close()
    return {
        "id": vid_id, "prompt": prompt, "checkpoint": checkpoint,
        "width": width, "height": height, "filename": filename,
        "created_at": now, "type": "video", "length": length, "fps": fps,
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

_PUBLIC_API = {
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/health",
    "/api/auth/microsoft/start",
    "/api/auth/microsoft/callback",
}

# Mismo valor que el frontend al mostrar claves guardadas (no re-enviar al guardar)
_CONFIG_SECRET_PLACEHOLDER = "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"


class JWTAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path.rstrip("/")

        if not path.startswith("/api"):
            return await call_next(request)

        if path in _PUBLIC_API:
            return await call_next(request)

        cfg = get_comfyui_config()
        if not app_auth_enabled(cfg):
            return await call_next(request)

        token = extract_token_from_request(request)
        payload = verify_token(token) if token else None
        if payload and token_payload_allowed(payload, cfg):
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
    model_type: Optional[str] = None  # "checkpoint" or "diffusion_model"
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


class ModelFavoritePayload(BaseModel):
    folder: str
    filename: str
    label: str = ""
    sort_order: Optional[int] = None


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
    openai_api_base: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    openai_organization: Optional[str] = None
    llm_temperature: Optional[str] = None
    llm_max_tokens: Optional[str] = None
    llm_content_filter: Optional[str] = None


class LLMTestPayload(BaseModel):
    openai_api_base: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    openai_organization: Optional[str] = None


class PromptEnhanceRequest(BaseModel):
    prompt: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserPatchPayload(BaseModel):
    role: Optional[str] = None
    disabled: Optional[bool] = None


# ─── App ──────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    configure_civitai(DB_PATH, MODELS_DIR)
    url = get_comfyui_url()
    user, pw = get_auth_credentials()
    if oauth_env_configured():
        auth_msg = "OAuth Microsoft + JWT"
    elif user and pw:
        auth_msg = "JWT (login local)"
    else:
        auth_msg = "disabled (open)"
    print(f"Krita AI Studio Backend v3.1 iniciado")
    print(f"ComfyUI URL: {url}")
    print(f"Auth app: {auth_msg}")
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
    enabled = app_auth_enabled(cfg)
    legacy_creds = bool(cfg.get("auth_user") and cfg.get("auth_pass"))
    oauth_on = oauth_env_configured()
    legacy_allowed = allow_legacy_login() or not oauth_on

    token = extract_token_from_request(request)
    payload = verify_token(token) if token else None
    valid = bool(payload and token_payload_allowed(payload, cfg))
    logged_in = (not enabled) or valid

    out: Dict[str, Any] = {
        "auth_enabled": enabled,
        "logged_in": logged_in,
        "oauth_available": oauth_on,
        "legacy_login": legacy_creds and legacy_allowed,
        "username": None,
        "email": None,
        "user_id": None,
        "role": None,
        "is_admin": False,
    }
    if valid and payload:
        if payload.get("typ") == "oauth":
            out["username"] = payload.get("email") or payload.get("sub")
            out["email"] = payload.get("email")
            out["user_id"] = payload.get("sub")
            out["role"] = payload.get("role")
        else:
            out["username"] = payload.get("sub")
            out["role"] = payload.get("role") or "admin"
        out["is_admin"] = is_admin_payload(payload, cfg)

    return out


@app.post("/api/auth/login")
async def auth_login(payload: LoginRequest):
    if oauth_env_configured() and not allow_legacy_login():
        raise HTTPException(status_code=403, detail="Local login disabled")

    cfg = get_comfyui_config()
    stored_user = cfg.get("auth_user", "")
    stored_hash = cfg.get("auth_pass", "")

    if not stored_user or not stored_hash:
        raise HTTPException(status_code=400, detail="Auth not configured")

    if not secrets.compare_digest(payload.username, stored_user):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(payload.password, stored_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_app_jwt_legacy(stored_user)
    r = JSONResponse(content={"token": token, "username": stored_user})
    attach_auth_cookie(r, token)
    return r


@app.post("/api/auth/logout")
async def auth_logout():
    r = JSONResponse(content={"status": "ok"})
    clear_auth_cookie(r)
    r.delete_cookie(MS_OAUTH_STATE_COOKIE, path="/")
    return r


@app.get("/api/auth/microsoft/start")
async def oauth_microsoft_start():
    if not oauth_env_configured():
        raise HTTPException(status_code=404, detail="OAuth not configured")
    state = secrets.token_urlsafe(32)
    resp = RedirectResponse(url=build_authorize_url(state), status_code=302)
    resp.set_cookie(
        MS_OAUTH_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
        path="/",
    )
    return resp


@app.get("/api/auth/microsoft/callback")
async def oauth_microsoft_callback(request: Request):
    base = get_app_public_url()
    err = request.query_params.get("error")
    if err:
        return RedirectResponse(
            url=f"{base}/?login_error={urllib.parse.quote(err)}",
            status_code=302,
        )
    if not oauth_env_configured():
        return RedirectResponse(url=f"{base}/?login_error=config", status_code=302)

    state = request.query_params.get("state") or ""
    code = request.query_params.get("code") or ""
    cookie_state = request.cookies.get(MS_OAUTH_STATE_COOKIE) or ""

    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        return RedirectResponse(url=f"{base}/?login_error=state", status_code=302)
    if not code:
        return RedirectResponse(url=f"{base}/?login_error=code", status_code=302)

    try:
        tokens = await exchange_code_for_tokens(code)
        id_tok = tokens.get("id_token")
        if not id_tok:
            return RedirectResponse(url=f"{base}/?login_error=no_id_token", status_code=302)
        claims = validate_microsoft_id_token(id_tok)
        oid = claims.get("oid") or claims.get("sub") or ""
        if not oid:
            return RedirectResponse(url=f"{base}/?login_error=no_oid", status_code=302)
        email = str(claims.get("email") or claims.get("preferred_username") or "")
        name = str(claims.get("name") or "")
        uid, role = user_upsert_oauth(str(oid), email, name)
        if user_is_disabled(uid):
            return RedirectResponse(url=f"{base}/?login_error=disabled", status_code=302)
        token = create_app_jwt_oauth(uid, email, role)
        resp = RedirectResponse(url=f"{base}/", status_code=302)
        resp.delete_cookie(MS_OAUTH_STATE_COOKIE, path="/")
        attach_auth_cookie(resp, token)
        return resp
    except Exception as e:
        msg = urllib.parse.quote(str(e)[:220])
        return RedirectResponse(url=f"{base}/?login_error={msg}", status_code=302)


def _require_admin(request: Request) -> Dict[str, Any]:
    cfg = get_comfyui_config()
    if not app_auth_enabled(cfg):
        raise HTTPException(status_code=403, detail="Authentication is not enabled")
    token = extract_token_from_request(request)
    payload = verify_token(token) if token else None
    if not payload or not token_payload_allowed(payload, cfg):
        raise HTTPException(status_code=401, detail="Authentication required")
    if not is_admin_payload(payload, cfg):
        raise HTTPException(status_code=403, detail="Admin required")
    return payload


@app.get("/api/users")
async def api_list_users(request: Request):
    _require_admin(request)
    return {"users": list_users_db()}


@app.patch("/api/users/{user_id}")
async def api_patch_user(request: Request, user_id: str, body: UserPatchPayload):
    admin_payload = _require_admin(request)
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    if data.get("disabled") or data.get("role") == "user":
        if admin_payload.get("typ") == "oauth" and user_id == admin_payload.get("sub"):
            if _count_active_admins() <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot demote or disable the last admin",
                )

    try:
        updated = update_user_db(
            user_id,
            role=data.get("role"),
            disabled=data.get("disabled"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": updated}


# ─── Config endpoints (ComfyUI connection + auth) ────────────────────────────

@app.get("/api/config")
async def api_get_config():
    cfg = get_comfyui_config()
    url = get_comfyui_url()
    auth_enabled = app_auth_enabled(cfg)
    safe_cfg = {**cfg, "comfyui_url": url, "auth_enabled": auth_enabled}
    if safe_cfg.get("auth_pass"):
        safe_cfg["auth_pass"] = _CONFIG_SECRET_PLACEHOLDER
    if safe_cfg.get("openai_api_key"):
        safe_cfg["openai_api_key"] = _CONFIG_SECRET_PLACEHOLDER
    safe_cfg.pop("jwt_secret", None)
    safe_cfg.pop("civitai_nsfw_level", None)
    safe_cfg["content_filter"] = get_content_filter_info()
    safe_cfg["llm_filter"] = get_llm_filter_info(cfg)
    return safe_cfg


@app.get("/api/content-filter")
async def api_content_filter():
    return get_content_filter_info()


@app.post("/api/config")
async def api_save_config(payload: ConfigPayload):
    old_cfg = get_comfyui_config()
    was_auth_enabled = app_auth_enabled(old_cfg)

    data: Dict[str, str] = {}
    for field, val in payload.model_dump(exclude_none=True).items():
        if field == "auth_pass":
            if val == _CONFIG_SECRET_PLACEHOLDER:
                continue
            if val:
                data[field] = hash_password(val)
            else:
                data[field] = ""
        elif field == "openai_api_key":
            if val == _CONFIG_SECRET_PLACEHOLDER:
                continue
            data[field] = str(val)
        elif field == "llm_content_filter":
            v = str(val).lower()
            data[field] = "true" if v in ("true", "1", "yes") else "false"
        else:
            data[field] = str(val)
    if data:
        if _llm_filter_mandatory():
            data["llm_content_filter"] = "true"
        update_comfyui_config(data)

    cfg = get_comfyui_config()
    is_auth_enabled = app_auth_enabled(cfg)
    auth_activated = is_auth_enabled and not was_auth_enabled

    url = get_comfyui_url()
    response: Dict[str, Any] = {
        **cfg,
        "comfyui_url": url,
        "auth_enabled": is_auth_enabled,
    }
    if response.get("auth_pass"):
        response["auth_pass"] = _CONFIG_SECRET_PLACEHOLDER
    if response.get("openai_api_key"):
        response["openai_api_key"] = _CONFIG_SECRET_PLACEHOLDER
    response.pop("jwt_secret", None)

    if auth_activated:
        tok = create_app_jwt_legacy(cfg.get("auth_user", ""))
        response["token"] = tok
        response["auth_activated"] = True

    response["llm_filter"] = get_llm_filter_info(cfg)

    if auth_activated and response.get("token"):
        jr = JSONResponse(content=response)
        attach_auth_cookie(jr, response["token"])
        return jr
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


LLM_ENHANCE_BASE = (
    "You rewrite the user's idea into one detailed prompt entirely in English for AI image or video generation "
    "(Stable Diffusion, Wan, Chinese video models, etc.). "
    "If the input is in any non-English language (Spanish, Chinese, Japanese, Korean, etc.), "
    "translate the full result to clear, natural English. "
    "Add concrete visual detail: subject, style, lighting, composition, colors, lens or camera when relevant. "
    "Keep existing <lora:...> style tags meaningful; you may reorder them. "
    "Reply with ONLY the improved prompt, no quotes, markdown, or preamble."
)

LLM_PROMPT_FILTER_SYSTEM = (
    "You sanitize text-to-image and text-to-video prompts for general-audience APIs. "
    "ONLY task: if the prompt describes sexual content, graphic violence, hate, illegal acts, or other material "
    "unsuitable for PG-13-style APIs, replace those fragments with safe equivalents (suggestive not explicit, "
    "stylized action not gore) while preserving scene, composition, and mood. "
    "If nothing needs changing, return the prompt unchanged. "
    "Do not add creative detail, do not translate unless required for the replacement. "
    "Preserve the same language as the input. "
    "Reply with ONLY the resulting prompt text, no quotes, markdown, or preamble."
)


async def _openai_chat(
    cfg: Dict[str, str],
    *,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
    timeout: float = 120.0,
) -> str:
    api_key = (cfg.get("openai_api_key") or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Falta API key de OpenAI; configúrala en Ajustes.",
        )
    base = (cfg.get("openai_api_base") or "https://api.openai.com/v1").strip().rstrip("/")
    model = (cfg.get("openai_model") or "gpt-4o-mini").strip()
    max_tok = min(max(max_tokens, 32), 4096)
    temp = min(max(temperature, 0.0), 2.0)
    url = f"{base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    org = (cfg.get("openai_organization") or "").strip()
    if org:
        headers["OpenAI-Organization"] = org
    oa_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temp,
        "max_tokens": max_tok,
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=oa_payload, headers=headers, timeout=timeout)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    if resp.status_code != 200:
        try:
            err = resp.json()
            detail = err.get("error", {}).get("message", resp.text[:400])
        except Exception:
            detail = resp.text[:400]
        raise HTTPException(
            status_code=502 if resp.status_code >= 500 else 400,
            detail=detail or f"HTTP {resp.status_code}",
        )

    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise HTTPException(status_code=502, detail="Respuesta vacía del modelo")
    content = (choices[0].get("message") or {}).get("content") or ""
    return content.strip()


async def _maybe_apply_llm_prompt_filter(cfg: Dict[str, str], text: str) -> str:
    """Paso interno antes de ComfyUI: reescribe el prompt positivo si el filtro está activo."""
    raw = text if text is not None else ""
    t = raw.strip()
    if not t:
        return raw
    if not _llm_prompt_filter_effective(cfg):
        return raw
    try:
        mt = int(cfg.get("llm_max_tokens") or "512")
    except ValueError:
        mt = 512
    mt = min(max(mt, 32), 1024)
    out = await _openai_chat(
        cfg,
        system=LLM_PROMPT_FILTER_SYSTEM.strip(),
        user=t,
        max_tokens=mt,
        temperature=0.2,
        timeout=90.0,
    )
    return out if out else raw


@app.post("/api/llm/test")
async def api_llm_test(payload: LLMTestPayload = LLMTestPayload()):
    cfg = get_comfyui_config()
    base = (payload.openai_api_base or cfg.get("openai_api_base") or "https://api.openai.com/v1").strip().rstrip("/")
    key = payload.openai_api_key
    if key is None or key == _CONFIG_SECRET_PLACEHOLDER:
        key = cfg.get("openai_api_key", "")
    key = (key or "").strip()
    if not key:
        return {"status": "error", "message": "Falta API key de OpenAI"}

    headers = {"Authorization": f"Bearer {key}"}
    org = payload.openai_organization if payload.openai_organization is not None else cfg.get("openai_organization", "")
    org = (org or "").strip()
    if org:
        headers["OpenAI-Organization"] = org

    url = f"{base}/models"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=20.0)
    except Exception as e:
        return {"status": "error", "message": str(e)}

    if resp.status_code == 200:
        return {"status": "ok", "message": "Conexión OpenAI correcta"}
    try:
        body = resp.json()
        msg = body.get("error", {}).get("message", resp.text[:300])
    except Exception:
        msg = resp.text[:300]
    return {"status": "error", "message": f"HTTP {resp.status_code}: {msg}"}


@app.post("/api/prompt/enhance")
async def api_prompt_enhance(body: PromptEnhanceRequest):
    text = (body.prompt or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Prompt vacío")

    cfg = get_comfyui_config()
    api_key = (cfg.get("openai_api_key") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="Configura la API key de OpenAI en Ajustes")

    try:
        temp = float(cfg.get("llm_temperature") or "0.7")
    except ValueError:
        temp = 0.7
    try:
        max_tok = int(cfg.get("llm_max_tokens") or "512")
    except ValueError:
        max_tok = 512
    max_tok = min(max(max_tok, 32), 4096)
    temp = min(max(temp, 0.0), 2.0)

    content = await _openai_chat(
        cfg,
        system=LLM_ENHANCE_BASE.strip(),
        user=text,
        max_tokens=max_tok,
        temperature=temp,
        timeout=120.0,
    )
    if not content:
        raise HTTPException(status_code=502, detail="El modelo no devolvió texto")
    return {"prompt": content}


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
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT filename, type FROM gallery WHERE id = ?", (img_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")
    filepath = GALLERY_DIR / row["filename"]
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Image file missing")
    if row["type"] == "video":
        ext = filepath.suffix.lower()
        media_map = {".webm": "video/webm", ".webp": "image/webp", ".gif": "image/gif", ".mp4": "video/mp4"}
        media_type = media_map.get(ext, "application/octet-stream")
    else:
        media_type = "image/png"
    return FileResponse(str(filepath), media_type=media_type)


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
    item_type = data.get("type", "image")
    result = {
        "id": data.get("id", ""),
        "url": f"/api/gallery/{img_id}/image",
        "type": item_type,
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
    if item_type == "video":
        result["length"] = data.get("length", 0)
        result["fps"] = data.get("fps", 0)
        result["meta"]["length"] = data.get("length", 0)
        result["meta"]["fps"] = data.get("fps", 0)
    return result


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
    Lista modelos disponibles, filtrando los ocultos via architectures.json.
    """
    comfy_url = get_comfyui_url()
    arch_mgr = get_arch_manager()

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{comfy_url}/api/kas/models",
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", {})

                checkpoints = [
                    {"name": m["filename"], "type": "checkpoint", **m}
                    for m in models.get("checkpoints", [])
                    if not arch_mgr.is_hidden_from(m["filename"], "image_generation")
                ]
                diffusion_models = [
                    {"name": m["filename"], "type": "diffusion_model", **m}
                    for m in models.get("diffusion_models", [])
                    if not arch_mgr.is_hidden_from(m["filename"], "image_generation")
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
                    "diffusion_models": diffusion_models,
                    "loras": loras,
                    "controlnets": controlnets,
                    "via_plugin": True,
                }
    except Exception as e:
        print(f"[models] Plugin no disponible ({e}), usando fallback")

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

# Carpetas cuyos archivos pueden aparecer en el selector principal de imagen
FAVORITE_MODEL_FOLDERS = frozenset({"checkpoints", "diffusion_models"})


def _load_model_favorites_map() -> Dict[tuple, Dict[str, Any]]:
    out: Dict[tuple, Dict[str, Any]] = {}
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        for r in conn.execute("SELECT folder, filename, label, sort_order FROM model_favorites"):
            out[(r["folder"], r["filename"])] = {
                "label": r["label"] or "",
                "sort_order": int(r["sort_order"] or 0),
            }
        conn.close()
    except Exception:
        pass
    return out


def _db_list_model_favorites() -> List[Dict[str, Any]]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT folder, filename, label, sort_order FROM model_favorites ORDER BY sort_order, filename"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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

    fav_map = _load_model_favorites_map()

    # Obtener modelos del plugin KAS
    all_models: Dict[str, list] = {}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{comfy_url}/api/kas/models", timeout=15.0)
            if resp.status_code == 200:
                all_models = resp.json().get("models", {})
    except Exception as e:
        return {"error": f"No se pudo conectar al plugin KAS: {e}", "categories": []}

    arch_mgr = get_arch_manager()

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

                arch_id = arch_mgr.detect(fname)
                arch_label = arch_mgr.architectures.get(arch_id, {}).get("label", arch_id)
                override = arch_mgr.get_override(fname)

                fav = fav_map.get((folder_name, fname))
                item = {
                    "filename": fname,
                    "folder": folder_name,
                    "size_bytes": size,
                    "base_model": base_model,
                    "architecture": arch_id,
                    "architecture_label": arch_label,
                    "has_override": override is not None,
                    "from_civitai": civitai_info is not None,
                    "civitai_name": civitai_info["name"] if civitai_info else None,
                    "civitai_model_id": civitai_info["civitai_model_id"] if civitai_info else None,
                    "is_favorite": fav is not None,
                    "favorite_label": fav["label"] if fav else None,
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


@app.get("/api/model-favorites")
async def api_list_model_favorites():
    return {"favorites": _db_list_model_favorites()}


@app.put("/api/model-favorites")
async def api_upsert_model_favorite(payload: ModelFavoritePayload):
    folder = (payload.folder or "").strip()
    filename = (payload.filename or "").strip()
    if folder not in FAVORITE_MODEL_FOLDERS:
        raise HTTPException(status_code=400, detail="Carpeta no permitida para favoritos")
    if not filename:
        raise HTTPException(status_code=400, detail="filename requerido")
    label = (payload.label or "").strip()[:200]
    conn = sqlite3.connect(str(DB_PATH))
    exists = conn.execute(
        "SELECT sort_order FROM model_favorites WHERE folder = ? AND filename = ?",
        (folder, filename),
    ).fetchone()
    if exists:
        if payload.sort_order is not None:
            conn.execute(
                "UPDATE model_favorites SET label = ?, sort_order = ? WHERE folder = ? AND filename = ?",
                (label, int(payload.sort_order), folder, filename),
            )
        else:
            conn.execute(
                "UPDATE model_favorites SET label = ? WHERE folder = ? AND filename = ?",
                (label, folder, filename),
            )
    else:
        row = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM model_favorites").fetchone()
        so = int(payload.sort_order) if payload.sort_order is not None else int(row[0])
        conn.execute(
            "INSERT INTO model_favorites (folder, filename, label, sort_order) VALUES (?, ?, ?, ?)",
            (folder, filename, label, so),
        )
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.delete("/api/model-favorites/{folder}/{filename:path}")
async def api_delete_model_favorite(folder: str, filename: str):
    if folder not in FAVORITE_MODEL_FOLDERS:
        raise HTTPException(status_code=400, detail="Carpeta no permitida")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM model_favorites WHERE folder = ? AND filename = ?", (folder, filename))
    conn.commit()
    conn.close()
    return {"status": "ok"}


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


# ─── Architecture Config Endpoints ────────────────────────────────────────────

@app.get("/api/architectures")
async def get_architectures():
    """List all architecture definitions from architectures.json."""
    arch_mgr = get_arch_manager()
    return {"architectures": arch_mgr.list_architectures()}


@app.get("/api/architectures/detect/{filename:path}")
async def detect_architecture(filename: str):
    """Detect architecture for a given model filename."""
    arch_mgr = get_arch_manager()
    arch_id = arch_mgr.detect(filename)
    config = arch_mgr.resolve(filename)
    return {"filename": filename, "architecture": arch_id, "config": config}


@app.get("/api/model-overrides")
async def list_model_overrides():
    """List all model overrides."""
    arch_mgr = get_arch_manager()
    return {"overrides": arch_mgr.list_overrides()}


@app.get("/api/model-overrides/{filename:path}")
async def get_model_override(filename: str):
    """Get override for a specific model."""
    arch_mgr = get_arch_manager()
    override = arch_mgr.get_override(filename)
    if override is None:
        return {"filename": filename, "override": None}
    return {"filename": filename, "override": override}


@app.post("/api/model-overrides/{filename:path}")
async def save_model_override(filename: str, request: Request):
    """Save/update override for a model."""
    data = await request.json()
    arch_mgr = get_arch_manager()
    arch_mgr.save_override(filename, data)
    return {"status": "ok", "filename": filename}


@app.delete("/api/model-overrides/{filename:path}")
async def delete_model_override(filename: str):
    """Delete override for a model."""
    arch_mgr = get_arch_manager()
    deleted = arch_mgr.delete_override(filename)
    return {"status": "ok", "deleted": deleted}


@app.post("/api/architectures/reload")
async def reload_architectures():
    """Reload architectures.json from disk."""
    arch_mgr = get_arch_manager()
    arch_mgr.reload()
    return {"status": "ok", "count": len(arch_mgr.architectures)}


# ─── LoRA Search ──────────────────────────────────────────────────────────────

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


@app.get("/api/video-models")
async def get_video_models():
    """Lista modelos disponibles para generación de vídeo (capabilities: txt2video)."""
    comfy_url = get_comfyui_url()
    arch_mgr = get_arch_manager()
    video_models = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{comfy_url}/api/kas/models?folder=diffusion_models")
            if resp.status_code == 200:
                models = resp.json().get("models", {}).get("diffusion_models", [])
                for m in models:
                    fname = m["filename"]
                    arch_config = arch_mgr.resolve(fname)
                    caps = arch_config.get("capabilities", [])
                    if "txt2video" in caps:
                        video_models.append({
                            "name": fname,
                            "filename": fname,
                            "size_bytes": m.get("size_bytes", 0),
                            "architecture": arch_config.get("_arch_id", ""),
                            "architecture_label": arch_config.get("label", ""),
                        })
    except Exception as e:
        print(f"[video-models] Error: {e}")
    return {"models": video_models}


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
    cfg = get_comfyui_config()
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

        prompt_text = clean_prompt if lora_tags else request.prompt
        prompt_text = await _maybe_apply_llm_prompt_filter(cfg, prompt_text)
        model_name = request.checkpoint or "SDXL.safetensors"

        arch_mgr = get_arch_manager()
        arch_config = arch_mgr.resolve(model_name)
        arch_id = arch_config.get("_arch_id", "sd15")

        print(f"[txt2img] model={model_name}, arch={arch_id}, loader={arch_config.get('loader')}")
        print(f"[txt2img] size={request.width}x{request.height}, steps={request.steps}, cfg={request.cfg_scale}, sampler={request.sampler}")

        workflow = build_txt2img_workflow(
            arch_config=arch_config,
            prompt=prompt_text,
            negative_prompt=request.negative_prompt or "",
            model_name=model_name,
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
        print(f"[txt2img] Workflow built: arch={arch_id}, nodes={list(workflow.keys())}, seed={actual_seed}")

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
                "prompt": prompt_text,
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
                            progress = 50
                            try:
                                prog_resp = await client.get(f"{comfy_url}/api/kas/progress", timeout=3.0)
                                if prog_resp.status_code == 200:
                                    prog_data = prog_resp.json()
                                    if prog_data.get("prompt_id") == job_id:
                                        current = prog_data.get("current_step", 0)
                                        total = prog_data.get("total_steps", 1)
                                        if total > 0:
                                            progress = max(5, min(95, int(current / total * 100)))
                            except Exception:
                                pass
                            return {
                                "job_id": job_id,
                                "status": "processing",
                                "progress": progress,
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
                    video_files: List[Dict[str, str]] = []

                    ANIMATED_EXTENSIONS = (".webp", ".gif", ".apng")

                    for node_id, node_output in outputs.items():
                        if not isinstance(node_output, dict):
                            continue
                        images = node_output.get("images", [])
                        for img in images:
                            if not isinstance(img, dict):
                                continue

                            # Format A: KAS plugin (source=http, id=kas_xxx)
                            if img.get("source") == "http":
                                img_id = img.get("id")
                                if img_id and img_id.startswith("kas_"):
                                    video_files.append({"type": "kas", "id": img_id})
                                elif img_id:
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

                            # Format B: ComfyUI native (type=output, filename=xxx.webp)
                            elif img.get("type") == "output":
                                fname = img.get("filename", "")
                                if any(fname.lower().endswith(ext) for ext in ANIMATED_EXTENSIONS):
                                    video_files.append({
                                        "type": "comfyui",
                                        "filename": fname,
                                        "subfolder": img.get("subfolder", ""),
                                    })

                    # Manejar videos / animated outputs
                    if video_files:
                        gallery_video_ids = []
                        if job_id not in _saved_jobs:
                            _saved_jobs.add(job_id)
                            meta = _job_meta.pop(job_id, {})
                            for vf in video_files:
                                try:
                                    if vf["type"] == "kas":
                                        vid_resp = await client.get(
                                            f"{comfy_url}/api/kas/video/{vf['id']}",
                                            timeout=120.0,
                                        )
                                    else:
                                        params = {
                                            "filename": vf["filename"],
                                            "subfolder": vf.get("subfolder", ""),
                                            "type": "output",
                                        }
                                        vid_resp = await client.get(
                                            f"{comfy_url}/view",
                                            params=params,
                                            timeout=120.0,
                                        )
                                    if vid_resp.status_code == 200:
                                        entry = save_gallery_video(
                                            video_bytes=vid_resp.content,
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
                                            length=meta.get("length", 0),
                                            fps=meta.get("fps", 0.0),
                                        )
                                        gallery_video_ids.append(entry["id"])
                                    else:
                                        print(f"[video] Failed to download video: status={vid_resp.status_code}")
                                except Exception as e:
                                    print(f"[video] Failed to save video to gallery: {e}")
                            print(f"Video job completed: saved {len(gallery_video_ids)} to gallery")

                        return {
                            "job_id": job_id,
                            "status": "completed",
                            "gallery_video_ids": gallery_video_ids,
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
    """Genera video usando Wan 2.x T2V via workflow con soporte LoRA."""
    comfy_url = get_comfyui_url()
    cfg = get_comfyui_config()
    try:
        actual_seed = request.seed
        if actual_seed < 0:
            actual_seed = random.randint(0, 2**32 - 1)

        VIDEO_UNET_DEFAULT = "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors"
        available_unets: list[str] = []
        available_loras: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{comfy_url}/api/kas/models?folder=diffusion_models")
                if r.status_code == 200:
                    available_unets = [
                        m["filename"] for m in r.json().get("models", {}).get("diffusion_models", [])
                    ]
                r2 = await c.get(f"{comfy_url}/api/kas/models?folder=loras")
                if r2.status_code == 200:
                    available_loras = [
                        m["filename"] for m in r2.json().get("models", {}).get("loras", [])
                    ]
        except Exception:
            pass

        req_checkpoint = request.checkpoint or ""
        video_checkpoint = req_checkpoint if req_checkpoint in available_unets else VIDEO_UNET_DEFAULT

        # Parse LoRA tags from prompt
        clean_prompt, lora_tags = parse_lora_tags(request.prompt)
        resolved_loras = None
        if lora_tags:
            resolved_loras = []
            missing_loras = []
            for name, strength_model, strength_clip in lora_tags:
                filename = resolve_lora_filename(name, available_loras)
                if filename:
                    resolved_loras.append((filename, strength_model, strength_clip))
                    print(f"[txt2video] LoRA resuelto: {name} -> {filename}")
                else:
                    print(f"[txt2video] LoRA no encontrado: {name}")
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

        prompt_text = clean_prompt if lora_tags else request.prompt
        prompt_text = await _maybe_apply_llm_prompt_filter(cfg, prompt_text)

        arch_mgr = get_arch_manager()
        video_arch_config = arch_mgr.resolve(video_checkpoint)

        low_unet: Optional[str] = None
        if "high_noise" in video_checkpoint.lower():
            cand = video_checkpoint.replace("high_noise", "low_noise")
            if cand in available_unets:
                low_unet = cand

        workflow = build_txt2video_workflow(
            arch_config=video_arch_config,
            prompt=prompt_text,
            negative_prompt=request.negative_prompt or "",
            model_name=video_checkpoint,
            low_noise_model=low_unet,
            vae_override=request.vae or "",
            clip_override=request.clip or "",
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
            loras=resolved_loras,
        )
        print(
            f"[txt2video] arch={video_arch_config.get('_arch_id')}, unet={video_checkpoint}, "
            f"dual={low_unet is not None}, low={low_unet or '-'}, seed={actual_seed}, length={request.length}, loras={len(resolved_loras or [])}"
        )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{comfy_url}/prompt",
                json={"prompt": workflow},
                timeout=15.0,
            )
            if response.status_code != 200:
                print(f"[txt2video] ComfyUI rejected: {response.text[:500]}")
                raise HTTPException(
                    status_code=500, detail=f"ComfyUI error: {response.text}"
                )

            result = response.json()
            prompt_id = result.get("prompt_id")

            _job_meta[prompt_id] = {
                "prompt": prompt_text,
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

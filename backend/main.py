"""
Krita AI Studio Backend - FastAPI
Replica EXACTAMENTE el comportamiento de krita-ai-diffusion
Usa ETN_SaveImageCache (no PreviewImage) + /api/etn/image/{id}
SQLite para persistir configuración del usuario y conexión ComfyUI
"""

import os
import base64
import random
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import httpx

from workflow_krita import create_txt2img_workflow_krita

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
DB_PATH = DATA_DIR / "krita_ai.db"


# ─── SQLite helpers ───────────────────────────────────────────────────────────

def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
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


class GenerationResponse(BaseModel):
    job_id: str
    status: str
    images: Optional[List[str]] = None
    error: Optional[str] = None


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


# ─── App ──────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    url = get_comfyui_url()
    print(f"Krita AI Studio Backend iniciado")
    print(f"ComfyUI URL: {url}")
    print(f"Database: {DB_PATH}")
    yield
    print("Cerrando Krita AI Studio Backend")


app = FastAPI(
    title="Krita AI Studio API",
    version="2.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Config endpoints (ComfyUI connection) ───────────────────────────────────

@app.get("/api/config")
async def api_get_config():
    cfg = get_comfyui_config()
    url = get_comfyui_url()
    return {**cfg, "comfyui_url": url}


@app.post("/api/config")
async def api_save_config(payload: ConfigPayload):
    data: Dict[str, str] = {}
    for field, val in payload.model_dump(exclude_none=True).items():
        data[field] = str(val)
    if data:
        update_comfyui_config(data)
    cfg = get_comfyui_config()
    url = get_comfyui_url()
    return {**cfg, "comfyui_url": url}


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
    comfy_url = get_comfyui_url()
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
                }
    except Exception as e:
        print(f"Error fetching models: {e}")

    return {
        "checkpoints": [],
        "loras": [],
        "controlnets": [],
        "fallback": True,
    }


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

        workflow = create_txt2img_workflow_krita(
            prompt=request.prompt,
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
            return GenerationResponse(job_id=prompt_id, status="queued", images=None)

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error en txt2img: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Job polling ──────────────────────────────────────────────────────────────

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
                                    img_resp = await client.get(
                                        f"{comfy_url}/api/etn/image/{img_id}",
                                        timeout=60.0,
                                    )
                                    if img_resp.status_code == 200:
                                        img_b64 = base64.b64encode(
                                            img_resp.content
                                        ).decode("utf-8")
                                        images_base64.append(img_b64)

                    if images_base64:
                        return {
                            "job_id": job_id,
                            "status": "completed",
                            "images": images_base64,
                            "progress": 100,
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

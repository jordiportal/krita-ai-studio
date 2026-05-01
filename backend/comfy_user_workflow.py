"""
Carga workflows API guardados en ComfyUI: plugin KAS y/o API nativa (/userdata?dir=workflows).
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx

from comfy_ui_workflow_convert import ensure_api_prompt_format

# Longitud máxima razonable (ComfyUI guarda nombres con espacios, paréntesis, +, etc.)
_MAX_WORKFLOW_PATH_LEN = 2048


def is_safe_workflow_id(name: str) -> bool:
    """
    Nombre de archivo .json tal como lo devuelve Comfy (puede incluir espacios, paréntesis, +, etc.)
    o ruta relativa tipo subcarpeta/Mi flujo (v1).json.
    Solo bloquea path traversal y bytes de control.
    """
    if not name or len(name) > _MAX_WORKFLOW_PATH_LEN:
        return False
    if "\x00" in name or "\r" in name:
        return False
    n = name.strip().replace("\\", "/")
    if n.startswith("/"):
        return False
    parts = [p for p in n.split("/") if p != ""]
    if not parts:
        return False
    for p in parts:
        if p in (".", ".."):
            return False
    if not parts[-1].endswith(".json"):
        return False
    return True


def is_safe_workflow_filename(name: str) -> bool:
    """Alias: mismo criterio que is_safe_workflow_id (antes solo plano)."""
    return is_safe_workflow_id(name)


def _unwrap_prompt(data: Any) -> Dict[str, Any]:
    """Acepta dict API {node_id: {...}} o envoltorio {'prompt': {...}}."""
    if isinstance(data, dict):
        if "prompt" in data and isinstance(data["prompt"], dict):
            inner = data["prompt"]
            if inner and all(isinstance(k, str) for k in inner.keys()):
                return inner
        if data and all(isinstance(k, str) for k in data.keys()):
            first = next(iter(data.values()))
            if isinstance(first, dict) and "class_type" in first:
                return data
    raise ValueError("Formato de workflow no reconocido")


def _parse_userdata_workflow_list(data: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(data, list):
        return out
    for item in data:
        rel = ""
        size = 0
        if isinstance(item, str):
            rel = item.replace("\\", "/").strip()
        elif isinstance(item, dict):
            rel = str(item.get("path", "")).replace("\\", "/").strip()
            size = int(item.get("size", 0) or 0)
        if not rel or not rel.endswith(".json"):
            continue
        if not is_safe_workflow_id(rel):
            continue
        out.append({"filename": rel, "size_bytes": size})
    return out


async def _list_userdata_workflows(client: httpx.AsyncClient, comfy_url: str) -> List[Dict[str, Any]]:
    """Lista JSON bajo el directorio de usuario 'workflows' (API estándar ComfyUI)."""
    base = comfy_url.rstrip("/")
    urls = [
        f"{base}/api/userdata?dir=workflows&full_info=true",
        f"{base}/api/userdata?dir=workflows",
        f"{base}/userdata?dir=workflows&full_info=true",
        f"{base}/userdata?dir=workflows",
    ]
    for url in urls:
        try:
            r = await client.get(url)
            if r.status_code != 200:
                continue
            parsed = _parse_userdata_workflow_list(r.json())
            if parsed:
                return parsed
        except Exception:
            continue
    return []


async def fetch_workflow_file_list(comfy_url: str) -> List[Dict[str, Any]]:
    """Unión: plugin KAS (si existe) + /api/userdata?dir=workflows de ComfyUI."""
    merged: Dict[str, Dict[str, Any]] = {}
    base = comfy_url.rstrip("/")
    kas_urls = [
        f"{base}/api/kas/workflows",
        f"{base}/api/kas/models?folder=workflows",
    ]
    async with httpx.AsyncClient(timeout=15.0) as client:
        for url in kas_urls:
            try:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                data = r.json()
                if isinstance(data, list):
                    for item in data:
                        fn = (item.get("filename") if isinstance(item, dict) else str(item)) or ""
                        fn = str(fn).strip().replace("\\", "/")
                        if not is_safe_workflow_id(fn):
                            continue
                        sz = (
                            int(item.get("size_bytes", 0) or 0)
                            if isinstance(item, dict)
                            else 0
                        )
                        merged.setdefault(fn, {"filename": fn, "size_bytes": sz})
                elif isinstance(data, dict):
                    if isinstance(data.get("workflows"), list):
                        raw = data["workflows"]
                    elif isinstance(data.get("models"), dict):
                        raw = data["models"].get("workflows") or []
                    else:
                        raw = []
                    for item in raw:
                        if not isinstance(item, dict):
                            continue
                        fn = str(item.get("filename", "")).strip().replace("\\", "/")
                        if not is_safe_workflow_id(fn):
                            continue
                        sz = int(item.get("size_bytes", 0) or 0)
                        merged.setdefault(fn, {"filename": fn, "size_bytes": sz})
            except Exception:
                continue

        try:
            for it in await _list_userdata_workflows(client, comfy_url):
                fn = it["filename"]
                if fn not in merged or int(merged[fn].get("size_bytes", 0) or 0) == 0:
                    merged[fn] = dict(it)
        except Exception:
            pass

    return sorted(merged.values(), key=lambda x: str(x["filename"]).lower())


def _userdata_raw_urls(comfy_base: str, filename: str) -> List[str]:
    rel = filename.strip().replace("\\", "/")
    storage = rel if rel.startswith("workflows/") else f"workflows/{rel}"
    enc = quote(storage, safe="")
    return [
        f"{comfy_base}/api/userdata/{enc}",
        f"{comfy_base}/userdata/{enc}",
    ]


async def fetch_workflow_json(comfy_url: str, filename: str) -> Dict[str, Any]:
    if not is_safe_workflow_id(filename):
        raise ValueError("Nombre de workflow no permitido")
    base = comfy_url.rstrip("/")
    urls = _userdata_raw_urls(base, filename)
    urls.extend(
        [
            f"{base}/api/kas/workflows/{quote(filename, safe='')}",
            f"{base}/api/kas/workflow/{quote(filename, safe='')}",
            f"{base}/api/kas/workflow-file/{quote(filename, safe='')}",
        ]
    )
    async with httpx.AsyncClient(timeout=60.0) as client:
        last_err = ""
        for url in urls:
            try:
                r = await client.get(url)
                if r.status_code != 200:
                    last_err = f"{r.status_code}: {r.text[:200]}"
                    continue
                try:
                    data = r.json()
                except json.JSONDecodeError:
                    last_err = "JSON inválido"
                    continue
                try:
                    api_prompt = await ensure_api_prompt_format(comfy_url, data, client)
                except ValueError as ve:
                    raise RuntimeError(str(ve)) from ve
                return _unwrap_prompt(api_prompt)
            except RuntimeError:
                raise
            except Exception as e:
                last_err = str(e)
                continue
    raise RuntimeError(last_err or "No se pudo descargar el workflow")


def _natural_node_id(nid: str) -> Tuple[int, str]:
    if nid.isdigit():
        return (int(nid), nid)
    return (10**9, nid)


def inject_into_api_workflow(
    workflow: Dict[str, Any],
    *,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    seed: Optional[int] = None,
    length: Optional[int] = None,
    fps: Optional[float] = None,
) -> Dict[str, Any]:
    w = copy.deepcopy(workflow)
    clip_nodes: List[tuple] = []
    prompt_injected = False

    for nid, node in w.items():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type") or node.get("type") or "")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue

        if "CLIPTextEncode" in ct and "text" in inputs:
            clip_nodes.append((nid, node))

        if "prompt" in inputs and isinstance(inputs["prompt"], str):
            inputs["prompt"] = prompt
            prompt_injected = True
        if "negative_prompt" in inputs and isinstance(inputs["negative_prompt"], str):
            inputs["negative_prompt"] = negative_prompt or ""

        if "width" in inputs and "height" in inputs:
            latentish = (
                "EmptyLatent" in ct
                or "EmptySD3Latent" in ct
                or "WanImageToVideo" in ct
                or (length is not None and "length" in inputs and "Wan" in ct)
            )
            if latentish:
                try:
                    inputs["width"] = int(width)
                    inputs["height"] = int(height)
                except (TypeError, ValueError):
                    pass
        if seed is not None:
            if "noise_seed" in inputs:
                try:
                    inputs["noise_seed"] = int(seed)
                except (TypeError, ValueError):
                    pass
            if "seed" in inputs and isinstance(inputs.get("seed"), (int, float)):
                try:
                    inputs["seed"] = int(seed)
                except (TypeError, ValueError):
                    pass
        if length is not None and "length" in inputs:
            try:
                inputs["length"] = int(length)
            except (TypeError, ValueError):
                pass
        if fps is not None and "fps" in inputs:
            try:
                inputs["fps"] = float(fps)
            except (TypeError, ValueError):
                pass

    if not prompt_injected:
        clip_nodes.sort(key=lambda x: _natural_node_id(str(x[0])))
        if len(clip_nodes) >= 1:
            n0 = clip_nodes[0][1]
            if isinstance(n0.get("inputs"), dict):
                n0["inputs"]["text"] = prompt
        if len(clip_nodes) >= 2:
            n1 = clip_nodes[1][1]
            if isinstance(n1.get("inputs"), dict):
                n1["inputs"]["text"] = negative_prompt or ""
        elif len(clip_nodes) == 1 and negative_prompt:
            n0 = clip_nodes[0][1]
            if isinstance(n0.get("inputs"), dict):
                t = str(n0["inputs"].get("text", ""))
                if t.strip():
                    n0["inputs"]["text"] = f"{t}\n\n[negative]\n{negative_prompt}"
                else:
                    n0["inputs"]["text"] = prompt

    return w

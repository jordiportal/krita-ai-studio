"""
Convierte workflows guardados desde la UI de ComfyUI (nodes + links) al formato API de /prompt.
Basado en la lógica de krita-ai-diffusion (ComfyObjectInfo + _convert_ui_workflow).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

_control_after_generate = ["fixed", "increment", "decrement", "randomize"]


class ComfyObjectInfo:
    """Subconjunto de /object_info: solo lo necesario para mapear widgets → inputs."""

    def __init__(self, nodes: Dict[str, Any]):
        self.nodes = nodes

    def inputs(self, node_name: str, category: str = "") -> Optional[Dict[str, list]]:
        node = self.nodes.get(node_name)
        if node is None:
            return None
        inputs = node.get("input", {})
        if category:
            return inputs.get(category)
        result: Dict[str, list] = {}
        result.update(inputs.get("required", {}) or {})
        result.update(inputs.get("optional", {}) or {})
        return result


def looks_like_ui_workflow(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("nodes"), list) and isinstance(data.get("links"), list)


def looks_like_api_prompt(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    inner = data.get("prompt") if isinstance(data.get("prompt"), dict) else data
    if not isinstance(inner, dict) or not inner:
        return False
    if not all(isinstance(k, str) for k in inner.keys()):
        return False
    first = next(iter(inner.values()), None)
    return isinstance(first, dict) and "class_type" in first


def _find_link(links: List[Any], link_id: Any) -> Optional[List[Any]]:
    for x in links:
        if isinstance(x, (list, tuple)) and len(x) >= 3 and x[0] == link_id:
            return list(x)
        if isinstance(x, dict) and x.get("id") == link_id:
            return [
                x.get("id"),
                x.get("origin_id") or x.get("from"),
                x.get("origin_slot") if "origin_slot" in x else x.get("from_slot", 0),
            ]
    return None


def convert_ui_workflow_to_api_prompt(w: Dict[str, Any], node_inputs: ComfyObjectInfo) -> Dict[str, Any]:
    nodes = w.get("nodes")
    links = w.get("links")
    if not isinstance(nodes, list) or not isinstance(links, list):
        return w
    if not node_inputs.nodes:
        raise ValueError("object_info vacío: no se puede convertir el workflow de la UI")

    primitives: Dict[Any, Any] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("type") == "PrimitiveNode":
            wv = node.get("widgets_values") or []
            if wv:
                primitives[node["id"]] = wv[0]

    r: Dict[str, Dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = node.get("id")
        ntype = node.get("type")
        if ntype == "PrimitiveNode" or nid is None or not ntype:
            continue

        inputs: Dict[str, Any] = {}
        fields = node_inputs.inputs(str(ntype))
        if fields is None:
            raise ValueError(
                f"El workflow usa el nodo «{ntype}», que no aparece en object_info del ComfyUI conectado "
                f"(¿custom node no instalado en ese servidor?)"
            )

        node_inputs_list = node.get("inputs")
        if not isinstance(node_inputs_list, list):
            node_inputs_list = []
        connected: Dict[str, dict] = {}
        for conn in node_inputs_list:
            if isinstance(conn, dict) and conn.get("link") is not None:
                connected[conn.get("name", "")] = conn

        widget_count = 0
        wvals = node.get("widgets_values")
        if not isinstance(wvals, list):
            wvals = []

        for field_name, field in fields.items():
            if not isinstance(field, (list, tuple)) or len(field) < 1:
                continue
            field_type = field[0]
            if isinstance(field_type, list):
                field_type = "COMBO"

            is_widget_type = field_type in ("INT", "FLOAT", "BOOL", "STRING", "COMBO")

            if field_name in connected:
                conn = connected[field_name]
                link = _find_link(links, conn["link"])
                if link is None or len(link) < 3:
                    raise ValueError(
                        f"Nodo {ntype} (id={nid}): enlace {conn.get('link')} no encontrado en links[]"
                    )
                prim = primitives.get(link[1])
                if prim is not None:
                    inputs[field_name] = prim
                else:
                    inputs[field_name] = [str(link[1]), int(link[2])]
                continue

            if is_widget_type:
                if widget_count >= len(wvals):
                    raise ValueError(
                        f"Nodo {ntype} (id={nid}): faltan widgets_values para «{field_name}» "
                        f"(widget #{widget_count}). ¿Versión distinta de ComfyUI o nodo custom?"
                    )
                inputs[field_name] = wvals[widget_count]
                widget_count += 1
                field_opts = field[1] if len(field) > 1 and isinstance(field[1], dict) else {}
                has_control = "control_after_generate" in field_opts
                if has_control and len(wvals) > widget_count:
                    widget_count += 1
                elif len(wvals) > widget_count and wvals[widget_count] in _control_after_generate:
                    widget_count += 1
                if ntype == "ETN_Parameter" and widget_count >= len(wvals):
                    break

        r[str(nid)] = {"class_type": str(ntype), "inputs": inputs}

    return r


async def fetch_object_info(comfy_url: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    base = comfy_url.rstrip("/")
    for path in ("/api/object_info", "/object_info"):
        try:
            r = await client.get(f"{base}{path}", timeout=120.0)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    raise RuntimeError("No se pudo obtener /object_info desde ComfyUI (¿URL o auth incorrectos?)")


async def ensure_api_prompt_format(
    comfy_url: str,
    data: Any,
    client: httpx.AsyncClient,
) -> Dict[str, Any]:
    """
    Si `data` es un workflow de la UI (nodes+links), lo convierte usando object_info.
    Si ya es formato API, lo devuelve tal cual (dict de nodos).
    """
    if isinstance(data, list):
        raise ValueError("El JSON del archivo es una lista, no un workflow")
    if not isinstance(data, dict):
        raise ValueError("El archivo no es un JSON de objeto/dict")
    if looks_like_api_prompt(data):
        if "prompt" in data and isinstance(data["prompt"], dict):
            return dict(data["prompt"])
        return dict(data)
    if looks_like_ui_workflow(data):
        obj = await fetch_object_info(comfy_url, client)
        return convert_ui_workflow_to_api_prompt(data, ComfyObjectInfo(obj))
    raise ValueError(
        "Formato de workflow no reconocido: no es ni API ({id: {class_type, inputs}}) "
        "ni UI de ComfyUI ({nodes, links})."
    )

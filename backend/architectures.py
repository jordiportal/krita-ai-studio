"""
Model Architecture Configuration System.

Two-layer approach:
  Layer 1: architectures.json — static definitions for each model family
  Layer 2: model_overrides table in SQLite — per-model user overrides

Usage:
    from architectures import get_arch_manager
    mgr = get_arch_manager()
    config = mgr.resolve("z_image_turbo_bf16.safetensors")
    # config is a dict with all merged fields ready for workflow building
"""

import json
import sqlite3
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional


_ARCH_FILE = Path(__file__).parent / "architectures.json"
_DB_PATH = Path(os.getenv("DATA_DIR", "/app/data")) / "krita_ai.db"

FALLBACK_ARCH = "sd15"


class ArchManager:
    """Loads architectures.json, detects model families, merges SQLite overrides."""

    def __init__(self, arch_file: Path = _ARCH_FILE, db_path: Path = _DB_PATH):
        self._db_path = db_path
        self._archs: Dict[str, Dict[str, Any]] = {}
        self._sorted_keys: List[str] = []
        self._load(arch_file)

    def _load(self, arch_file: Path) -> None:
        with open(arch_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._archs = data.get("architectures", {})
        self._sorted_keys = sorted(
            self._archs.keys(),
            key=lambda k: self._archs[k].get("priority", 0),
            reverse=True,
        )

    def reload(self) -> None:
        self._load(_ARCH_FILE)

    @property
    def architectures(self) -> Dict[str, Dict[str, Any]]:
        return self._archs

    def list_architectures(self) -> List[Dict[str, Any]]:
        result = []
        for key in self._sorted_keys:
            arch = self._archs[key]
            result.append({"id": key, **arch})
        return result

    def detect(self, filename: str) -> str:
        """Auto-detect architecture from filename using patterns and priorities."""
        name = filename.lower()

        for key in self._sorted_keys:
            arch = self._archs[key]
            detection = arch.get("detection", [])
            exclude = arch.get("exclude", [])
            require = arch.get("require", [])

            if not detection:
                continue

            matched = any(pat in name for pat in detection)
            if not matched:
                continue

            excluded = any(pat in name for pat in exclude) if exclude else False
            if excluded:
                continue

            if require and not all(pat in name for pat in require):
                continue

            return key

        return FALLBACK_ARCH

    def get_override(self, filename: str) -> Optional[Dict[str, Any]]:
        """Fetch per-model override from SQLite, or None."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM model_overrides WHERE filename = ?", (filename,)
            ).fetchone()
            conn.close()
            if row is None:
                return None
            result = dict(row)
            for json_field in ("sampling", "clip"):
                if result.get(json_field):
                    try:
                        result[json_field] = json.loads(result[json_field])
                    except (json.JSONDecodeError, TypeError):
                        result[json_field] = {}
                else:
                    result[json_field] = {}
            return result
        except Exception:
            return None

    def resolve(self, filename: str) -> Dict[str, Any]:
        """
        Resolve the full config for a model file.
        Priority: SQLite override.architecture > auto-detect, then merge override fields.
        """
        override = self.get_override(filename)

        if override and override.get("architecture"):
            arch_key = override["architecture"]
        else:
            arch_key = self.detect(filename)

        base = deepcopy(self._archs.get(arch_key, self._archs.get(FALLBACK_ARCH, {})))
        base["_arch_id"] = arch_key

        if not override:
            return base

        if override.get("hidden"):
            base.setdefault("hidden_from", [])
            if "image_generation" not in base["hidden_from"]:
                base["hidden_from"].append("image_generation")

        if override.get("vae"):
            base["vae"] = override["vae"]

        override_sampling = override.get("sampling", {})
        if override_sampling:
            base_sampling = base.get("sampling", {})
            for k, v in override_sampling.items():
                if v is not None and v != "":
                    base_sampling[k] = v
            base["sampling"] = base_sampling

        override_clip = override.get("clip", {})
        if override_clip:
            base_clip = base.get("clip", {})
            for k, v in override_clip.items():
                if v is not None and v != "":
                    base_clip[k] = v
            base["clip"] = base_clip

        return base

    def is_hidden_from(self, filename: str, context: str = "image_generation") -> bool:
        """Check if a model should be hidden from a given context (e.g. image_generation)."""
        config = self.resolve(filename)
        hidden = config.get("hidden_from", [])
        return context in hidden

    def save_override(self, filename: str, data: Dict[str, Any]) -> None:
        """Upsert a model override in SQLite."""
        conn = sqlite3.connect(str(self._db_path))
        sampling_json = json.dumps(data.get("sampling", {}))
        clip_json = json.dumps(data.get("clip", {}))
        conn.execute(
            """INSERT INTO model_overrides (filename, architecture, sampling, clip, vae, hidden, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(filename) DO UPDATE SET
                 architecture = excluded.architecture,
                 sampling = excluded.sampling,
                 clip = excluded.clip,
                 vae = excluded.vae,
                 hidden = excluded.hidden,
                 notes = excluded.notes
            """,
            (
                filename,
                data.get("architecture"),
                sampling_json,
                clip_json,
                data.get("vae"),
                1 if data.get("hidden") else 0,
                data.get("notes", ""),
            ),
        )
        conn.commit()
        conn.close()

    def delete_override(self, filename: str) -> bool:
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.execute(
            "DELETE FROM model_overrides WHERE filename = ?", (filename,)
        )
        conn.commit()
        deleted = cursor.rowcount > 0
        conn.close()
        return deleted

    def list_overrides(self) -> List[Dict[str, Any]]:
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM model_overrides").fetchall()
            conn.close()
            results = []
            for row in rows:
                d = dict(row)
                for json_field in ("sampling", "clip"):
                    if d.get(json_field):
                        try:
                            d[json_field] = json.loads(d[json_field])
                        except (json.JSONDecodeError, TypeError):
                            d[json_field] = {}
                    else:
                        d[json_field] = {}
                results.append(d)
            return results
        except Exception:
            return []


_instance: Optional[ArchManager] = None


def get_arch_manager() -> ArchManager:
    global _instance
    if _instance is None:
        _instance = ArchManager()
    return _instance

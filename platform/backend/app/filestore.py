"""File storage — the configurable 'bucket' on the instance (local backend).

One storage root acts as a shared inbox/outbox: users drop files in, agents read
inputs and write generated files back, and the Files screen browses it. Everything is
confined to the root — no path can escape it (the key safety rule). The backend sits
behind one interface so an Azure Blob backend can be added later without touching
callers. Configuration is UI-driven (Governance -> File Storage) via governance settings.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .store import DATA_DIR

_DEFAULT = {
    "backend": "local",                         # local (Azure Blob later)
    "root_path": str(DATA_DIR / "file_storage"),
    "max_file_kb": 25_600,                       # 25 MB per file
    "allowed_ext": [],                           # [] = allow all; else whitelist e.g. ["csv","txt"]
}


def config() -> dict:
    from .governance import get_settings
    s = get_settings()
    fs = s.get("file_storage") or {}
    return {**_DEFAULT, **fs, "allowed_ext": fs.get("allowed_ext", _DEFAULT["allowed_ext"])}


def update_config(patch: dict) -> dict:
    from .governance import get_settings, update_settings
    cur = {**_DEFAULT, **(get_settings().get("file_storage") or {})}
    cur.update({k: v for k, v in patch.items() if k in _DEFAULT})
    update_settings({"file_storage": cur})
    _ensure_root()
    return config()


def root() -> Path:
    return Path(config()["root_path"]).resolve()


def _ensure_root() -> Path:
    r = root()
    (r / "shared").mkdir(parents=True, exist_ok=True)
    return r


class StorageError(Exception):
    pass


def _resolve(rel: str) -> Path:
    """Resolve a relative path INSIDE the root, or raise. Blocks '..' escapes,
    absolute paths, and symlink breakouts."""
    r = _ensure_root()
    rel = (rel or "").strip().lstrip("/")
    if not rel:
        return r
    target = (r / rel).resolve()
    if target != r and r not in target.parents:
        raise StorageError(f"path '{rel}' escapes the storage root")
    return target


def _check_ext(name: str) -> None:
    allowed = config()["allowed_ext"]
    if allowed:
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in [e.lower().lstrip(".") for e in allowed]:
            raise StorageError(f"file type '.{ext}' is not allowed by File Storage settings")


# ------------------------------- operations -------------------------------
def list_dir(prefix: str = "") -> list[dict]:
    base = _resolve(prefix)
    if not base.exists():
        return []
    out = []
    for p in sorted(base.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        rel = str(p.relative_to(root()))
        if p.is_dir():
            out.append({"name": p.name, "path": rel, "type": "folder"})
        else:
            st = p.stat()
            out.append({"name": p.name, "path": rel, "type": "file",
                        "size": st.st_size, "modified": st.st_mtime})
    return out


def read_text(rel: str, limit: int = 200_000) -> str:
    p = _resolve(rel)
    if not p.is_file():
        raise StorageError(f"not a file: {rel}")
    return p.read_text(errors="replace")[:limit]


def read_bytes(rel: str) -> bytes:
    p = _resolve(rel)
    if not p.is_file():
        raise StorageError(f"not a file: {rel}")
    return p.read_bytes()


def write_bytes(rel: str, data: bytes, actor: str = "user") -> dict:
    name = Path(rel).name
    _check_ext(name)
    max_bytes = config()["max_file_kb"] * 1024
    if len(data) > max_bytes:
        raise StorageError(f"file exceeds max size ({config()['max_file_kb']} KB)")
    p = _resolve(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    st = p.stat()
    return {"name": p.name, "path": str(p.relative_to(root())), "size": st.st_size}


def write_text(rel: str, content: str, actor: str = "agent") -> dict:
    return write_bytes(rel, content.encode(), actor)


def delete(rel: str) -> bool:
    p = _resolve(rel)
    if p == root():
        raise StorageError("cannot delete the storage root")
    if p.is_dir():
        shutil.rmtree(p)
        return True
    if p.is_file():
        p.unlink()
        return True
    return False


def mkdir(rel: str) -> dict:
    p = _resolve(rel)
    p.mkdir(parents=True, exist_ok=True)
    return {"name": p.name, "path": str(p.relative_to(root())), "type": "folder"}

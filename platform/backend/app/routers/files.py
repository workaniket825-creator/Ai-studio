from __future__ import annotations

import base64
import urllib.parse

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from .. import filestore

router = APIRouter(prefix="/api/v1/files", tags=["file-storage"])


@router.get("/config")
def get_config():
    return filestore.config()


@router.put("/config")
def update_config(patch: dict):
    from ..governance import audit
    cfg = filestore.update_config(patch)
    audit("admin", "update", "file_storage", detail=",".join(patch.keys()))
    return cfg


@router.get("/list")
def list_files(prefix: str = ""):
    try:
        return {"prefix": prefix, "entries": filestore.list_dir(prefix)}
    except filestore.StorageError as e:
        raise HTTPException(400, str(e))


@router.post("/upload")
def upload(body: dict):
    """Upload via base64 JSON (no multipart dependency).
    body: { filename, prefix?, content_b64 }"""
    fn = body.get("filename")
    if not fn:
        raise HTTPException(400, "filename is required")
    try:
        data = base64.b64decode(body.get("content_b64", ""))
    except Exception:
        raise HTTPException(400, "content_b64 must be valid base64")
    prefix = (body.get("prefix") or "shared").rstrip("/")
    rel = f"{prefix}/{fn}" if prefix else fn
    try:
        return filestore.write_bytes(rel, data, actor="user")
    except filestore.StorageError as e:
        raise HTTPException(400, str(e))


@router.get("/download")
def download(path: str):
    try:
        data = filestore.read_bytes(path)
    except filestore.StorageError as e:
        raise HTTPException(404, str(e))
    name = path.rsplit("/", 1)[-1]
    return Response(content=data, media_type="application/octet-stream",
                    headers={"Content-Disposition":
                             f"attachment; filename*=UTF-8''{urllib.parse.quote(name)}"})


@router.get("/preview")
def preview(path: str):
    try:
        return {"path": path, "content": filestore.read_text(path)}
    except filestore.StorageError as e:
        raise HTTPException(404, str(e))


@router.post("/mkdir")
def mkdir(body: dict):
    try:
        return filestore.mkdir(body.get("path", ""))
    except filestore.StorageError as e:
        raise HTTPException(400, str(e))


@router.delete("/delete")
def delete(path: str):
    try:
        ok = filestore.delete(path)
    except filestore.StorageError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "not found")
    return {"deleted": path}

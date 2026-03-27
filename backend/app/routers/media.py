from __future__ import annotations

import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.services.oss_storage import oss_storage

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("/health")
async def media_health() -> dict[str, str]:
    return {"status": "ok", "oss": "on" if oss_storage.enabled else "off"}


@router.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    prefix: str = "uploads",
) -> dict[str, str]:
    """上传文件到阿里云 OSS，返回可访问 URL。"""
    if not oss_storage.enabled:
        raise HTTPException(
            status_code=503,
            detail="OSS 未配置：请设置 oss_region、oss_bucket 及 OSS 环境变量",
        )
    data = await file.read()
    ext = ""
    if file.filename and "." in file.filename:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower()
    key = f"{prefix.strip('/')}/{uuid.uuid4().hex}{ext}"
    url = await oss_storage.put_bytes(key, data)
    return {"url": key, "public_url": url}

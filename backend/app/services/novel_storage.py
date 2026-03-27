from __future__ import annotations

import logging
from pathlib import Path

import httpx

from app.core.config import settings
from app.services.oss_storage import oss_storage

logger = logging.getLogger(__name__)


def ensure_local_novel_dir(novel_id: str) -> Path:
    base = Path(settings.novel_local_upload_dir).resolve()
    d = base / novel_id
    d.mkdir(parents=True, exist_ok=True)
    return d


async def save_novel_reference(
    novel_id: str, data: bytes, original_filename: str
) -> tuple[str, str]:
    """
    保存参考 txt。优先 OSS，否则本地目录。
    返回 (storage_key, public_url 或 API 下载路径)。
    """
    ext = ".txt"
    if original_filename and "." in original_filename:
        ext = "." + original_filename.rsplit(".", 1)[-1].lower()
    safe_name = f"reference{ext}"
    if oss_storage.enabled:
        key = f"novels/{novel_id}/{safe_name}"
        try:
            url = await oss_storage.put_bytes(
                key, data, content_type="text/plain; charset=utf-8"
            )
            return key, url
        except Exception as e:
            logger.warning(
                "OSS 上传参考文件失败（请核对 OSS_REGION / OSS_ENDPOINT 与控制台 Bucket 地域是否一致），"
                "已改存本地: %s",
                e,
            )
    d = ensure_local_novel_dir(novel_id)
    path = d / safe_name
    path.write_bytes(data)
    rel = f"local:{novel_id}/{safe_name}"
    return rel, f"/api/novels/{novel_id}/reference/file"


def read_reference_bytes(storage_key: str, novel_id: str) -> bytes:
    if not storage_key:
        return b""
    if storage_key.startswith("local:"):
        part = storage_key.removeprefix("local:")
        path = Path(settings.novel_local_upload_dir).resolve() / part
        return path.read_bytes()
    raise OSError("当前仅支持本地上传的参考文件直接读取；OSS 请使用 public_url")


def load_reference_text_for_llm(
    storage_key: str,
    novel_id: str,
    public_url: str = "",
    max_chars: int = 80_000,
) -> str:
    text = ""
    if public_url.startswith("http"):
        try:
            r = httpx.get(public_url, timeout=60.0)
            r.raise_for_status()
            text = r.text
        except httpx.HTTPError:
            text = ""
    if not text and storage_key.startswith("local:"):
        try:
            raw = read_reference_bytes(storage_key, novel_id)
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("gb18030", errors="replace")
        except OSError:
            text = ""
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n[参考文本已截断用于模型上下文]"
    return text

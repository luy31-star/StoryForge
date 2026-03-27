from __future__ import annotations

import asyncio
from typing import BinaryIO

import alibabacloud_oss_v2 as oss

from app.core.config import settings


def _normalize_oss_region_id(region: str) -> str:
    """控制台地域多为 cn-hangzhou；若误填 oss-cn-hangzhou 则规整为 cn-hangzhou。"""
    r = region.strip()
    if r.lower().startswith("oss-"):
        r = r[4:]
    return r


def _default_public_endpoint_host(region_id: str) -> str:
    """外网访问域名：oss-{region}.aliyuncs.com（与控制台「Bucket 概览 - Endpoint」一致）。"""
    rid = _normalize_oss_region_id(region_id)
    return f"oss-{rid}.aliyuncs.com"


def _public_url_for_key(key: str) -> str:
    if settings.oss_public_base_url:
        base = settings.oss_public_base_url.rstrip("/")
        return f"{base}/{key.lstrip('/')}"
    if settings.oss_endpoint:
        ep = settings.oss_endpoint.rstrip("/")
        if ep.startswith("http"):
            return f"{ep}/{settings.oss_bucket}/{key.lstrip('/')}"
        return f"https://{ep}/{settings.oss_bucket}/{key.lstrip('/')}"
    if settings.oss_bucket and settings.oss_region:
        host = _default_public_endpoint_host(settings.oss_region)
        return f"https://{settings.oss_bucket}.{host}/{key.lstrip('/')}"
    return f"oss://{settings.oss_bucket}/{key}"


class OSSStorage:
    """阿里云 OSS 存储（SDK V2，凭证：OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET）。"""

    def __init__(self) -> None:
        self._client: oss.Client | None = None

    @property
    def enabled(self) -> bool:
        return bool(settings.oss_region and settings.oss_bucket)

    def _get_client(self) -> oss.Client:
        if self._client is not None:
            return self._client
        if not self.enabled:
            raise RuntimeError("OSS 未配置：请设置 oss_region 与 oss_bucket")
        credentials_provider = oss.credentials.EnvironmentVariableCredentialsProvider()
        cfg = oss.config.load_default()
        cfg.credentials_provider = credentials_provider
        region_id = _normalize_oss_region_id(settings.oss_region)
        cfg.region = region_id
        # 显式指定外网 Endpoint，避免 SDK 推断与 Bucket 实际地域不一致导致 403（EC 0003-00001403）
        if settings.oss_endpoint:
            raw = settings.oss_endpoint.strip()
            cfg.endpoint = raw if raw.startswith("http") else f"https://{raw}"
        else:
            cfg.endpoint = f"https://{_default_public_endpoint_host(settings.oss_region)}"
        self._client = oss.Client(cfg)
        return self._client

    def put_bytes_sync(self, key: str, data: bytes, content_type: str | None = None) -> str:
        client = self._get_client()
        req = oss.PutObjectRequest(
            bucket=settings.oss_bucket,
            key=key.lstrip("/"),
            body=data,
        )
        if content_type and hasattr(req, "content_type"):
            req.content_type = content_type
        client.put_object(req)
        return _public_url_for_key(key)

    def put_fileobj_sync(
        self, key: str, fp: BinaryIO, content_type: str | None = None
    ) -> str:
        data = fp.read()
        return self.put_bytes_sync(key, data, content_type=content_type)

    async def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        return await asyncio.to_thread(
            self.put_bytes_sync, key, data, content_type
        )


oss_storage = OSSStorage()

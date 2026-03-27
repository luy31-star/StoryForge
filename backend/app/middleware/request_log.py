"""HTTP 请求/响应详细日志（方法、路径、查询、客户端、耗时、状态码）。"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("vocalflow.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """记录每个请求的开始、结束与耗时；不含请求体（避免大文件/流式问题）。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        raw_path = request.url.path
        path_q = raw_path
        if request.url.query:
            path_q = f"{raw_path}?{request.url.query[:800]}"
        client = request.client.host if request.client else "-"
        method = request.method
        ua = (request.headers.get("user-agent") or "")[:120]
        clen = request.headers.get("content-length", "-")

        log_detail = logger.info
        if raw_path.startswith("/health") or raw_path == "/":
            log_detail = logger.debug

        log_detail(
            "→ [%s] %s %s | client=%s | ua=%r | content-length=%s",
            rid,
            method,
            path_q,
            client,
            ua,
            clen,
        )

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "✗ [%s] %s %s failed after %.2fms",
                rid,
                method,
                path_q,
                elapsed_ms,
            )
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        log_detail(
            "← [%s] %s %s → %s | %.2fms",
            rid,
            method,
            path_q,
            response.status_code,
            elapsed_ms,
        )
        response.headers["X-Request-Id"] = rid
        return response

from __future__ import annotations

import base64
import html
import json
from urllib.parse import urlencode
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import (
    load_der_private_key,
    load_der_public_key,
    load_pem_private_key,
    load_pem_public_key,
)

from app.core.config import settings


def _read_text(path: str) -> str:
    return Path(path).expanduser().read_text(encoding="utf-8")


def _read_key_bytes(path: str) -> bytes:
    data = _read_text(path).strip().encode("utf-8")
    if data.startswith(b"-----BEGIN "):
        return data
    return b"".join(data.split())


def _load_private_key(path: str) -> rsa.RSAPrivateKey:
    data = _read_key_bytes(path)
    try:
        if data.startswith(b"-----BEGIN "):
            return load_pem_private_key(data, password=None)  # type: ignore[return-value]
        der = base64.b64decode(data, validate=True)
        return load_der_private_key(der, password=None)  # type: ignore[return-value]
    except Exception as e:
        raise RuntimeError("支付宝应用私钥文件格式无效：需要 PEM（含 BEGIN/END）或 base64-encoded DER") from e


def _load_public_key(path: str) -> Any:
    data = _read_key_bytes(path)
    try:
        if data.startswith(b"-----BEGIN "):
            return load_pem_public_key(data)
        der = base64.b64decode(data, validate=True)
        return load_der_public_key(der)
    except Exception as e:
        raise RuntimeError("支付宝公钥文件格式无效：需要 PEM（含 BEGIN/END）或 base64-encoded DER") from e


def _canonical_kv(params: dict[str, Any]) -> str:
    items: list[tuple[str, str]] = []
    for k, v in params.items():
        if v is None:
            continue
        if k == "sign":
            continue
        items.append((k, str(v)))
    items.sort(key=lambda x: x[0])
    return "&".join([f"{k}={v}" for k, v in items])


@dataclass
class AlipayTradeQueryResult:
    trade_status: str
    alipay_trade_no: str
    out_trade_no: str
    total_amount: str
    raw: dict[str, Any]


class AlipayClient:
    def __init__(self) -> None:
        if not settings.alipay_app_id:
            raise RuntimeError("ALIPAY_APP_ID 未配置")
        if not settings.alipay_private_key_path:
            raise RuntimeError("ALIPAY_PRIVATE_KEY_PATH 未配置")
        if not settings.alipay_public_key_path:
            raise RuntimeError("ALIPAY_PUBLIC_KEY_PATH 未配置")

        self.gateway = settings.alipay_gateway_url.rstrip("?")
        self.app_id = settings.alipay_app_id
        self.sign_type = settings.alipay_sign_type

        self._private_key = _load_private_key(settings.alipay_private_key_path)
        self._public_key = _load_public_key(settings.alipay_public_key_path)

    def sign(self, params: dict[str, Any]) -> str:
        msg = _canonical_kv(params).encode("utf-8")
        sig = self._private_key.sign(
            msg,
            padding.PKCS1v15(),
            hashes.SHA256() if self.sign_type == "RSA2" else hashes.SHA1(),
        )
        return base64.b64encode(sig).decode("utf-8")

    def verify(self, params: dict[str, Any]) -> bool:
        sign = params.get("sign")
        if not sign:
            return False
        sign_bytes = base64.b64decode(str(sign))
        msg = _canonical_kv(params).encode("utf-8")
        try:
            self._public_key.verify(  # type: ignore[attr-defined]
                sign_bytes,
                msg,
                padding.PKCS1v15(),
                hashes.SHA256() if str(params.get("sign_type") or self.sign_type) == "RSA2" else hashes.SHA1(),
            )
            return True
        except Exception:
            return False

    def build_params(self, method: str, biz_content: dict[str, Any]) -> dict[str, Any]:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        params: dict[str, Any] = {
            "app_id": self.app_id,
            "method": method,
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": self.sign_type,
            "timestamp": ts,
            "version": "1.0",
            "biz_content": json.dumps(biz_content, ensure_ascii=False, separators=(",", ":")),
        }
        return params

    def _build_gateway_request_parts(self, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        signed = dict(params)
        signed["sign"] = self.sign(signed)

        query_params = {k: v for k, v in signed.items() if k != "biz_content"}
        body_params = {}
        if "biz_content" in signed:
            body_params["biz_content"] = signed["biz_content"]
        action = f"{self.gateway}?{urlencode(query_params)}"
        return action, body_params

    def page_pay_form(
        self,
        out_trade_no: str,
        total_amount: str,
        subject: str,
        notify_url: str,
        return_url: str,
    ) -> str:
        biz = {
            "out_trade_no": out_trade_no,
            "product_code": "FAST_INSTANT_TRADE_PAY",
            "total_amount": total_amount,
            "subject": subject,
        }
        params = self.build_params("alipay.trade.page.pay", biz)
        params["notify_url"] = notify_url
        params["return_url"] = return_url
        action, body_params = self._build_gateway_request_parts(params)

        inputs = "\n".join(
            [
                f'<input type="hidden" name="{html.escape(str(k), quote=True)}" value="{html.escape(str(v), quote=True)}"/>'
                for k, v in body_params.items()
            ]
        )
        page_html = f"""
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>跳转支付宝支付</title>
  </head>
  <body>
    <p>正在跳转到支付宝支付页…</p>
    <form id="alipay_form" accept-charset="utf-8" method="post" action="{html.escape(action, quote=True)}">
      {inputs}
      <button type="submit">如未自动跳转，请点击继续</button>
    </form>
    <script>
      setTimeout(function(){{ document.getElementById("alipay_form").submit(); }}, 50);
    </script>
  </body>
</html>
"""
        return page_html.strip()

    def trade_query_sync(self, out_trade_no: str) -> AlipayTradeQueryResult:
        biz = {"out_trade_no": out_trade_no}
        params = self.build_params("alipay.trade.query", biz)
        action, body_params = self._build_gateway_request_parts(params)

        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                action,
                data=body_params,
                headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
            )
            resp.raise_for_status()
            data = resp.json()

        payload = data.get("alipay_trade_query_response") or {}
        return AlipayTradeQueryResult(
            trade_status=str(payload.get("trade_status") or ""),
            alipay_trade_no=str(payload.get("trade_no") or ""),
            out_trade_no=str(payload.get("out_trade_no") or out_trade_no),
            total_amount=str(payload.get("total_amount") or ""),
            raw=data,
        )

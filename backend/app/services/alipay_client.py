from __future__ import annotations

import base64
import html
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key

from app.core.config import settings


def _read_text(path: str) -> str:
    return Path(path).expanduser().read_text(encoding="utf-8")


def _canonical_kv(params: dict[str, Any]) -> str:
    items: list[tuple[str, str]] = []
    for k, v in params.items():
        if v is None:
            continue
        if k in ("sign", "sign_type"):
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

        priv_pem = _read_text(settings.alipay_private_key_path).encode("utf-8")
        pub_pem = _read_text(settings.alipay_public_key_path).encode("utf-8")

        self._private_key: rsa.RSAPrivateKey = load_pem_private_key(priv_pem, password=None)  # type: ignore[assignment]
        self._public_key = load_pem_public_key(pub_pem)

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
        params["sign"] = self.sign(params)

        inputs = "\n".join(
            [
                f'<input type="hidden" name="{html.escape(str(k), quote=True)}" value="{html.escape(str(v), quote=True)}"/>'
                for k, v in params.items()
            ]
        )
        html = f"""
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>跳转支付宝支付</title>
  </head>
  <body>
    <form id="alipay_form" method="post" action="{self.gateway}">
      {inputs}
    </form>
    <script>
      setTimeout(function(){{ document.getElementById("alipay_form").submit(); }}, 50);
    </script>
  </body>
</html>
"""
        return html.strip()

    def trade_query_sync(self, out_trade_no: str) -> AlipayTradeQueryResult:
        biz = {"out_trade_no": out_trade_no}
        params = self.build_params("alipay.trade.query", biz)
        params["sign"] = self.sign(params)

        with httpx.Client(timeout=20.0) as client:
            resp = client.post(self.gateway, data=params)
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

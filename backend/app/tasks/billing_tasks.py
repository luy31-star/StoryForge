from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.recharge_order import RechargeOrder
from app.services.alipay_client import AlipayClient
from app.services.recharge_service import apply_recharge_paid, fmt_amount_cny
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="billing.reconcile_alipay_orders")
def reconcile_alipay_orders() -> dict[str, int]:
    if not settings.alipay_reconcile_enabled:
        return {"skipped": 1, "processed": 0, "paid": 0, "closed": 0, "failed": 0}

    now = datetime.utcnow()
    min_created_at = now - timedelta(hours=int(settings.alipay_reconcile_lookback_hours))
    max_created_at = now - timedelta(minutes=int(settings.alipay_reconcile_min_age_minutes))

    db = SessionLocal()
    processed = 0
    paid = 0
    closed = 0
    failed = 0
    try:
        client = AlipayClient()
        rows = (
            db.query(RechargeOrder)
            .filter(
                RechargeOrder.channel == "alipay",
                RechargeOrder.status.in_(["created", "pending"]),
                RechargeOrder.created_at >= min_created_at,
                RechargeOrder.created_at <= max_created_at,
            )
            .order_by(RechargeOrder.created_at.asc())
            .limit(50)
            .all()
        )

        for order in rows:
            processed += 1
            try:
                q = client.trade_query_sync(order.out_trade_no)
                order.query_raw = json.dumps(q.raw, ensure_ascii=False)
                order.reconciled_at = datetime.utcnow()
                order.trade_status = q.trade_status or order.trade_status
                order.alipay_trade_no = q.alipay_trade_no or order.alipay_trade_no

                if q.total_amount and q.total_amount != fmt_amount_cny(int(order.amount_cny or 0)):
                    db.commit()
                    continue

                if q.trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
                    apply_recharge_paid(db, order, q.trade_status, q.alipay_trade_no, q.raw, via="query")
                    paid += 1
                elif q.trade_status in ("TRADE_CLOSED",):
                    order.status = "closed"
                    closed += 1
                else:
                    if order.status == "created":
                        order.status = "pending"

                db.commit()
            except Exception:
                failed += 1
                logger.exception("reconcile failed | out_trade_no=%s", order.out_trade_no)
                db.rollback()

        return {
            "skipped": 0,
            "processed": processed,
            "paid": paid,
            "closed": closed,
            "failed": failed,
        }
    finally:
        db.close()


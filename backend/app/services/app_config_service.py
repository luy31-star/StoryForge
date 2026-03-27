from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.app_config import AppConfig


DEFAULT_CONFIG_ID = "global"


def ensure_app_config(db: Session) -> AppConfig:
    row = db.get(AppConfig, DEFAULT_CONFIG_ID)
    if row:
        return row

    row = AppConfig(id=DEFAULT_CONFIG_ID)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_app_config(db: Session) -> AppConfig:
    return ensure_app_config(db)

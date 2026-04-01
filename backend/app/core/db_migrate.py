from __future__ import annotations

import logging

from sqlalchemy import Engine, text

from app.core.config import settings

logger = logging.getLogger(__name__)


def _has_column_sqlite(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    for r in rows:
        # (cid, name, type, notnull, dflt_value, pk)
        if len(r) >= 2 and str(r[1]) == column:
            return True
    return False


def _has_column_postgres(conn, table: str, column: str) -> bool:
    q = text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c LIMIT 1"
    )
    row = conn.execute(q, {"t": table, "c": column}).fetchone()
    return row is not None


def ensure_novel_target_chapters(engine: Engine) -> None:
    """
    轻量自动迁移：给 novels 表补 target_chapters 列。
    说明：项目未引入 Alembic；create_all 不会给已有表加列，所以需要这段兜底。
    """
    try:
        with engine.begin() as conn:
            dialect = engine.dialect.name
            if dialect == "sqlite":
                if _has_column_sqlite(conn, "novels", "target_chapters"):
                    return
                conn.execute(
                    text("ALTER TABLE novels ADD COLUMN target_chapters INTEGER DEFAULT 300")
                )
                logger.info("db migrate: added novels.target_chapters (sqlite)")
                return
            if dialect in ("postgresql", "postgres"):
                if _has_column_postgres(conn, "novels", "target_chapters"):
                    return
                conn.execute(
                    text(
                        "ALTER TABLE novels ADD COLUMN target_chapters INTEGER DEFAULT 300"
                    )
                )
                logger.info("db migrate: added novels.target_chapters (postgres)")
                return
            logger.warning("db migrate: unsupported dialect=%s, skip", dialect)
    except Exception:
        logger.exception("db migrate: ensure_novel_target_chapters failed")


def ensure_app_config_row(engine: Engine) -> None:
    """轻量初始化：确保 app_config 表至少存在一行全局配置。"""
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT 1 FROM app_config WHERE id = :id LIMIT 1"),
                {"id": "global"},
            ).fetchone()
            if row is not None:
                return

            # 表由 create_all 创建；这里仅做插入兜底
            conn.execute(
                text(
                    "INSERT INTO app_config ("
                    "id, llm_provider, llm_model, "
                    "novel_web_search, novel_generate_web_search, novel_volume_plan_web_search, novel_memory_refresh_web_search, "
                    "novel_inspiration_web_search, updated_at"
                    ") VALUES (:id, :p, :m, :nws, :ngws, :npws, :nmws, :niws, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": "global",
                    "p": (settings.llm_provider or "ai302").strip().lower(),
                    "m": (settings.llm_model or "").strip(),
                    "nws": int(bool(settings.ai302_novel_web_search)),
                    "ngws": int(bool(settings.ai302_novel_web_search)),
                    "npws": int(bool(settings.ai302_novel_web_search)),
                    "nmws": int(bool(settings.ai302_novel_web_search)),
                    "niws": 1,
                },
            )
            logger.info("db migrate: inserted app_config:global")
    except Exception:
        logger.exception("db migrate: ensure_app_config_row failed")


def ensure_app_config_columns(engine: Engine) -> None:
    """轻量迁移：补齐 app_config 细粒度 web-search 列。"""
    cols = (
        "novel_generate_web_search",
        "novel_volume_plan_web_search",
        "novel_memory_refresh_web_search",
    )
    try:
        with engine.begin() as conn:
            dialect = engine.dialect.name
            for c in cols:
                if dialect == "sqlite":
                    if _has_column_sqlite(conn, "app_config", c):
                        continue
                    conn.execute(
                        text(f"ALTER TABLE app_config ADD COLUMN {c} BOOLEAN DEFAULT 0")
                    )
                    conn.execute(
                        text(
                            f"UPDATE app_config SET {c} = COALESCE(novel_web_search, 0) "
                            f"WHERE {c} IS NULL OR {c} = 0"
                        )
                    )
                    logger.info("db migrate: added app_config.%s (sqlite)", c)
                elif dialect in ("postgresql", "postgres"):
                    if _has_column_postgres(conn, "app_config", c):
                        continue
                    conn.execute(
                        text(
                            f"ALTER TABLE app_config ADD COLUMN {c} BOOLEAN DEFAULT FALSE"
                        )
                    )
                    conn.execute(
                        text(
                            f"UPDATE app_config SET {c} = COALESCE(novel_web_search, FALSE) "
                            f"WHERE {c} IS NULL OR {c} = FALSE"
                        )
                    )
                    logger.info("db migrate: added app_config.%s (postgres)", c)
                else:
                    logger.warning("db migrate: unsupported dialect=%s, skip %s", dialect, c)
    except Exception:
        logger.exception("db migrate: ensure_app_config_columns failed")


def ensure_novel_memory_norm_extended_columns(engine: Engine) -> None:
    """
    轻量迁移：规范化记忆表 v2 列（影响力、情绪锚点、伏笔元数据、设定防火墙）。
    create_all 不会给已有表加列。
    """
    sqlite_alters: list[tuple[str, str]] = [
        ("novel_memory_norm_outline", "forbidden_constraints_json TEXT DEFAULT '[]'"),
        ("novel_memory_norm_skills", "influence_score INTEGER DEFAULT 0"),
        ("novel_memory_norm_skills", "is_active BOOLEAN DEFAULT 1"),
        ("novel_memory_norm_items", "influence_score INTEGER DEFAULT 0"),
        ("novel_memory_norm_items", "is_active BOOLEAN DEFAULT 1"),
        ("novel_memory_norm_pets", "influence_score INTEGER DEFAULT 0"),
        ("novel_memory_norm_pets", "is_active BOOLEAN DEFAULT 1"),
        ("novel_memory_norm_characters", "influence_score INTEGER DEFAULT 0"),
        ("novel_memory_norm_characters", "is_active BOOLEAN DEFAULT 1"),
        ("novel_memory_norm_plots", "plot_type VARCHAR(32) DEFAULT 'Transient'"),
        ("novel_memory_norm_plots", "priority INTEGER DEFAULT 0"),
        ("novel_memory_norm_plots", "estimated_duration INTEGER DEFAULT 0"),
        ("novel_memory_norm_plots", "current_stage TEXT DEFAULT ''"),
        ("novel_memory_norm_plots", "resolve_when TEXT DEFAULT ''"),
        ("novel_memory_norm_plots", "introduced_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_plots", "last_touched_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_chapters", "emotional_state TEXT DEFAULT ''"),
        ("novel_memory_norm_chapters", "unresolved_hooks_json TEXT DEFAULT '[]'"),
    ]
    pg_alters: list[tuple[str, str]] = [
        ("novel_memory_norm_outline", "forbidden_constraints_json TEXT DEFAULT '[]'"),
        ("novel_memory_norm_skills", "influence_score INTEGER DEFAULT 0"),
        ("novel_memory_norm_skills", "is_active BOOLEAN DEFAULT TRUE"),
        ("novel_memory_norm_items", "influence_score INTEGER DEFAULT 0"),
        ("novel_memory_norm_items", "is_active BOOLEAN DEFAULT TRUE"),
        ("novel_memory_norm_pets", "influence_score INTEGER DEFAULT 0"),
        ("novel_memory_norm_pets", "is_active BOOLEAN DEFAULT TRUE"),
        ("novel_memory_norm_characters", "influence_score INTEGER DEFAULT 0"),
        ("novel_memory_norm_characters", "is_active BOOLEAN DEFAULT TRUE"),
        ("novel_memory_norm_plots", "plot_type VARCHAR(32) DEFAULT 'Transient'"),
        ("novel_memory_norm_plots", "priority INTEGER DEFAULT 0"),
        ("novel_memory_norm_plots", "estimated_duration INTEGER DEFAULT 0"),
        ("novel_memory_norm_plots", "current_stage TEXT DEFAULT ''"),
        ("novel_memory_norm_plots", "resolve_when TEXT DEFAULT ''"),
        ("novel_memory_norm_plots", "introduced_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_plots", "last_touched_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_chapters", "emotional_state TEXT DEFAULT ''"),
        ("novel_memory_norm_chapters", "unresolved_hooks_json TEXT DEFAULT '[]'"),
    ]
    try:
        with engine.begin() as conn:
            dialect = engine.dialect.name
            if dialect == "sqlite":
                for table, ddl in sqlite_alters:
                    col = ddl.split()[0]
                    if _has_column_sqlite(conn, table, col):
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                    logger.info("db migrate: added %s.%s (sqlite)", table, col)
            elif dialect in ("postgresql", "postgres"):
                for table, ddl in pg_alters:
                    col = ddl.split()[0]
                    if _has_column_postgres(conn, table, col):
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                    logger.info("db migrate: added %s.%s (postgres)", table, col)
            else:
                logger.warning(
                    "db migrate: ensure_novel_memory_norm_extended_columns unsupported dialect=%s",
                    dialect,
                )
    except Exception:
        logger.exception("db migrate: ensure_novel_memory_norm_extended_columns failed")


def ensure_user_isolation_columns(engine: Engine) -> None:
    """
    轻量迁移：为 novels / projects / workflows 补 user_id（多用户隔离）。
    users 表须已由 metadata.create_all 创建。
    """
    sqlite_specs = [
        ("novels", "user_id VARCHAR(36)"),
        ("projects", "user_id VARCHAR(36)"),
        ("workflows", "user_id VARCHAR(36)"),
    ]
    pg_specs = [
        ("novels", "user_id VARCHAR(36)"),
        ("projects", "user_id VARCHAR(36)"),
        ("workflows", "user_id VARCHAR(36)"),
    ]
    try:
        with engine.begin() as conn:
            dialect = engine.dialect.name
            if dialect == "sqlite":
                for table, ddl in sqlite_specs:
                    col = ddl.split()[0]
                    if _has_column_sqlite(conn, table, col):
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                    logger.info("db migrate: added %s.%s (sqlite)", table, col)
            elif dialect in ("postgresql", "postgres"):
                for table, ddl in pg_specs:
                    col = ddl.split()[0]
                    if _has_column_postgres(conn, table, col):
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                    logger.info("db migrate: added %s.%s (postgres)", table, col)
            else:
                logger.warning(
                    "db migrate: ensure_user_isolation_columns unsupported dialect=%s",
                    dialect,
                )
    except Exception:
        logger.exception("db migrate: ensure_user_isolation_columns failed")


def relax_novel_memory_norm_columns(engine: Engine) -> None:
    """
    轻量迁移：放宽 novel_memory_norm_outline 表中已移除字段的约束。
    原因：代码中移除了 world_rules_json, arcs_json, themes_json, notes_json，
    但旧数据库中这些列可能存在且为 NOT NULL，导致插入失败。
    """
    cols = ("world_rules_json", "arcs_json", "themes_json", "notes_json")
    try:
        with engine.begin() as conn:
            dialect = engine.dialect.name
            if dialect in ("postgresql", "postgres"):
                for c in cols:
                    if _has_column_postgres(conn, "novel_memory_norm_outline", c):
                        conn.execute(
                            text(
                                f"ALTER TABLE novel_memory_norm_outline ALTER COLUMN {c} DROP NOT NULL"
                            )
                        )
                        logger.info("db migrate: relaxed novel_memory_norm_outline.%s (postgres)", c)
            elif dialect == "sqlite":
                # SQLite 不支持直接 DROP NOT NULL，且我们不再向这些列写数据，
                # 如果是新创建的表，这些列根本不存在；如果是旧表，SQLite 默认允许 NULL（除非显式指定）。
                # 实际上 SQLite 的 ALTER TABLE 限制很多，通常需要重建表。
                # 鉴于报错主要发生在 Postgres，SQLite 暂时跳过。
                pass
    except Exception:
        logger.exception("db migrate: relax_novel_memory_norm_columns failed")


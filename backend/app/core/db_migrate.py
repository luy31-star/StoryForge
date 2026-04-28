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


def _has_column_mysql(conn, table: str, column: str) -> bool:
    """MySQL 的 information_schema 检查。"""
    q = text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c LIMIT 1"
    )
    row = conn.execute(q, {"t": table, "c": column}).fetchone()
    return row is not None


def ensure_novel_target_chapters(engine: Engine) -> None:
    """
    轻量自动迁移：给 novels 表补小说写作设置相关列。
    说明：项目未引入 Alembic；create_all 不会给已有表加列，所以需要这段兜底。
    """
    try:
        with engine.begin() as conn:
            dialect = engine.dialect.name
            if dialect == "sqlite":
                if _has_column_sqlite(conn, "novels", "target_chapters"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN target_chapters INTEGER DEFAULT 300")
                    )
                    logger.info("db migrate: added novels.target_chapters (sqlite)")
                
                if _has_column_sqlite(conn, "novels", "daily_auto_time"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN daily_auto_time VARCHAR(16) DEFAULT '14:30'")
                    )
                    logger.info("db migrate: added novels.daily_auto_time (sqlite)")

                if _has_column_sqlite(conn, "novels", "last_auto_date"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN last_auto_date VARCHAR(10) DEFAULT ''")
                    )
                    logger.info("db migrate: added novels.last_auto_date (sqlite)")

                if _has_column_sqlite(conn, "novels", "chapter_target_words"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN chapter_target_words INTEGER DEFAULT 3000")
                    )
                    logger.info("db migrate: added novels.chapter_target_words (sqlite)")
                if _has_column_sqlite(conn, "novels", "auto_consistency_check"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN auto_consistency_check BOOLEAN DEFAULT 0")
                    )
                    logger.info("db migrate: added novels.auto_consistency_check (sqlite)")
                if _has_column_sqlite(conn, "novels", "auto_plan_guard_check"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN auto_plan_guard_check BOOLEAN DEFAULT 0")
                    )
                    logger.info("db migrate: added novels.auto_plan_guard_check (sqlite)")
                if _has_column_sqlite(conn, "novels", "auto_plan_guard_fix"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN auto_plan_guard_fix BOOLEAN DEFAULT 0")
                    )
                    logger.info("db migrate: added novels.auto_plan_guard_fix (sqlite)")
                if _has_column_sqlite(conn, "novels", "auto_style_polish"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN auto_style_polish BOOLEAN DEFAULT 0")
                    )
                    logger.info("db migrate: added novels.auto_style_polish (sqlite)")
                if _has_column_sqlite(conn, "novels", "base_framework_confirmed"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN base_framework_confirmed BOOLEAN DEFAULT 0")
                    )
                    logger.info("db migrate: added novels.base_framework_confirmed (sqlite)")
                if _has_column_sqlite(conn, "novels", "rag_enabled"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN rag_enabled BOOLEAN DEFAULT 0")
                    )
                    logger.info("db migrate: added novels.rag_enabled (sqlite)")
                if _has_column_sqlite(conn, "novels", "story_bible_enabled"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN story_bible_enabled BOOLEAN DEFAULT 0")
                    )
                    logger.info("db migrate: added novels.story_bible_enabled (sqlite)")
                conn.execute(
                    text(
                        "UPDATE novels SET auto_consistency_check = COALESCE(auto_consistency_check, 0)"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE novels SET auto_plan_guard_check = COALESCE(auto_plan_guard_check, 0)"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE novels SET auto_plan_guard_fix = COALESCE(auto_plan_guard_fix, 0)"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE novels SET auto_style_polish = COALESCE(auto_style_polish, 0)"
                    )
                )
                return
            if dialect in ("postgresql", "postgres"):
                if _has_column_postgres(conn, "novels", "target_chapters"):
                    pass
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE novels ADD COLUMN target_chapters INTEGER DEFAULT 300"
                        )
                    )
                    logger.info("db migrate: added novels.target_chapters (postgres)")
                
                if _has_column_postgres(conn, "novels", "daily_auto_time"):
                    pass
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE novels ADD COLUMN daily_auto_time VARCHAR(16) DEFAULT '14:30'"
                        )
                    )
                    logger.info("db migrate: added novels.daily_auto_time (postgres)")

                if _has_column_postgres(conn, "novels", "last_auto_date"):
                    pass
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE novels ADD COLUMN last_auto_date VARCHAR(10) DEFAULT ''"
                        )
                    )
                    logger.info("db migrate: added novels.last_auto_date (postgres)")

                if _has_column_postgres(conn, "novels", "chapter_target_words"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN chapter_target_words INTEGER DEFAULT 3000")
                    )
                    logger.info("db migrate: added novels.chapter_target_words (postgres)")
                if _has_column_postgres(conn, "novels", "auto_consistency_check"):
                    pass
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE novels ADD COLUMN auto_consistency_check BOOLEAN DEFAULT FALSE"
                        )
                    )
                    logger.info("db migrate: added novels.auto_consistency_check (postgres)")
                if _has_column_postgres(conn, "novels", "auto_plan_guard_check"):
                    pass
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE novels ADD COLUMN auto_plan_guard_check BOOLEAN DEFAULT FALSE"
                        )
                    )
                    logger.info("db migrate: added novels.auto_plan_guard_check (postgres)")
                if _has_column_postgres(conn, "novels", "auto_plan_guard_fix"):
                    pass
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE novels ADD COLUMN auto_plan_guard_fix BOOLEAN DEFAULT FALSE"
                        )
                    )
                    logger.info("db migrate: added novels.auto_plan_guard_fix (postgres)")
                if _has_column_postgres(conn, "novels", "auto_style_polish"):
                    pass
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE novels ADD COLUMN auto_style_polish BOOLEAN DEFAULT FALSE"
                        )
                    )
                    logger.info("db migrate: added novels.auto_style_polish (postgres)")
                if _has_column_postgres(conn, "novels", "rag_enabled"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN rag_enabled BOOLEAN DEFAULT FALSE")
                    )
                    logger.info("db migrate: added novels.rag_enabled (postgres)")
                if _has_column_postgres(conn, "novels", "story_bible_enabled"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN story_bible_enabled BOOLEAN DEFAULT FALSE")
                    )
                    logger.info("db migrate: added novels.story_bible_enabled (postgres)")
                conn.execute(
                    text(
                        "UPDATE novels SET auto_consistency_check = COALESCE(auto_consistency_check, FALSE)"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE novels SET auto_plan_guard_check = COALESCE(auto_plan_guard_check, FALSE)"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE novels SET auto_plan_guard_fix = COALESCE(auto_plan_guard_fix, FALSE)"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE novels SET auto_style_polish = COALESCE(auto_style_polish, FALSE)"
                    )
                )
                return
            if dialect == "mysql":
                if _has_column_mysql(conn, "novels", "target_chapters"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN target_chapters INTEGER DEFAULT 300")
                    )
                    logger.info("db migrate: added novels.target_chapters (mysql)")
                
                if _has_column_mysql(conn, "novels", "daily_auto_time"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN daily_auto_time VARCHAR(16) DEFAULT '14:30'")
                    )
                    logger.info("db migrate: added novels.daily_auto_time (mysql)")

                if _has_column_mysql(conn, "novels", "last_auto_date"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN last_auto_date VARCHAR(10) DEFAULT ''")
                    )
                    logger.info("db migrate: added novels.last_auto_date (mysql)")

                if _has_column_mysql(conn, "novels", "chapter_target_words"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN chapter_target_words INTEGER DEFAULT 3000")
                    )
                    logger.info("db migrate: added novels.chapter_target_words (mysql)")
                if _has_column_mysql(conn, "novels", "auto_consistency_check"):
                    pass
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE novels ADD COLUMN auto_consistency_check BOOLEAN DEFAULT FALSE"
                        )
                    )
                    logger.info("db migrate: added novels.auto_consistency_check (mysql)")
                if _has_column_mysql(conn, "novels", "auto_plan_guard_check"):
                    pass
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE novels ADD COLUMN auto_plan_guard_check BOOLEAN DEFAULT FALSE"
                        )
                    )
                    logger.info("db migrate: added novels.auto_plan_guard_check (mysql)")
                if _has_column_mysql(conn, "novels", "auto_plan_guard_fix"):
                    pass
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE novels ADD COLUMN auto_plan_guard_fix BOOLEAN DEFAULT FALSE"
                        )
                    )
                    logger.info("db migrate: added novels.auto_plan_guard_fix (mysql)")
                if _has_column_mysql(conn, "novels", "auto_style_polish"):
                    pass
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE novels ADD COLUMN auto_style_polish BOOLEAN DEFAULT FALSE"
                        )
                    )
                    logger.info("db migrate: added novels.auto_style_polish (mysql)")
                if _has_column_mysql(conn, "novels", "base_framework_confirmed"):
                    pass
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE novels ADD COLUMN base_framework_confirmed BOOLEAN DEFAULT FALSE"
                        )
                    )
                    logger.info("db migrate: added novels.base_framework_confirmed (mysql)")
                if _has_column_mysql(conn, "novels", "rag_enabled"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN rag_enabled BOOLEAN DEFAULT FALSE")
                    )
                    logger.info("db migrate: added novels.rag_enabled (mysql)")
                if _has_column_mysql(conn, "novels", "story_bible_enabled"):
                    pass
                else:
                    conn.execute(
                        text("ALTER TABLE novels ADD COLUMN story_bible_enabled BOOLEAN DEFAULT FALSE")
                    )
                    logger.info("db migrate: added novels.story_bible_enabled (mysql)")
                conn.execute(
                    text(
                        "UPDATE novels SET auto_consistency_check = COALESCE(auto_consistency_check, FALSE)"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE novels SET auto_plan_guard_check = COALESCE(auto_plan_guard_check, FALSE)"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE novels SET auto_plan_guard_fix = COALESCE(auto_plan_guard_fix, FALSE)"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE novels SET auto_style_polish = COALESCE(auto_style_polish, FALSE)"
                    )
                )
                return
            logger.warning("db migrate: unsupported dialect=%s, skip", dialect)
    except Exception:
        logger.exception("db migrate: ensure_novel_target_chapters failed")


def ensure_user_email_column(engine: Engine) -> None:
    """补齐 User 表 email 列并设置默认值。"""
    table = "users"
    col = "email"
    ddl = "VARCHAR(255) DEFAULT 'luyuhrbust@163.com'"
    
    try:
        with engine.begin() as conn:
            dialect = engine.dialect.name
            exists = False
            if dialect == "sqlite":
                exists = _has_column_sqlite(conn, table, col)
            elif dialect == "mysql":
                exists = _has_column_mysql(conn, table, col)
            elif dialect in ("postgresql", "postgres"):
                exists = _has_column_postgres(conn, table, col)

            if not exists:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                # 更新已有用户邮箱为默认值
                conn.execute(text(f"UPDATE {table} SET {col} = 'luyuhrbust@163.com' WHERE {col} IS NULL"))
                logger.info("db migrate: added %s.%s (%s)", table, col, dialect)
            else:
                # 即使列存在，也确保旧用户有默认邮箱
                conn.execute(text(f"UPDATE {table} SET {col} = 'luyuhrbust@163.com' WHERE {col} IS NULL OR {col} = ''"))
    except Exception:
        logger.exception("db migrate: ensure_user_email_column failed")


def ensure_user_status_columns(engine: Engine) -> None:
    try:
        with engine.begin() as conn:
            dialect = engine.dialect.name
            if dialect == "mysql":
                cols: tuple[tuple[str, str], ...] = (
                    ("is_frozen", "BOOLEAN DEFAULT FALSE"),
                    ("frozen_reason", "TEXT"),
                    ("frozen_at", "DATETIME NULL"),
                )
            elif dialect in ("postgresql", "postgres"):
                cols = (
                    ("is_frozen", "BOOLEAN DEFAULT FALSE"),
                    ("frozen_reason", "TEXT DEFAULT ''"),
                    ("frozen_at", "TIMESTAMP NULL"),
                )
            else:
                cols = (
                    ("is_frozen", "BOOLEAN DEFAULT FALSE"),
                    ("frozen_reason", "TEXT DEFAULT ''"),
                    ("frozen_at", "DATETIME NULL"),
                )
            for col, ddl in cols:
                exists = False
                if dialect == "sqlite":
                    exists = _has_column_sqlite(conn, "users", col)
                elif dialect == "mysql":
                    exists = _has_column_mysql(conn, "users", col)
                elif dialect in ("postgresql", "postgres"):
                    exists = _has_column_postgres(conn, "users", col)
                if exists:
                    continue
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))
                logger.info("db migrate: added users.%s (%s)", col, dialect)
            if dialect == "mysql":
                if _has_column_mysql(conn, "users", "is_frozen"):
                    conn.execute(text("UPDATE users SET is_frozen = 0 WHERE is_frozen IS NULL"))
                if _has_column_mysql(conn, "users", "frozen_reason"):
                    conn.execute(text("UPDATE users SET frozen_reason = '' WHERE frozen_reason IS NULL"))
    except Exception:
        logger.exception("db migrate: ensure_user_status_columns failed")


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
                    "novel_inspiration_web_search, invite_only_registration, updated_at"
                    ") VALUES (:id, :p, :m, :nws, :ngws, :npws, :nmws, :niws, :invite_only, CURRENT_TIMESTAMP)"
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
                    "invite_only": 1,
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
        "invite_only_registration",
    )
    try:
        with engine.begin() as conn:
            dialect = engine.dialect.name
            for c in cols:
                if dialect == "sqlite":
                    if _has_column_sqlite(conn, "app_config", c):
                        continue
                    default_v = 1 if c == "invite_only_registration" else 0
                    conn.execute(text(f"ALTER TABLE app_config ADD COLUMN {c} BOOLEAN DEFAULT {default_v}"))
                    if c != "invite_only_registration":
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
                    default_v = "TRUE" if c == "invite_only_registration" else "FALSE"
                    conn.execute(text(f"ALTER TABLE app_config ADD COLUMN {c} BOOLEAN DEFAULT {default_v}"))
                    if c != "invite_only_registration":
                        conn.execute(
                            text(
                                f"UPDATE app_config SET {c} = COALESCE(novel_web_search, FALSE) "
                                f"WHERE {c} IS NULL OR {c} = FALSE"
                            )
                        )
                    logger.info("db migrate: added app_config.%s (postgres)", c)
                elif dialect == "mysql":
                    if _has_column_mysql(conn, "app_config", c):
                        continue
                    default_v = "TRUE" if c == "invite_only_registration" else "FALSE"
                    conn.execute(text(f"ALTER TABLE app_config ADD COLUMN {c} BOOLEAN DEFAULT {default_v}"))
                    if c != "invite_only_registration":
                        conn.execute(
                            text(
                                f"UPDATE app_config SET {c} = COALESCE(novel_web_search, FALSE) "
                                f"WHERE {c} IS NULL OR {c} = FALSE"
                            )
                        )
                    logger.info("db migrate: added app_config.%s (mysql)", c)
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
        ("novel_memory_norm_relations", "is_active BOOLEAN DEFAULT 1"),
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
        ("novel_memory_norm_relations", "is_active BOOLEAN DEFAULT TRUE"),
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
            elif dialect == "mysql":
                for table, ddl in pg_alters:
                    col = ddl.split()[0]
                    if _has_column_mysql(conn, table, col):
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                    logger.info("db migrate: added %s.%s (mysql)", table, col)
            else:
                logger.warning(
                    "db migrate: ensure_novel_memory_norm_extended_columns unsupported dialect=%s",
                    dialect,
                )
    except Exception:
        logger.exception("db migrate: ensure_novel_memory_norm_extended_columns failed")


def ensure_story_bible_columns(engine: Engine) -> None:
    """
    轻量迁移：为现有规范化记忆表补 Story Bible / RAG 需要的别名、标签、来源章节等字段。
    """
    sqlite_specs: list[tuple[str, str]] = [
        ("novel_memory_norm_skills", "aliases_json TEXT DEFAULT '[]'"),
        ("novel_memory_norm_skills", "tags_json TEXT DEFAULT '[]'"),
        ("novel_memory_norm_skills", "source_chapter_no INTEGER DEFAULT 0"),
        ("novel_memory_norm_skills", "last_seen_chapter_no INTEGER DEFAULT 0"),
        ("novel_memory_norm_items", "aliases_json TEXT DEFAULT '[]'"),
        ("novel_memory_norm_items", "tags_json TEXT DEFAULT '[]'"),
        ("novel_memory_norm_items", "source_chapter_no INTEGER DEFAULT 0"),
        ("novel_memory_norm_items", "last_seen_chapter_no INTEGER DEFAULT 0"),
        ("novel_memory_norm_pets", "aliases_json TEXT DEFAULT '[]'"),
        ("novel_memory_norm_pets", "tags_json TEXT DEFAULT '[]'"),
        ("novel_memory_norm_pets", "source_chapter_no INTEGER DEFAULT 0"),
        ("novel_memory_norm_pets", "last_seen_chapter_no INTEGER DEFAULT 0"),
        ("novel_memory_norm_characters", "aliases_json TEXT DEFAULT '[]'"),
        ("novel_memory_norm_characters", "tags_json TEXT DEFAULT '[]'"),
        ("novel_memory_norm_characters", "source_chapter_no INTEGER DEFAULT 0"),
        ("novel_memory_norm_characters", "last_seen_chapter_no INTEGER DEFAULT 0"),
        ("novel_memory_norm_relations", "detail_json TEXT DEFAULT '{}'"),
        ("novel_memory_norm_relations", "source_chapter_no INTEGER DEFAULT 0"),
        ("novel_memory_norm_relations", "last_seen_chapter_no INTEGER DEFAULT 0"),
        ("novel_memory_norm_plots", "related_entities_json TEXT DEFAULT '[]'"),
        ("novel_memory_norm_chapters", "scene_facts_json TEXT DEFAULT '[]'"),
    ]
    pg_specs = sqlite_specs
    mysql_specs: list[tuple[str, str, str | None]] = [
        ("novel_memory_norm_skills", "aliases_json LONGTEXT NULL", "UPDATE novel_memory_norm_skills SET aliases_json = '[]' WHERE aliases_json IS NULL"),
        ("novel_memory_norm_skills", "tags_json LONGTEXT NULL", "UPDATE novel_memory_norm_skills SET tags_json = '[]' WHERE tags_json IS NULL"),
        ("novel_memory_norm_skills", "source_chapter_no INTEGER DEFAULT 0", None),
        ("novel_memory_norm_skills", "last_seen_chapter_no INTEGER DEFAULT 0", None),
        ("novel_memory_norm_items", "aliases_json LONGTEXT NULL", "UPDATE novel_memory_norm_items SET aliases_json = '[]' WHERE aliases_json IS NULL"),
        ("novel_memory_norm_items", "tags_json LONGTEXT NULL", "UPDATE novel_memory_norm_items SET tags_json = '[]' WHERE tags_json IS NULL"),
        ("novel_memory_norm_items", "source_chapter_no INTEGER DEFAULT 0", None),
        ("novel_memory_norm_items", "last_seen_chapter_no INTEGER DEFAULT 0", None),
        ("novel_memory_norm_pets", "aliases_json LONGTEXT NULL", "UPDATE novel_memory_norm_pets SET aliases_json = '[]' WHERE aliases_json IS NULL"),
        ("novel_memory_norm_pets", "tags_json LONGTEXT NULL", "UPDATE novel_memory_norm_pets SET tags_json = '[]' WHERE tags_json IS NULL"),
        ("novel_memory_norm_pets", "source_chapter_no INTEGER DEFAULT 0", None),
        ("novel_memory_norm_pets", "last_seen_chapter_no INTEGER DEFAULT 0", None),
        ("novel_memory_norm_characters", "aliases_json LONGTEXT NULL", "UPDATE novel_memory_norm_characters SET aliases_json = '[]' WHERE aliases_json IS NULL"),
        ("novel_memory_norm_characters", "tags_json LONGTEXT NULL", "UPDATE novel_memory_norm_characters SET tags_json = '[]' WHERE tags_json IS NULL"),
        ("novel_memory_norm_characters", "source_chapter_no INTEGER DEFAULT 0", None),
        ("novel_memory_norm_characters", "last_seen_chapter_no INTEGER DEFAULT 0", None),
        ("novel_memory_norm_relations", "detail_json LONGTEXT NULL", "UPDATE novel_memory_norm_relations SET detail_json = '{}' WHERE detail_json IS NULL"),
        ("novel_memory_norm_relations", "source_chapter_no INTEGER DEFAULT 0", None),
        ("novel_memory_norm_relations", "last_seen_chapter_no INTEGER DEFAULT 0", None),
        ("novel_memory_norm_plots", "related_entities_json LONGTEXT NULL", "UPDATE novel_memory_norm_plots SET related_entities_json = '[]' WHERE related_entities_json IS NULL"),
        ("novel_memory_norm_chapters", "scene_facts_json LONGTEXT NULL", "UPDATE novel_memory_norm_chapters SET scene_facts_json = '[]' WHERE scene_facts_json IS NULL"),
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
            elif dialect == "mysql":
                for table, ddl, backfill_sql in mysql_specs:
                    col = ddl.split()[0]
                    if _has_column_mysql(conn, table, col):
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                    if backfill_sql:
                        conn.execute(text(backfill_sql))
                    logger.info("db migrate: added %s.%s (mysql)", table, col)
            else:
                logger.warning(
                    "db migrate: ensure_story_bible_columns unsupported dialect=%s",
                    dialect,
                )
    except Exception:
        logger.exception("db migrate: ensure_story_bible_columns failed")


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
            elif dialect == "mysql":
                for table, ddl in pg_specs:
                    col = ddl.split()[0]
                    if _has_column_mysql(conn, table, col):
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                    logger.info("db migrate: added %s.%s (mysql)", table, col)
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
            elif dialect == "mysql":
                for c in cols:
                    if _has_column_mysql(conn, "novel_memory_norm_outline", c):
                        # MySQL DROP NOT NULL is MODIFY
                        conn.execute(
                            text(
                                f"ALTER TABLE novel_memory_norm_outline MODIFY {c} TEXT NULL"
                            )
                        )
                        logger.info("db migrate: relaxed novel_memory_norm_outline.%s (mysql)", c)
            elif dialect == "sqlite":
                # SQLite 不支持直接 DROP NOT NULL，且我们不再向这些列写数据，
                # 如果是新创建的表，这些列根本不存在；如果是旧表，SQLite 默认允许 NULL（除非显式指定）。
                # 实际上 SQLite 的 ALTER TABLE 限制很多，通常需要重建表。
                # 鉴于报错主要发生在 Postgres，SQLite 暂时跳过。
                pass
    except Exception:
        logger.exception("db migrate: relax_novel_memory_norm_columns failed")


def ensure_model_price_split_columns(engine: Engine) -> None:
    """补齐 ModelPrice 的输入输出单价列。"""
    specs = [
        ("model_prices", "prompt_price_cny_per_million_tokens FLOAT DEFAULT 1.0"),
        ("model_prices", "completion_price_cny_per_million_tokens FLOAT DEFAULT 1.0"),
    ]
    try:
        with engine.begin() as conn:
            dialect = engine.dialect.name
            for table, ddl in specs:
                col = ddl.split()[0]
                exists = False
                if dialect == "sqlite":
                    exists = _has_column_sqlite(conn, table, col)
                elif dialect == "mysql":
                    exists = _has_column_mysql(conn, table, col)
                elif dialect in ("postgresql", "postgres"):
                    exists = _has_column_postgres(conn, table, col)

                if not exists:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                    # 同步旧的通用价格到新列
                    conn.execute(text(f"UPDATE {table} SET {col} = price_cny_per_million_tokens"))
                    logger.info("db migrate: added %s.%s (%s)", table, col, dialect)
    except Exception:
        logger.exception("db migrate: ensure_model_price_split_columns failed")


def ensure_user_config_columns(engine: Engine) -> None:
    """补齐 User 表个性化 LLM 配置列。"""
    specs = [
        ("users", "llm_model VARCHAR(255) DEFAULT ''"),
        ("users", "novel_web_search BOOLEAN DEFAULT 0"),
        ("users", "novel_generate_web_search BOOLEAN DEFAULT 0"),
        ("users", "novel_volume_plan_web_search BOOLEAN DEFAULT 0"),
        ("users", "novel_memory_refresh_web_search BOOLEAN DEFAULT 0"),
        ("users", "novel_inspiration_web_search BOOLEAN DEFAULT 1"),
    ]
    try:
        with engine.begin() as conn:
            dialect = engine.dialect.name
            for table, ddl in specs:
                col = ddl.split()[0]
                exists = False
                if dialect == "sqlite":
                    exists = _has_column_sqlite(conn, table, col)
                elif dialect == "mysql":
                    exists = _has_column_mysql(conn, table, col)
                elif dialect in ("postgresql", "postgres"):
                    exists = _has_column_postgres(conn, table, col)

                if not exists:
                    # 对于非 SQLite，DEFAULT 0/1 会自动转为 FALSE/TRUE
                    if dialect in ("postgresql", "postgres") and "BOOLEAN" in ddl:
                        ddl = ddl.replace("DEFAULT 0", "DEFAULT FALSE").replace("DEFAULT 1", "DEFAULT TRUE")
                    
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                    logger.info("db migrate: added %s.%s (%s)", table, col, dialect)
    except Exception:
        logger.exception("db migrate: ensure_user_config_columns failed")


def ensure_writing_style_id_column(engine: Engine) -> None:
    """补齐 Novel 表 writing_style_id 列。"""
    table = "novels"
    col = "writing_style_id"
    ddl = "VARCHAR(36) NULL"

    try:
        with engine.begin() as conn:
            dialect = engine.dialect.name
            exists = False
            if dialect == "sqlite":
                exists = _has_column_sqlite(conn, table, col)
            elif dialect == "mysql":
                exists = _has_column_mysql(conn, table, col)
            elif dialect in ("postgresql", "postgres"):
                exists = _has_column_postgres(conn, table, col)

            if not exists:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                logger.info("db migrate: added %s.%s (%s)", table, col, dialect)
    except Exception:
        logger.exception("db migrate: ensure_writing_style_id_column failed")


def ensure_item_skill_lifecycle_columns(engine: Engine) -> None:
    """补齐 NovelMemoryNormItem / NovelMemoryNormSkill 的引入/过期追踪列。"""
    sqlite_alters: list[tuple[str, str]] = [
        ("novel_memory_norm_items", "introduced_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_items", "last_used_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_items", "expired_chapter INTEGER DEFAULT NULL"),
        ("novel_memory_norm_skills", "introduced_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_skills", "last_used_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_skills", "expired_chapter INTEGER DEFAULT NULL"),
    ]
    pg_alters: list[tuple[str, str]] = [
        ("novel_memory_norm_items", "introduced_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_items", "last_used_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_items", "expired_chapter INTEGER DEFAULT NULL"),
        ("novel_memory_norm_skills", "introduced_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_skills", "last_used_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_skills", "expired_chapter INTEGER DEFAULT NULL"),
    ]
    try:
        with engine.begin() as conn:
            dialect = engine.dialect.name
            alters = sqlite_alters if dialect == "sqlite" else pg_alters
            for table, ddl in alters:
                col = ddl.split()[0]
                exists = False
                if dialect == "sqlite":
                    exists = _has_column_sqlite(conn, table, col)
                elif dialect == "mysql":
                    exists = _has_column_mysql(conn, table, col)
                elif dialect in ("postgresql", "postgres"):
                    exists = _has_column_postgres(conn, table, col)
                if exists:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                logger.info("db migrate: added %s.%s (%s)", table, col, dialect)
    except Exception:
        logger.exception("db migrate: ensure_item_skill_lifecycle_columns failed")


def ensure_volume_outline_columns(engine: Engine) -> None:
    """补齐 novel_volumes 表 outline_json / outline_markdown 列。"""
    table = "novel_volumes"
    sqlite_specs = [
        ("outline_json", "TEXT DEFAULT '{}'"),
        ("outline_markdown", "TEXT DEFAULT ''"),
    ]
    pg_specs = [
        ("outline_json", "TEXT DEFAULT '{}'"),
        ("outline_markdown", "TEXT DEFAULT ''"),
    ]
    try:
        with engine.begin() as conn:
            dialect = engine.dialect.name
            if dialect == "mysql":
                # 与 ORM LONGTEXT 一致；避免 TEXT + DEFAULT 在部分 MySQL 配置下 ALTER 失败被静默跳过
                for col in ("outline_json", "outline_markdown"):
                    if _has_column_mysql(conn, table, col):
                        continue
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {col} LONGTEXT NULL")
                    )
                    logger.info("db migrate: added %s.%s (mysql)", table, col)
                if _has_column_mysql(conn, table, "outline_json"):
                    conn.execute(
                        text(
                            f"UPDATE {table} SET outline_json = '{{}}' "
                            "WHERE outline_json IS NULL OR outline_json = ''"
                        )
                    )
                if _has_column_mysql(conn, table, "outline_markdown"):
                    conn.execute(
                        text(
                            f"UPDATE {table} SET outline_markdown = '' "
                            "WHERE outline_markdown IS NULL"
                        )
                    )
                return

            specs = sqlite_specs if dialect == "sqlite" else pg_specs
            for col, ddl in specs:
                exists = False
                if dialect == "sqlite":
                    exists = _has_column_sqlite(conn, table, col)
                elif dialect in ("postgresql", "postgres"):
                    exists = _has_column_postgres(conn, table, col)
                else:
                    logger.warning(
                        "db migrate: ensure_volume_outline_columns unsupported dialect=%s",
                        dialect,
                    )
                    return
                if exists:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                logger.info("db migrate: added %s.%s (%s)", table, col, dialect)
    except Exception:
        logger.exception("db migrate: ensure_volume_outline_columns failed")


def ensure_novel_entity_state_machine_columns(engine: Engine) -> None:
    """核心升级：规范化记忆生命周期 + 关系端点 + novels 表现力开关。"""
    sqlite_specs: list[tuple[str, str]] = [
        ("novel_memory_norm_skills", "lifecycle_state VARCHAR(32) DEFAULT 'usable'"),
        ("novel_memory_norm_items", "lifecycle_state VARCHAR(32) DEFAULT 'usable'"),
        ("novel_memory_norm_pets", "introduced_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_pets", "expired_chapter INTEGER DEFAULT NULL"),
        ("novel_memory_norm_pets", "lifecycle_state VARCHAR(32) DEFAULT 'usable'"),
        ("novel_memory_norm_characters", "introduced_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_characters", "expired_chapter INTEGER DEFAULT NULL"),
        ("novel_memory_norm_characters", "identity_stage VARCHAR(64) DEFAULT 'public'"),
        ("novel_memory_norm_characters", "exposed_identity_level VARCHAR(32) DEFAULT '0'"),
        ("novel_memory_norm_characters", "lifecycle_state VARCHAR(32) DEFAULT 'usable'"),
        ("novel_memory_norm_relations", "src_entity_id VARCHAR(36) DEFAULT NULL"),
        ("novel_memory_norm_relations", "dst_entity_id VARCHAR(36) DEFAULT NULL"),
        ("novel_memory_norm_chapters", "state_snapshot_json TEXT DEFAULT '{}'"),
        ("novel_memory_norm_chapters", "state_transition_summary_json TEXT DEFAULT '[]'"),
        ("novels", "auto_expressive_enhance BOOLEAN DEFAULT 0"),
    ]
    pg_specs: list[tuple[str, str]] = [
        ("novel_memory_norm_skills", "lifecycle_state VARCHAR(32) DEFAULT 'usable'"),
        ("novel_memory_norm_items", "lifecycle_state VARCHAR(32) DEFAULT 'usable'"),
        ("novel_memory_norm_pets", "introduced_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_pets", "expired_chapter INTEGER DEFAULT NULL"),
        ("novel_memory_norm_pets", "lifecycle_state VARCHAR(32) DEFAULT 'usable'"),
        ("novel_memory_norm_characters", "introduced_chapter INTEGER DEFAULT 0"),
        ("novel_memory_norm_characters", "expired_chapter INTEGER DEFAULT NULL"),
        ("novel_memory_norm_characters", "identity_stage VARCHAR(64) DEFAULT 'public'"),
        ("novel_memory_norm_characters", "exposed_identity_level VARCHAR(32) DEFAULT '0'"),
        ("novel_memory_norm_characters", "lifecycle_state VARCHAR(32) DEFAULT 'usable'"),
        ("novel_memory_norm_relations", "src_entity_id VARCHAR(36) DEFAULT NULL"),
        ("novel_memory_norm_relations", "dst_entity_id VARCHAR(36) DEFAULT NULL"),
        ("novel_memory_norm_chapters", "state_snapshot_json TEXT DEFAULT '{}'"),
        ("novel_memory_norm_chapters", "state_transition_summary_json TEXT DEFAULT '[]'"),
        ("novels", "auto_expressive_enhance BOOLEAN DEFAULT FALSE"),
    ]
    mysql_specs: list[tuple[str, str, str | None]] = [
        ("novel_memory_norm_skills", "lifecycle_state VARCHAR(32) DEFAULT 'usable'", None),
        ("novel_memory_norm_items", "lifecycle_state VARCHAR(32) DEFAULT 'usable'", None),
        ("novel_memory_norm_pets", "introduced_chapter INTEGER DEFAULT 0", None),
        ("novel_memory_norm_pets", "expired_chapter INTEGER DEFAULT NULL", None),
        ("novel_memory_norm_pets", "lifecycle_state VARCHAR(32) DEFAULT 'usable'", None),
        ("novel_memory_norm_characters", "introduced_chapter INTEGER DEFAULT 0", None),
        ("novel_memory_norm_characters", "expired_chapter INTEGER DEFAULT NULL", None),
        ("novel_memory_norm_characters", "identity_stage VARCHAR(64) DEFAULT 'public'", None),
        ("novel_memory_norm_characters", "exposed_identity_level VARCHAR(32) DEFAULT '0'", None),
        ("novel_memory_norm_characters", "lifecycle_state VARCHAR(32) DEFAULT 'usable'", None),
        ("novel_memory_norm_relations", "src_entity_id VARCHAR(36) DEFAULT NULL", None),
        ("novel_memory_norm_relations", "dst_entity_id VARCHAR(36) DEFAULT NULL", None),
        (
            "novel_memory_norm_chapters",
            "state_snapshot_json LONGTEXT NULL",
            "UPDATE novel_memory_norm_chapters SET state_snapshot_json = '{}' WHERE state_snapshot_json IS NULL",
        ),
        (
            "novel_memory_norm_chapters",
            "state_transition_summary_json LONGTEXT NULL",
            "UPDATE novel_memory_norm_chapters SET state_transition_summary_json = '[]' WHERE state_transition_summary_json IS NULL",
        ),
        ("novels", "auto_expressive_enhance BOOLEAN DEFAULT FALSE", None),
    ]
    try:
        with engine.begin() as conn:
            dialect = engine.dialect.name
            if dialect == "mysql":
                for table, ddl, post_sql in mysql_specs:
                    col = ddl.split()[0]
                    if _has_column_mysql(conn, table, col):
                        if post_sql:
                            conn.execute(text(post_sql))
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                    if post_sql:
                        conn.execute(text(post_sql))
                    logger.info("db migrate: added %s.%s (mysql)", table, col)
                return
            specs = sqlite_specs if dialect == "sqlite" else pg_specs
            for table, ddl in specs:
                col = ddl.split()[0]
                exists = False
                if dialect == "sqlite":
                    exists = _has_column_sqlite(conn, table, col)
                elif dialect in ("postgresql", "postgres"):
                    exists = _has_column_postgres(conn, table, col)
                else:
                    logger.warning(
                        "db migrate: ensure_novel_entity_state_machine_columns unsupported dialect=%s",
                        dialect,
                    )
                    return
                if exists:
                    continue
                if dialect in ("postgresql", "postgres") and "BOOLEAN" in ddl and "novels" in table:
                    ddl = ddl.replace("BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT FALSE")
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                logger.info("db migrate: added %s.%s (%s)", table, col, dialect)
    except Exception:
        logger.exception("db migrate: ensure_novel_entity_state_machine_columns failed")

-- StoryForge / VocalFlow 后端 MySQL 初始化脚本
-- 由 SQLAlchemy 模型编译生成，与 backend/app/models 保持一致。
-- 用法：mysql -h HOST -u USER -p < sql/mysql_init.sql
-- 可修改下方库名；若库已存在可删掉 CREATE DATABASE / USE 两行，在目标库内执行。
-- 仅建议在空库上执行一次。

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

CREATE DATABASE IF NOT EXISTS vocalflow CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE vocalflow;


CREATE TABLE agent_configs ( id VARCHAR(36) NOT NULL, node_type VARCHAR(64) NOT NULL, config_json TEXT NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id) );

CREATE TABLE app_config ( id VARCHAR(36) NOT NULL, llm_provider VARCHAR(32) NOT NULL, llm_model VARCHAR(255) NOT NULL, novel_web_search BOOL NOT NULL, novel_generate_web_search BOOL NOT NULL, novel_volume_plan_web_search BOOL NOT NULL, novel_memory_refresh_web_search BOOL NOT NULL, novel_inspiration_web_search BOOL NOT NULL, invite_only_registration BOOL NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id) );

CREATE TABLE media_assets ( id VARCHAR(36) NOT NULL, kind VARCHAR(32) NOT NULL, url VARCHAR(2048) NOT NULL, workflow_id VARCHAR(36), created_at DATETIME NOT NULL, PRIMARY KEY (id) );

CREATE TABLE model_prices ( id VARCHAR(36) NOT NULL, model_id VARCHAR(128) NOT NULL, price_cny_per_million_tokens FLOAT NOT NULL, prompt_price_cny_per_million_tokens FLOAT NOT NULL, completion_price_cny_per_million_tokens FLOAT NOT NULL, enabled BOOL NOT NULL, display_name VARCHAR(256) NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id) );

CREATE TABLE users ( id VARCHAR(36) NOT NULL, username VARCHAR(64) NOT NULL, email VARCHAR(255) NOT NULL, hashed_password VARCHAR(255) NOT NULL, points_balance INTEGER NOT NULL, is_admin BOOL NOT NULL, is_frozen BOOL NOT NULL, frozen_reason TEXT NOT NULL, frozen_at DATETIME, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, llm_model VARCHAR(255) NOT NULL, novel_web_search BOOL NOT NULL, novel_generate_web_search BOOL NOT NULL, novel_volume_plan_web_search BOOL NOT NULL, novel_memory_refresh_web_search BOOL NOT NULL, novel_inspiration_web_search BOOL NOT NULL, PRIMARY KEY (id) );

CREATE TABLE invite_codes ( id VARCHAR(36) NOT NULL, code VARCHAR(64) NOT NULL, created_by_admin_id VARCHAR(36) NOT NULL, expires_at DATETIME, is_frozen BOOL NOT NULL, used_by_user_id VARCHAR(36), used_at DATETIME, note TEXT NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(created_by_admin_id) REFERENCES users (id), FOREIGN KEY(used_by_user_id) REFERENCES users (id) );

CREATE TABLE novels ( id VARCHAR(36) NOT NULL, user_id VARCHAR(36), title VARCHAR(512) NOT NULL, intro TEXT NOT NULL, background TEXT NOT NULL, style VARCHAR(255) NOT NULL, target_chapters INTEGER NOT NULL, target_word_count INTEGER NOT NULL, daily_auto_chapters INTEGER NOT NULL, daily_auto_time VARCHAR(16) NOT NULL, chapter_target_words INTEGER NOT NULL, auto_consistency_check BOOL NOT NULL, auto_plan_guard_check BOOL NOT NULL, auto_plan_guard_fix BOOL NOT NULL, auto_style_polish BOOL NOT NULL, last_auto_date VARCHAR(10) NOT NULL, reference_storage_key VARCHAR(1024) NOT NULL, reference_public_url VARCHAR(2048) NOT NULL, reference_filename VARCHAR(512) NOT NULL, framework_json TEXT NOT NULL, framework_markdown TEXT NOT NULL, framework_confirmed BOOL NOT NULL, status VARCHAR(32) NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(user_id) REFERENCES users (id) );

CREATE TABLE points_transactions ( id VARCHAR(36) NOT NULL, user_id VARCHAR(36) NOT NULL, amount_points INTEGER NOT NULL, transaction_type VARCHAR(32) NOT NULL, note TEXT NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(user_id) REFERENCES users (id) );

CREATE TABLE recharge_orders ( id VARCHAR(36) NOT NULL, user_id VARCHAR(36) NOT NULL, channel VARCHAR(16) NOT NULL, out_trade_no VARCHAR(64) NOT NULL, amount_cny INTEGER NOT NULL, points INTEGER NOT NULL, status VARCHAR(32) NOT NULL, trade_status VARCHAR(32) NOT NULL, alipay_trade_no VARCHAR(64) NOT NULL, notify_raw TEXT NOT NULL, query_raw TEXT NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, paid_at DATETIME, credited_at DATETIME, notified_at DATETIME, reconciled_at DATETIME, PRIMARY KEY (id), FOREIGN KEY(user_id) REFERENCES users (id) );

CREATE TABLE token_usages ( id VARCHAR(36) NOT NULL, user_id VARCHAR(36) NOT NULL, model_id VARCHAR(128) NOT NULL, prompt_tokens INTEGER NOT NULL, completion_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL, cost_points INTEGER NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(user_id) REFERENCES users (id) );

CREATE TABLE workflows ( id VARCHAR(36) NOT NULL, user_id VARCHAR(36), name VARCHAR(255) NOT NULL, nodes_json TEXT NOT NULL, edges_json TEXT NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(user_id) REFERENCES users (id) );

CREATE TABLE novel_chapters ( id VARCHAR(36) NOT NULL, novel_id VARCHAR(36) NOT NULL, chapter_no INTEGER NOT NULL, title VARCHAR(512) NOT NULL, content TEXT NOT NULL, pending_content TEXT NOT NULL, pending_revision_prompt TEXT NOT NULL, status VARCHAR(32) NOT NULL, source VARCHAR(32) NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(novel_id) REFERENCES novels (id) );

CREATE TABLE novel_generation_logs ( id VARCHAR(36) NOT NULL, novel_id VARCHAR(36) NOT NULL, batch_id VARCHAR(64) NOT NULL, level VARCHAR(16) NOT NULL, event VARCHAR(64) NOT NULL, chapter_no INTEGER, message TEXT NOT NULL, meta_json TEXT NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(novel_id) REFERENCES novels (id) );

CREATE TABLE novel_memories ( id VARCHAR(36) NOT NULL, novel_id VARCHAR(36) NOT NULL, version INTEGER NOT NULL, payload_json TEXT NOT NULL, summary TEXT NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(novel_id) REFERENCES novels (id) );

CREATE TABLE novel_memory_norm_chapters ( id VARCHAR(36) NOT NULL, novel_id VARCHAR(36) NOT NULL, memory_version INTEGER NOT NULL, chapter_no INTEGER NOT NULL, chapter_title VARCHAR(512) NOT NULL, key_facts_json TEXT NOT NULL, causal_results_json TEXT NOT NULL, open_plots_added_json TEXT NOT NULL, open_plots_resolved_json TEXT NOT NULL, emotional_state TEXT NOT NULL, unresolved_hooks_json TEXT NOT NULL, PRIMARY KEY (id), FOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE CASCADE );

CREATE TABLE novel_memory_norm_characters ( id VARCHAR(36) NOT NULL, novel_id VARCHAR(36) NOT NULL, memory_version INTEGER NOT NULL, sort_order INTEGER NOT NULL, name VARCHAR(512) NOT NULL, `role` VARCHAR(512) NOT NULL, status VARCHAR(512) NOT NULL, traits_json TEXT NOT NULL, detail_json TEXT NOT NULL, influence_score INTEGER NOT NULL, is_active BOOL NOT NULL, PRIMARY KEY (id), FOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE CASCADE );

CREATE TABLE novel_memory_norm_items ( id VARCHAR(36) NOT NULL, novel_id VARCHAR(36) NOT NULL, memory_version INTEGER NOT NULL, sort_order INTEGER NOT NULL, label TEXT NOT NULL, detail_json TEXT NOT NULL, influence_score INTEGER NOT NULL, is_active BOOL NOT NULL, PRIMARY KEY (id), FOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE CASCADE );

CREATE TABLE novel_memory_norm_outline ( novel_id VARCHAR(36) NOT NULL, memory_version INTEGER NOT NULL, main_plot TEXT NOT NULL, timeline_archive_json TEXT NOT NULL, forbidden_constraints_json TEXT NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (novel_id), FOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE CASCADE );

CREATE TABLE novel_memory_norm_pets ( id VARCHAR(36) NOT NULL, novel_id VARCHAR(36) NOT NULL, memory_version INTEGER NOT NULL, sort_order INTEGER NOT NULL, name VARCHAR(512) NOT NULL, detail_json TEXT NOT NULL, influence_score INTEGER NOT NULL, is_active BOOL NOT NULL, PRIMARY KEY (id), FOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE CASCADE );

CREATE TABLE novel_memory_norm_plots ( id VARCHAR(36) NOT NULL, novel_id VARCHAR(36) NOT NULL, memory_version INTEGER NOT NULL, sort_order INTEGER NOT NULL, body TEXT NOT NULL, plot_type VARCHAR(32) NOT NULL, priority INTEGER NOT NULL, estimated_duration INTEGER NOT NULL, current_stage TEXT NOT NULL, resolve_when TEXT NOT NULL, introduced_chapter INTEGER NOT NULL, last_touched_chapter INTEGER NOT NULL, PRIMARY KEY (id), FOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE CASCADE );

CREATE TABLE novel_memory_norm_relations ( id VARCHAR(36) NOT NULL, novel_id VARCHAR(36) NOT NULL, memory_version INTEGER NOT NULL, sort_order INTEGER NOT NULL, src VARCHAR(512) NOT NULL, dst VARCHAR(512) NOT NULL, relation TEXT NOT NULL, is_active BOOL NOT NULL, PRIMARY KEY (id), FOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE CASCADE );

CREATE TABLE novel_memory_norm_skills ( id VARCHAR(36) NOT NULL, novel_id VARCHAR(36) NOT NULL, memory_version INTEGER NOT NULL, sort_order INTEGER NOT NULL, name VARCHAR(512) NOT NULL, detail_json TEXT NOT NULL, influence_score INTEGER NOT NULL, is_active BOOL NOT NULL, PRIMARY KEY (id), FOREIGN KEY(novel_id) REFERENCES novels (id) ON DELETE CASCADE );

CREATE TABLE novel_volumes ( id VARCHAR(36) NOT NULL, novel_id VARCHAR(36) NOT NULL, volume_no INTEGER NOT NULL, title VARCHAR(512) NOT NULL, summary TEXT NOT NULL, from_chapter INTEGER NOT NULL, to_chapter INTEGER NOT NULL, status VARCHAR(32) NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(novel_id) REFERENCES novels (id) );

CREATE TABLE projects ( id VARCHAR(36) NOT NULL, user_id VARCHAR(36), name VARCHAR(255) NOT NULL, workflow_id VARCHAR(36), created_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(user_id) REFERENCES users (id), FOREIGN KEY(workflow_id) REFERENCES workflows (id) );

CREATE TABLE novel_chapter_feedback ( id VARCHAR(36) NOT NULL, chapter_id VARCHAR(36) NOT NULL, body TEXT NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(chapter_id) REFERENCES novel_chapters (id) );

CREATE TABLE novel_chapter_plans ( id VARCHAR(36) NOT NULL, novel_id VARCHAR(36) NOT NULL, volume_id VARCHAR(36) NOT NULL, chapter_no INTEGER NOT NULL, chapter_title VARCHAR(512) NOT NULL, beats_json TEXT NOT NULL, open_plots_intent_added_json TEXT NOT NULL, open_plots_intent_resolved_json TEXT NOT NULL, status VARCHAR(32) NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(novel_id) REFERENCES novels (id), FOREIGN KEY(volume_id) REFERENCES novel_volumes (id) );

CREATE UNIQUE INDEX ix_model_prices_model_id ON model_prices (model_id);
CREATE UNIQUE INDEX ix_users_username ON users (username);
CREATE UNIQUE INDEX ix_users_email ON users (email);
CREATE INDEX ix_invite_codes_used_by_user_id ON invite_codes (used_by_user_id);
CREATE INDEX ix_invite_codes_created_by_admin_id ON invite_codes (created_by_admin_id);
CREATE UNIQUE INDEX ix_invite_codes_code ON invite_codes (code);
CREATE INDEX ix_novels_user_id ON novels (user_id);
CREATE INDEX ix_points_transactions_user_id ON points_transactions (user_id);
CREATE UNIQUE INDEX ix_recharge_orders_out_trade_no ON recharge_orders (out_trade_no);
CREATE INDEX ix_recharge_orders_user_id ON recharge_orders (user_id);
CREATE INDEX ix_token_usages_user_id ON token_usages (user_id);
CREATE INDEX ix_workflows_user_id ON workflows (user_id);
CREATE INDEX ix_novel_generation_logs_batch_id ON novel_generation_logs (batch_id);
CREATE INDEX ix_novel_generation_logs_created_at ON novel_generation_logs (created_at);
CREATE INDEX ix_novel_generation_logs_novel_id ON novel_generation_logs (novel_id);
CREATE INDEX ix_novel_memory_norm_chapters_novel_id ON novel_memory_norm_chapters (novel_id);
CREATE INDEX ix_novel_memory_norm_characters_novel_id ON novel_memory_norm_characters (novel_id);
CREATE INDEX ix_novel_memory_norm_items_novel_id ON novel_memory_norm_items (novel_id);
CREATE INDEX ix_novel_memory_norm_pets_novel_id ON novel_memory_norm_pets (novel_id);
CREATE INDEX ix_novel_memory_norm_plots_novel_id ON novel_memory_norm_plots (novel_id);
CREATE INDEX ix_novel_memory_norm_relations_novel_id ON novel_memory_norm_relations (novel_id);
CREATE INDEX ix_novel_memory_norm_skills_novel_id ON novel_memory_norm_skills (novel_id);
CREATE INDEX ix_novel_volumes_from_chapter ON novel_volumes (from_chapter);
CREATE INDEX ix_novel_volumes_novel_id ON novel_volumes (novel_id);
CREATE INDEX ix_novel_volumes_volume_no ON novel_volumes (volume_no);
CREATE INDEX ix_novel_volumes_to_chapter ON novel_volumes (to_chapter);
CREATE INDEX ix_projects_user_id ON projects (user_id);
CREATE INDEX ix_novel_chapter_plans_volume_id ON novel_chapter_plans (volume_id);
CREATE INDEX ix_novel_chapter_plans_chapter_no ON novel_chapter_plans (chapter_no);
CREATE INDEX ix_novel_chapter_plans_novel_id ON novel_chapter_plans (novel_id);

SET FOREIGN_KEY_CHECKS = 1;

INSERT INTO app_config (
  id, llm_provider, llm_model,
  novel_web_search, novel_generate_web_search, novel_volume_plan_web_search,
  novel_memory_refresh_web_search, novel_inspiration_web_search,
  invite_only_registration, updated_at
) VALUES (
  'global', 'ai302', '',
  0, 0, 0, 0, 1,
  1, NOW(6)
) ON DUPLICATE KEY UPDATE id = id;

-- 管理员：请用应用注册首个用户，或使用 Python 生成 bcrypt 哈希后插入 users（勿存明文密码）。

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "StoryForge API"
    database_url: str = "sqlite:///./vocalflow.db"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    seedance_api_key: str = ""
    azure_speech_key: str = ""

    # 302.AI 中转（OpenAI 兼容 Chat / TTS 等，见 https://doc.302.ai/ ）
    ai302_base_url: str = "https://api.302ai.cn/v1"
    ai302_api_key: str = ""
    # 兼容旧 .env；运行时 Chat 不再回退到这两项，须配置「模型计价」与全站 LLM
    ai302_chat_model: str = "Doubao-Seed-2.0-pro"
    ai302_novel_model: str = "Doubao-Seed-2.0-pro"
    # 小说相关请求是否开启 302「联网搜索」（文档 https://doc.302.ai/260112819e0 ）
    ai302_novel_web_search: bool = True
    # 语音：常用为 OpenAI 兼容 POST /audio/speech；或按控制台填完整路径
    ai302_tts_path: str = "/audio/speech"
    ai302_tts_model: str = "tts-1"
    # 视频：不同套餐路径不同，留空则仅走占位 + Celery 状态
    ai302_video_submit_path: str = ""

    # 全局默认（仅新建 app_config 行时的初始值；实际以 DB app_config + 模型计价为准）
    llm_provider: str = "ai302"
    llm_model: str = ""

    # 阿里云 OSS（凭证用环境变量 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET，见官方文档）
    oss_region: str = ""
    oss_bucket: str = ""
    oss_endpoint: str = ""
    oss_public_base_url: str = ""

    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
    # 1 元人民币 = 多少积分（扣费换算）
    points_per_cny: int = 10
    # 新注册用户赠送积分（生产可改为 0，由充值获得）
    register_initial_points: int = 100

    # 邮箱配置
    mail_server: str = "smtp.163.com"
    mail_port: int = 465
    mail_username: str = ""  # 从 .env 读取
    mail_password: str = ""  # 从 .env 读取（授权码）
    mail_from: str = ""      # 从 .env 读取
    mail_use_tls: bool = False
    mail_use_ssl: bool = True
    otp_expire_minutes: int = 10

    alipay_gateway_url: str = "https://openapi.alipay.com/gateway.do"
    alipay_app_id: str = ""
    alipay_private_key_path: str = ""
    alipay_public_key_path: str = ""
    alipay_return_url: str = ""
    alipay_notify_url: str = ""
    alipay_seller_id: str = ""
    alipay_sign_type: str = "RSA2"
    alipay_reconcile_enabled: bool = False
    alipay_reconcile_interval_minutes: int = 5
    alipay_reconcile_min_age_minutes: int = 2
    alipay_reconcile_lookback_hours: int = 24

    # 小说模块
    reference_txt_max_bytes: int = 15 * 1024 * 1024  # 15MB
    novel_local_upload_dir: str = "./uploads/novels"
    novel_rag_enabled: bool = True
    novel_story_bible_enabled: bool = True
    novel_workflow_v2_enabled: bool = True
    novel_judge_enabled: bool = True
    novel_qdrant_collection: str = "novel-memory"
    novel_embedding_dimension: int = 1536
    # hash | http（OpenAI 兼容 /embeddings，默认走 ai302_base_url + api_key）
    novel_embedding_provider: str = "http"
    novel_embedding_http_model: str = "text-embedding-3-small"
    novel_embedding_http_fallback: bool = False
    novel_embedding_http_batch_size: int = 32
    novel_embedding_http_timeout: float = 60.0
    novel_retrieval_top_k: int = 8
    novel_retrieval_timeout: float = 10.0
    # 多路子查询每路召回数、是否增量建索引、rerank
    novel_retrieval_incremental: bool = True
    novel_retrieval_per_branch_k: int = 4
    novel_retrieval_query_rewrite: bool = True
    novel_retrieval_rerank_enabled: bool = True
    novel_retrieval_mmr_lambda: float = 0.55
    novel_retrieval_chunk_max_chars: int = 880
    novel_retrieval_chunk_overlap: int = 100
    # 准图子图（Story Bible 最新快照 1~2 跳）注入写章上下文
    novel_quasi_graph_enabled: bool = True
    novel_quasi_graph_max_edges: int = 24
    # 表现力增强 pass（在一致性/执行卡之后、去 AI 味 style_polish 之前或并列由 novel 开关控制）
    novel_expressive_enhance_enabled: bool = False
    novel_expressive_enhance_strength: str = "safe"  # safe | strong | cinematic
    # 每日定时任务默认生成章节数（每本书可单独覆盖）
    novel_daily_default_chapters: int = 1
    # 全自动小说流水线的全局并发/排队软上限；超过后前端提示排队，接口拒绝继续入队
    novel_auto_pipeline_max_active: int = 5
    # Celery Beat：每日触发的小时（0-23，服务器本地时区）
    novel_beat_hour: int = 9
    novel_beat_minute: int = 0
    # 单章生成：传给 OpenAI 兼容接口的 max_tokens（豆包等未显式传时网关默认可能偏小，导致篇幅不足）
    novel_chapter_max_tokens: int = 8192
    # 大纲生成：同时要求 Markdown + 结构化 JSON，输出体量远大于单章，预算需显著放大
    novel_framework_max_tokens: int = 24576
    # 单章正文生成超时（秒）
    novel_chapter_timeout: float = 900.0
    # 一致性修订超时（秒）
    novel_consistency_check_timeout: float = 600.0
    # 审定章节摘要写入记忆时每章截取字数（越大越耗 token）
    novel_chapter_summary_chars: int = 3500
    # 内部：偏连续性时优先用章节结尾截取（默认 tail）
    novel_chapter_summary_mode: str = "tail"  # tail | head | both
    # tail/head 分别截取字数（用于 memory refresh 摘要合并）
    novel_chapter_summary_tail_chars: int = 3500
    novel_chapter_summary_head_chars: int = 3500
    # 刷新/合并时参与的最近已审定章节数量
    novel_memory_refresh_chapters: int = 15
    # 记忆热层：写章时注入的最近时间线条数（其余进入冷层）
    novel_timeline_hot_n: int = 20
    # 写章时注入的 open_plots 上限（超出部分仍保留在存储中）
    novel_open_plots_hot_max: int = 20
    # 写章时注入的人物状态上限（精简）
    novel_characters_hot_max: int = 12
    # 为 true 时 Beat 按下方钟点批量刷新所有书的记忆（需已有审定章节）
    novel_auto_refresh_memory: bool = False
    novel_memory_beat_hour: int = 10
    novel_memory_beat_minute: int = 30
    # 生成后一致性核对/自动修订：对长连载显著降低设定漂移
    novel_consistency_check_chapter: bool = True
    # 核对阶段使用较低温度，尽量做小幅修订
    novel_consistency_check_temperature: float = 0.25
    # 章计划分批生成：每批章节数（避免超时）
    novel_volume_plan_batch_size: int = 10
    # 单批 LLM 超时（秒）
    novel_volume_plan_batch_timeout: float = 480.0
    # AI 一键建书：头脑风暴（书名/简介/背景 JSON）单次请求超时（秒）
    novel_ai_create_brainstorm_timeout: float = 900.0
    # AI 一键建书头脑风暴：瞬时网络波动时的额外重试次数（总尝试次数=1+该值）
    novel_ai_create_brainstorm_max_retries: int = 0
    # AI 一键建书任务软超时（秒）：触发后会走失败收敛并提示用户
    novel_ai_create_task_soft_time_limit: int = 1500
    # AI 一键建书任务硬超时（秒）：超过后强制终止，避免长时间占用 worker
    novel_ai_create_task_time_limit: int = 1560
    # 记忆刷新分批：每批摘要最大字符数（0表示不分批）
    novel_memory_refresh_batch_chars: int = 15000
    # 记忆刷新单批超时（秒）
    novel_memory_refresh_batch_timeout: float = 600.0
    # 记忆增量抽取：单批返回 JSON 的 max_tokens
    novel_memory_delta_max_tokens: int = 4096
    # LLM 请求遇到 Timeout 时的额外重试次数
    novel_llm_timeout_retries: int = 1
    # LLM Timeout 重试前的基础退避秒数
    novel_llm_timeout_retry_backoff_seconds: float = 2.0
    # 写章时默认携带最近完整正文的章节数
    novel_recent_full_context_chapters: int = 2
    # 写章 prompt 的软预算（按字符近似）；超出后会优先裁剪最近正文与低优先级记忆块
    novel_prompt_char_budget: int = 42_000
    # 最近完整正文的总字符软上限（各章拼接后再二次裁剪）
    novel_recent_full_context_total_chars: int = 16_000
    # 写章时按实体召回的历史条目数上限
    novel_memory_entity_recall_max_items: int = 6
    # 审定前：用 LLM 审计正文是否违反 forbidden_constraints（关闭则不调用）
    novel_setting_audit_on_approve: bool = True
    # 审计发现冲突时是否直接拒绝审定（默认仅记录警告，不阻断）
    novel_setting_audit_block_on_violation: bool = False
    # 记忆压缩：每隔 N 章可将更早章节细节合并入 timeline_archive（0 表示仅手动触发）
    novel_memory_consolidate_every_n_chapters: int = 50
    # 线索超过预计持续章节数后，再额外宽限多少章才标记为 stale
    novel_open_plot_stale_grace_chapters: int = 3
    # 已收束剧情线日志保留：超过「当前最新章号 − 收束章号」则丢弃，避免列表无限增长
    novel_resolved_open_plots_log_retention_chapters: int = 20
    # 记忆校准：每隔 N 章对热层记忆做一次全量校准，修正 LLM 累积误差（0 表示关闭）
    novel_memory_calibration_interval: int = 10
    # 冷层 RAG 自动启用阈值：已审定章节数 ≥ 该值时自动开启冷层召回（0 表示始终关闭）
    novel_cold_recall_auto_threshold: int = 30


settings = Settings()

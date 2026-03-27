-- PostgreSQL 初始化参考（若使用 SQLAlchemy create_all 可跳过手工执行）
CREATE TABLE IF NOT EXISTS workflows (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL DEFAULT 'Untitled',
    nodes_json TEXT NOT NULL DEFAULT '[]',
    edges_json TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS projects (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    workflow_id VARCHAR(36) REFERENCES workflows(id),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

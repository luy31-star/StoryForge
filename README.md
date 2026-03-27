# VocalFlow Studio

AI 驱动的虚拟人歌唱视频创作平台：React Flow 工作流画布、多 Agent 节点、FastAPI 后端与 Gemini / SeeDance / 语音服务集成骨架。

## 目录结构

- `frontend/` — Vite + React 18 + TypeScript + Tailwind + React Flow + Zustand + TanStack Query
- `backend/` — FastAPI + SQLAlchemy + Redis/Celery 占位任务
- `database/` — SQL 参考脚本
- `docker/` — 开发与生产镜像

## 本地开发

### 后端

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # 按需填写密钥
uvicorn app.main:app --reload --port 8000
```

HTTP 详细请求日志由中间件写入 Logger **`vocalflow.request`**（含 `X-Request-Id`）；若与 Uvicorn access log 重复，可加 `--no-access-log`。

可选：在 `backend/` 下启动 Postgres/Redis：`docker compose -f docker-compose.yml up -d`

### 前端

```bash
cd frontend
npm install
npm run dev
```

浏览器访问 <http://localhost:3000>，工作流编辑器路径为 `/editor`。API 经 Vite 代理转发到 `http://127.0.0.1:8000`。

### Docker 全栈（生产向）

在项目根目录 `vocalflow-studio/`：

```bash
cp .env.example .env   # 填写 AI302_API_KEY 等
docker compose up --build -d
```

包含 **Postgres、Redis、FastAPI、Celery Worker、Celery Beat、Nginx 前端**（反代 `/api`、`/ws`，上传体上限约 18MB，小说参考 txt 单文件最大 15MB）。访问 <http://localhost:8080>，API 直连 <http://localhost:8000>。小说本地上传目录挂载卷 `novel_uploads`。

`docker-compose.yml` 中基础镜像默认使用 **`docker.m.daocloud.io/library/...`** 前缀拉取，减轻访问 Docker Hub 超时；若你所在网络能直连 Hub，可在根目录 `.env` 设置 `DOCKER_HUB_PREFIX=docker.io/library`。

开发组合（热更新前端 + 同上后端镜像 + Worker/Beat）：

```bash
cd docker && docker compose -f docker-compose.dev.yml up --build
```

### 环境变量（前端）

默认使用相对路径请求 `/api`，由 Vite 代理到后端。若需显式指定 API 根，可设置 `VITE_API_BASE`。

## 已实现（Phase 1 骨架）

- 工作流画布：节点拖拽、连线、MiniMap、内置「Gemini + SeeDance」模板
- 后端：`/api/workflow`、`/api/agents`（语音合成/融合、SeeDance 占位、Gemini 代理占位）、`/ws/workflow/{id}` WebSocket 回声
- 数据：`sqlite` 默认（可在 `.env` 中改为 PostgreSQL）

## 后续阶段

- 真实 SeeDance / Azure TTS 调用与 Celery 异步管线
- 工作流版本管理、用户认证、媒体存储（S3）
- WaveSurfer / Video.js 预览与质量控制 UI

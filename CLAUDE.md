# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VocalFlow Studio is an AI-driven virtual human singing video creation platform with a React Flow workflow canvas, multi-agent nodes, FastAPI backend, and integrations with Gemini, SeeDance, and voice synthesis services.

## Development Commands

### Backend (FastAPI)

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Configure API keys
uvicorn app.main:app --reload --port 8000
```

HTTP request logs are written to the `vocalflow.request` logger (includes `X-Request-Id`).

### Frontend (Vite + React)

```bash
cd frontend
npm install
npm run dev     # Development server on http://localhost:3000
npm run build   # Production build
npm run lint    # ESLint
```

The workflow editor is at path `/editor`. API requests are proxied to `http://127.0.0.1:8000` via Vite config.

### Docker (Full Stack)

```bash
# Production-like stack (Postgres, Redis, FastAPI, Celery Worker/Beat, Nginx frontend)
cp .env.example .env  # Configure AI302_API_KEY, etc.
docker compose up --build -d
# Access: http://localhost:8080, API: http://localhost:8000

# Development stack (hot-reload frontend + backend images)
cd docker && docker compose -f docker-compose.dev.yml up --build
```

Default image prefix is `docker.io/library/` (Docker Hub). For China mirrors, set `DOCKER_HUB_PREFIX=docker.m.daocloud.io/library` in `.env`.

### Celery Tasks

```bash
# Worker (from backend directory)
celery -A app.tasks.celery_app worker -l info -Q vocalflow,celery

# Beat (scheduler)
celery -A app.tasks.celery_app beat -l info
```

## Architecture

### Frontend Structure

- **Framework**: Vite + React 18 + TypeScript
- **State Management**: Zustand for workflow state, TanStack Query for server state
- **UI Components**: Radix UI primitives + Tailwind CSS + custom components
- **Workflow Canvas**: React Flow (`reactflow`) for node-based editor
- **Routing**: React Router DOM
- **Media**: WaveSurfer.js for audio, Video.js for video

Key stores:
- `stores/workflowStore.ts` - React Flow nodes/edges state
- `stores/novelStore.ts` - Novel writing module state

Key services:
- `services/api.ts` - API fetch wrapper with tracing

### Backend Structure

- **Framework**: FastAPI with SQLAlchemy ORM
- **Database**: Supports SQLite (dev) or PostgreSQL (production)
- **Task Queue**: Celery with Redis broker/backend
- **Storage**: Alibaba Cloud OSS (optional) or local filesystem

Module organization:
- `app/routers/` - API route handlers (workflow, agents, llm, media, novel, volume, websocket)
- `app/services/` - Business logic (workflow_engine, ai302_client, novel_llm_service, seedance_service, voice_service)
- `app/agents/` - Agent implementations (base_agent, input_agent, voice_agent, video_agent, merge_agent)
- `app/tasks/` - Celery async tasks (workflow_tasks, video_tasks, voice_tasks, novel_tasks)
- `app/models/` - SQLAlchemy ORM models (workflow, agent, novel, volume, media)
- `app/core/` - Config, database, security

### LLM Integration

The backend supports multiple LLM providers via the LLM router (`services/llm_router.py`):
- **302.AI** (`ai302`): OpenAI-compatible API for chat, TTS, and video generation
- **Custom proxy** (`custom`): Self-hosted OpenAI-compatible endpoints

Environment variables for 302.AI:
- `AI302_API_KEY`, `AI302_CHAT_MODEL`, `AI302_NOVEL_MODEL`, `AI302_TTS_PATH`, `AI302_VIDEO_SUBMIT_PATH`

### Novel Writing Module

A sophisticated novel generation system with:
- **Framework Management**: Target chapter counts, volume planning
- **Memory System**: Hot/cold layer architecture for timeline, plots, characters
- **Scheduled Generation**: Celery Beat auto-generates chapters daily
- **Consistency Checking**: Post-generation validation with configurable temperature

Key models:
- `novel` - Book metadata and memory
- `volume` - Volume/plan entities with framework/outline
- `target_chapters` - Daily generation targets per book

Key environment variables:
- `NOVEL_DAILY_DEFAULT_CHAPTERS` - Chapters to generate per day
- `NOVEL_BEAT_HOUR`/`NOVEL_BEAT_MINUTE` - Daily generation schedule
- `NOVEL_TIMELINE_HOT_N`/`NOVEL_OPEN_PLOTS_HOT_MAX`/`NOVEL_CHARACTERS_HOT_MAX` - Hot layer limits
- `NOVEL_MEMORY_REFRESH_CHAPTERS` - Chapters included in memory refresh

### Workflow Engine

Node-based workflow system:
- Nodes: Input, Voice, Video, Merge agents
- Execution via Celery tasks with WebSocket progress updates
- WebSocket endpoint: `/ws/workflow/{id}`

## Environment Configuration

Backend environment (`.env` in `backend/` or root):
- `DATABASE_URL` - `sqlite:///./vocalflow.db` (dev) or `postgresql://...` (prod)
- `REDIS_URL` - Redis connection string
- `AI302_API_KEY` - Required for AI features
- `OSS_*` - Alibaba Cloud OSS configuration (optional)
- `NOVEL_*` - Novel module configuration

Frontend environment:
- `VITE_API_BASE` - Optional explicit API base URL (defaults to relative `/api`)

## Key File Locations

- Frontend entry: `frontend/src/main.tsx`
- Backend entry: `backend/app/main.py`
- Celery app: `backend/app/tasks/celery_app.py`
- Database models: `backend/app/models/`
- API routes: `backend/app/routers/`
- Frontend pages: `frontend/src/pages/`
- Frontend components: `frontend/src/components/`

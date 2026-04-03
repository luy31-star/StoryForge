from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User

from app.services.gemini_service import GeminiService
from app.services.seedance_service import SeeDanceService
from app.services.voice_service import VoiceService

router = APIRouter(prefix="/api/agents", tags=["agents"])


class VoiceSettings(BaseModel):
    pitch: float = 1.0
    speed: float = 1.0
    emotion: str = "neutral"
    style: str = "default"


class VoiceSynthesisBody(BaseModel):
    text: str
    voice_model: str = "default"
    settings: VoiceSettings | None = None


class VoiceBlendBody(BaseModel):
    reference_voices: list[str]
    blend_ratios: list[float]
    target_text: str


class GeminiChatBody(BaseModel):
    systemPrompt: str | None = None
    messages: list[dict[str, str]]
    model: str | None = None


@router.post("/voice-synthesis")
async def synthesize_voice(
    body: VoiceSynthesisBody,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    voice_service = VoiceService()
    settings = body.settings.model_dump() if body.settings else {}
    result = await voice_service.synthesize(
        text=body.text,
        model=body.voice_model,
        voice_settings=settings,
    )
    return {"audio_url": result.url, "duration": result.duration}


@router.post("/voice-blend")
async def blend_voices(
    body: VoiceBlendBody,
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    voice_service = VoiceService()
    result = await voice_service.blend_voices(
        references=body.reference_voices,
        ratios=body.blend_ratios,
        text=body.target_text,
    )
    return {"blended_voice_url": result.url}


@router.post("/seedance-video")
async def generate_seedance_video(
    audio_file: UploadFile = File(...),
    character_image: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    seedance_service = SeeDanceService()
    task_id = await seedance_service.generate_video_async(
        audio=audio_file,
        image=character_image,
    )
    return {"task_id": task_id, "status": "processing"}


@router.get("/seedance-status/{task_id}")
async def seedance_status(
    task_id: str,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    svc = SeeDanceService()
    task = svc.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": task.get("status", "unknown"), **task}


@router.post("/gemini-chat")
async def gemini_chat(
    body: GeminiChatBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    gemini = GeminiService()
    text = await gemini.generate_text(
        system_prompt=body.systemPrompt,
        messages=body.messages,
        model=body.model or "gemini-2.0-flash",
        billing_db=db,
        billing_user_id=user.id,
    )
    return {"text": text}

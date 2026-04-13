from __future__ import annotations

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.writing_style_service import WritingStyleService

router = APIRouter(prefix="/api/writing-styles", tags=["writing-styles"])
logger = logging.getLogger(__name__)

class WritingStyleBase(BaseModel):
    name: str
    reference_author: Optional[str] = None
    lexicon: dict = Field(default_factory=dict)
    structure: dict = Field(default_factory=dict)
    tone: dict = Field(default_factory=dict)
    rhetoric: dict = Field(default_factory=dict)
    negative_prompts: List[str] = Field(default_factory=list)
    snippets: List[str] = Field(default_factory=list)

class WritingStyleCreate(WritingStyleBase):
    pass

class WritingStyleUpdate(BaseModel):
    name: Optional[str] = None
    reference_author: Optional[str] = None
    lexicon: Optional[dict] = None
    structure: Optional[dict] = None
    tone: Optional[dict] = None
    rhetoric: Optional[dict] = None
    negative_prompts: Optional[List[str]] = None
    snippets: Optional[List[str]] = None

class AnalyzeSnippetBody(BaseModel):
    text: str = Field(..., min_length=10)

class SearchAuthorBody(BaseModel):
    author: str = Field(..., min_length=1)

class FetchSnippetsBody(BaseModel):
    author: str = Field(..., min_length=1)
    works: List[str] = Field(..., min_length=1)

@router.post("")
def create_style(
    body: WritingStyleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = WritingStyleService(db, user.id)
    return service.create_style(body.name, body.model_dump(), body.reference_author)

@router.get("")
def list_styles(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = WritingStyleService(db, user.id)
    return service.list_styles()

@router.get("/{style_id}")
def get_style(
    style_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = WritingStyleService(db, user.id)
    style = service.get_style(style_id)
    if not style:
        raise HTTPException(404, "Style not found")
    return style

@router.patch("/{style_id}")
def update_style(
    style_id: str,
    body: WritingStyleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = WritingStyleService(db, user.id)
    try:
        return service.update_style(style_id, body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(404, str(e))

@router.delete("/{style_id}")
def delete_style(
    style_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = WritingStyleService(db, user.id)
    service.delete_style(style_id)
    return {"status": "ok"}

@router.post("/analyze-snippet")
async def analyze_snippet(
    body: AnalyzeSnippetBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = WritingStyleService(db, user.id)
    try:
        return await service.analyze_style_from_text(body.text)
    except Exception as e:
        raise HTTPException(500, f"Analysis failed: {e}")

@router.post("/search-author")
async def search_author(
    body: SearchAuthorBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = WritingStyleService(db, user.id)
    try:
        # 这个是旧的单步接口，为了兼容性保留
        return await service.search_author_style(body.author)
    except Exception as e:
        raise HTTPException(500, f"Search failed: {e}")

@router.post("/search-authors")
async def search_authors(
    body: SearchAuthorBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = WritingStyleService(db, user.id)
    try:
        # 这是分步接口的第一步：搜索作者列表
        return await service.search_authors(body.author)
    except Exception as e:
        raise HTTPException(500, f"Search failed: {e}")

@router.post("/fetch-snippets")
async def fetch_snippets(
    body: FetchSnippetsBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = WritingStyleService(db, user.id)
    try:
        # 这是分步接口的第二步：根据选定的作者和作品获取片段
        return await service.fetch_snippets(body.author, body.works)
    except Exception as e:
        raise HTTPException(500, f"Fetch failed: {e}")

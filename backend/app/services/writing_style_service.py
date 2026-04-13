from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.writing_style import WritingStyle
from app.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)

class WritingStyleService:
    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = user_id
        self.router = LLMRouter(user_id=user_id, db=db)

    async def analyze_style_from_text(self, text: str) -> Dict[str, Any]:
        """从提供的文本片段中提取文风特征。"""
        system_prompt = """你是一个顶级的文学评论家和文风分析专家。
请分析用户提供的文本片段，并提取其文风特征，输出为严格的 JSON 格式。
JSON 结构如下：
{
  "lexicon": {
    "tags": ["词汇标签1", "词汇标签2"],
    "rules": ["词汇使用规则1", "词汇使用规则2"],
    "forbidden": ["建议禁用的AI高频词或套话"]
  },
  "structure": {
    "sentence_length": 15, // 平均字数
    "complexity": "对句子复杂度的描述",
    "line_break": "对换行频率的描述",
    "punctuation": "对标点符号使用偏好的描述",
    "rules": ["结构方面的具体要求"]
  },
  "tone": {
    "primary": ["主要语气1", "主要语气2"],
    "description": "对整体语气的详细描述",
    "rules": ["语气方面的具体要求"]
  },
  "rhetoric": {
    "types": {"修辞手法1": "频率(高/中/低)", "修辞手法2": "频率"},
    "rules": ["修辞使用方面的具体要求"]
  },
  "negative_prompts": ["绝对禁止出现的表达方式或模板化句子"],
  "snippets": ["从原文中提取的1-2个最具代表性的短句或段落"]
}
"""
        user_prompt = f"请分析以下文本片段：\n\n{text}"
        
        try:
            response = await self.router.chat_text(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                billing_user_id=self.user_id,
                billing_db=self.db
            )
            return json.loads(response)
        except Exception as e:
            logger.exception("Failed to analyze style: %s", e)
            raise

    async def search_authors(self, query: str) -> List[Dict[str, Any]]:
        """搜索匹配的作者及其代表作。"""
        system_prompt = """你是一个文学百科专家。
请搜索并列出与“{query}”相关的网络文学或严肃文学作者。
输出为严格的 JSON 格式，包含一个 'authors' 键，其值为对象数组。
每个对象包含：
- name: 作者名
- works: 代表作列表（3-5部）
- description: 简短的作者介绍
"""
        user_prompt = f"请搜索与“{query}”相关的作者。"
        
        try:
            response = await self.router.chat_text(
                messages=[
                    {"role": "system", "content": system_prompt.format(query=query)},
                    {"role": "user", "content": user_prompt}
                ],
                web_search=True,
                response_format={"type": "json_object"},
                billing_user_id=self.user_id,
                billing_db=self.db
            )
            data = json.loads(response)
            return data.get("authors", [])
        except Exception as e:
            logger.exception("Failed to search authors: %s", e)
            return []

    async def fetch_snippets(self, author: str, works: List[str]) -> List[str]:
        """获取指定作者作品的代表性片段。"""
        system_prompt = """你是一个拥有联网能力的文学专家。
请为作者“{author}”的作品（{works_str}）搜索并提取 3-5 个最能体现其文风特色的经典片段。
要求：
1. 每个片段长度在 200-500 字之间。
2. 片段应包含典型的对话、环境描写或心理描写。
3. 必须是该作者真实的文字。
输出为严格的 JSON 格式，包含一个 'snippets' 键，其值为字符串数组。
"""
        works_str = "、".join(works)
        user_prompt = f"请提取作者“{author}”作品（{works_str}）的文风代表片段。"
        
        try:
            response = await self.router.chat_text(
                messages=[
                    {"role": "system", "content": system_prompt.format(author=author, works_str=works_str)},
                    {"role": "user", "content": user_prompt}
                ],
                web_search=True,
                response_format={"type": "json_object"},
                billing_user_id=self.user_id,
                billing_db=self.db
            )
            data = json.loads(response)
            return data.get("snippets", [])
        except Exception as e:
            logger.exception("Failed to fetch snippets: %s", e)
            return []

    async def search_author_style(self, author: str) -> Dict[str, Any]:
        """联网搜索指定作者的文风和代表作片段。"""
        system_prompt = """你是一个拥有联网能力的文学专家。
请搜索并分析作者“{author}”的写作风格，并提取其特征，输出为严格的 JSON 格式。
你需要查找：
1. 该作者的词汇习惯、句式结构、语气特色、修辞偏好。
2. 该作者最著名的 2-3 个写作片段。
JSON 结构与分析接口保持一致。
"""
        user_prompt = f"请搜索并分析作者“{author}”的文风及代表片段。"
        
        try:
            response = await self.router.chat_text(
                messages=[
                    {"role": "system", "content": system_prompt.format(author=author)},
                    {"role": "user", "content": user_prompt}
                ],
                web_search=True,
                response_format={"type": "json_object"},
                billing_user_id=self.user_id,
                billing_db=self.db
            )
            return json.loads(response)
        except Exception as e:
            logger.exception("Failed to search author style: %s", e)
            raise

    def create_style(self, name: str, data: Dict[str, Any], reference_author: Optional[str] = None) -> WritingStyle:
        style = WritingStyle(
            user_id=self.user_id,
            name=name,
            reference_author=reference_author,
            lexicon=data.get("lexicon", {}),
            structure=data.get("structure", {}),
            tone=data.get("tone", {}),
            rhetoric=data.get("rhetoric", {}),
            negative_prompts=data.get("negative_prompts", []),
            snippets=data.get("snippets", [])
        )
        self.db.add(style)
        self.db.commit()
        self.db.refresh(style)
        return style

    def update_style(self, style_id: str, data: Dict[str, Any]) -> WritingStyle:
        style = self.db.query(WritingStyle).filter(
            WritingStyle.id == style_id,
            WritingStyle.user_id == self.user_id
        ).first()
        if not style:
            raise ValueError("Style not found")
        
        if "name" in data:
            style.name = data["name"]
        if "reference_author" in data:
            style.reference_author = data["reference_author"]
        if "lexicon" in data:
            style.lexicon = data["lexicon"]
        if "structure" in data:
            style.structure = data["structure"]
        if "tone" in data:
            style.tone = data["tone"]
        if "rhetoric" in data:
            style.rhetoric = data["rhetoric"]
        if "negative_prompts" in data:
            style.negative_prompts = data["negative_prompts"]
        if "snippets" in data:
            style.snippets = data["snippets"]
            
        self.db.commit()
        self.db.refresh(style)
        return style

    def delete_style(self, style_id: str):
        style = self.db.query(WritingStyle).filter(
            WritingStyle.id == style_id,
            WritingStyle.user_id == self.user_id
        ).first()
        if style:
            self.db.delete(style)
            self.db.commit()

    def get_style(self, style_id: str) -> Optional[WritingStyle]:
        return self.db.query(WritingStyle).filter(
            WritingStyle.id == style_id,
            WritingStyle.user_id == self.user_id
        ).first()

    def list_styles(self) -> List[WritingStyle]:
        return self.db.query(WritingStyle).filter(
            WritingStyle.user_id == self.user_id
        ).order_by(WritingStyle.created_at.desc()).all()

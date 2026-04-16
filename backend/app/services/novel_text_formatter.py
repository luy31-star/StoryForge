from __future__ import annotations

import re


_HEADING_RE = re.compile(r"^第\s*\d+\s*章")
_DIALOGUE_START_RE = re.compile(r'^[“"「『]')
_SPEAKER_DIALOGUE_RE = re.compile(r'^[^，。！？；\s]{1,12}[：:][“"「『]')
_SCENE_SHIFT_RE = re.compile(
    r"^(这时|此时|忽然|突然|下一刻|片刻后|不多时|很快|紧接着|与此同时|另一边|次日|第二天|当晚|清晨|夜里|黎明时分)"
)
_SENTENCE_ENDERS = set("。！？!?；;…")
_QUOTE_CLOSERS = set('”’」』》）】')


def _compact_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def _normalize_block_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_sentences(block: str) -> list[str]:
    raw = _normalize_block_text(block)
    if not raw:
        return []

    out: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\n":
            if buf and buf[-1] != " ":
                buf.append(" ")
            i += 1
            continue

        buf.append(ch)
        if ch in _SENTENCE_ENDERS:
            j = i + 1
            while j < len(raw) and raw[j] in _QUOTE_CLOSERS:
                buf.append(raw[j])
                j += 1
            sentence = "".join(buf).strip()
            if sentence:
                out.append(sentence)
            buf = []
            i = j
            continue
        i += 1

    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def _is_dialogue_sentence(sentence: str) -> bool:
    s = sentence.strip()
    return bool(_DIALOGUE_START_RE.match(s) or _SPEAKER_DIALOGUE_RE.match(s))


def _is_scene_shift_sentence(sentence: str) -> bool:
    return bool(_SCENE_SHIFT_RE.match(sentence.strip()))


def _flush_paragraph(paragraphs: list[str], current: list[str]) -> None:
    text = "".join(current).strip()
    if text:
        paragraphs.append(text)
    current.clear()


def _paragraphize_blocks(blocks: list[str]) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    current_chars = 0
    current_sentences = 0

    for block in blocks:
        sentences = _split_sentences(block)
        if not sentences:
            continue
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            is_dialogue = _is_dialogue_sentence(sentence)
            is_scene_shift = _is_scene_shift_sentence(sentence)

            if current and (is_scene_shift or (is_dialogue and current_sentences >= 1)):
                _flush_paragraph(paragraphs, current)
                current_chars = 0
                current_sentences = 0

            current.append(sentence)
            current_chars += _compact_len(sentence)
            current_sentences += 1

            if is_dialogue:
                _flush_paragraph(paragraphs, current)
                current_chars = 0
                current_sentences = 0
                continue

            if current_sentences >= 3 or current_chars >= 120:
                _flush_paragraph(paragraphs, current)
                current_chars = 0
                current_sentences = 0

        if current:
            _flush_paragraph(paragraphs, current)
            current_chars = 0
            current_sentences = 0

    return paragraphs


def format_novel_text(content: str) -> dict[str, int | str]:
    raw = _normalize_block_text(content)
    if not raw:
        return {
            "formatted_content": "",
            "before_paragraphs": 0,
            "after_paragraphs": 0,
            "body_chars": 0,
        }

    lines = raw.splitlines()
    heading = lines[0].strip() if lines and _HEADING_RE.match(lines[0].strip()) else ""
    body = "\n".join(lines[1:]).strip() if heading else raw

    before_paragraphs = len([line for line in body.splitlines() if line.strip()])
    blocks = [part.strip() for part in re.split(r"\n\s*\n+", body) if part.strip()]
    paragraphs = _paragraphize_blocks(blocks)
    formatted_body = "\n\n".join(paragraphs).strip()
    formatted_content = f"{heading}\n\n{formatted_body}".strip() if heading else formatted_body

    return {
        "formatted_content": formatted_content,
        "before_paragraphs": before_paragraphs,
        "after_paragraphs": len(paragraphs),
        "body_chars": _compact_len(formatted_body),
    }

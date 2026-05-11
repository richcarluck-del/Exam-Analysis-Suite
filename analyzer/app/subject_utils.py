from __future__ import annotations

from typing import Optional


_SUBJECT_ALIAS_TO_CANONICAL = {
    "math": "数学",
    "mathematics": "数学",
    "数学": "数学",
    "chinese": "语文",
    "language": "语文",
    "语文": "语文",
    "english": "英语",
    "英语": "英语",
    "physics": "物理",
    "物理": "物理",
    "chemistry": "化学",
    "化学": "化学",
    "biology": "生物",
    "生物": "生物",
    "history": "历史",
    "历史": "历史",
    "geography": "地理",
    "地理": "地理",
    "politics": "政治",
    "political": "政治",
    "政治": "政治",
}


def normalize_subject(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return _SUBJECT_ALIAS_TO_CANONICAL.get(text.lower(), text)

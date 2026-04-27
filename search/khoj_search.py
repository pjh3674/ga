"""
Khoj 검색 모듈 — GA 토론봇용
vm109:42110의 Obsidian 노트 + 예산 문서를 검색해 토론 근거로 제공.
"""

from __future__ import annotations

import re
import requests

KHOJ_URL = "http://vm109:42110"

_SESSION = requests.Session()
_SESSION.headers.update({"Content-Type": "application/json"})


def khoj_search(query: str, limit: int = 5, timeout: int = 15) -> list[dict]:
    """Khoj 전문 검색. 반환: [{"entry": str, "score": float, "file": str}, ...]"""
    try:
        resp = _SESSION.get(
            f"{KHOJ_URL}/api/search",
            params={"q": query, "limit": limit},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("results", [])
    except Exception as e:
        return [{"entry": f"[Khoj 검색 실패: {e}]", "score": 0.0, "file": ""}]


def format_khoj_results(results: list[dict], max_chars: int = 2000) -> str:
    """검색 결과를 토론 컨텍스트 블록으로 변환."""
    if not results:
        return ""
    parts = []
    total = 0
    for i, r in enumerate(results, 1):
        entry = r.get("entry", "") or r.get("compiled", "")
        entry = re.sub(r"^---.*?---\s*", "", entry, flags=re.DOTALL).strip()
        src = r.get("file", "") or r.get("path", "")
        line = f"[근거{i}] {entry[:400]}"
        if src:
            line += f"\n출처: {src}"
        total += len(line)
        if total > max_chars:
            break
        parts.append(line)
    header = "### Khoj 내 문서 검색 결과\n"
    return header + "\n\n".join(parts)

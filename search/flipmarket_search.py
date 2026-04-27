"""
Flipmarket API 연동 — 토론 주제 관련 예측 시장 확률을 컨텍스트로 주입.

환경변수 FLIPMARKET_API_KEY 필요.
"""
from __future__ import annotations

import os
import requests
from typing import Any

FLIPMARKET_API_KEY = os.environ.get("FLIPMARKET_API_KEY", "")
FLIPMARKET_API_URL = "https://api.flipmarket.com/v1/markets/search"


def flipmarket_search(query: str, count: int = 5) -> list[dict]:
    """
    Flipmarket API로 예측 시장 검색. 결과 리스트 반환.
    각 항목: {"title": str, "url": str, "probability": float, "description": str}
    """
    if not FLIPMARKET_API_KEY:
        return [{"title": "검색 불가", "url": "", "description": "FLIPMARKET_API_KEY가 설정되지 않았습니다.", "probability": 0.0}]
    headers = {
        "Authorization": f"Bearer {FLIPMARKET_API_KEY}",
        "Accept": "application/json",
    }
    params = {"q": query, "limit": count}
    try:
        r = requests.get(FLIPMARKET_API_URL, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        results = []
        for item in data.get("markets", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "probability": item.get("probability", 0.0),
                "description": item.get("description", ""),
            })
        return results
    except Exception as e:
        return [{"title": "검색 실패", "url": "", "description": str(e), "probability": 0.0}]


def format_flipmarket_results(results: list[dict]) -> str:
    """
    Flipmarket 검색 결과를 에이전트 컨텍스트용 문자열로 변환.
    """
    if not results:
        return ""
    lines = ["### Flipmarket 예측 시장 결과"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r['title']}** (확률: {r['probability']*100:.1f}%)")
        if r["description"]:
            lines.append(f"   {r['description'][:200]}")
        if r["url"]:
            lines.append(f"   출처: {r['url']}")
    return "\n".join(lines)

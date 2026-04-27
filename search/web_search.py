from __future__ import annotations

import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
if not BRAVE_API_KEY:
    import warnings
    warnings.warn("BRAVE_API_KEY 환경변수가 설정되지 않았습니다. 웹 검색이 비활성화됩니다.", stacklevel=1)
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


def brave_search(query: str, count: int = 5) -> list[dict]:
    """
    Brave Search API 호출. 결과 리스트 반환.
    각 항목: {"title": str, "url": str, "description": str}
    """
    if not BRAVE_API_KEY:
        return [{"title": "검색 불가", "url": "", "description": "BRAVE_API_KEY가 설정되지 않았습니다."}]
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    }
    params = {"q": query, "count": count, "text_decorations": False}
    try:
        r = requests.get(BRAVE_SEARCH_URL, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
            })
        return results
    except Exception as e:
        return [{"title": "검색 실패", "url": "", "description": str(e)}]


def format_search_results(results: list[dict]) -> str:
    """검색 결과를 에이전트 컨텍스트용 문자열로 변환."""
    if not results:
        return ""
    lines = ["### 웹 검색 결과"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r['title']}**")
        if r["description"]:
            lines.append(f"   {r['description'][:200]}")
        if r["url"]:
            lines.append(f"   출처: {r['url']}")
    return "\n".join(lines)


def brave_search_evidence_pack(query: str, count: int = 8) -> str:
    """
    웹 검색 결과를 Evidence Pack 형식으로 반환한다.
    - 중복 도메인 제거 (도메인당 2개 이하)
    - confirmed_facts / disputed_points / key_sources 섹션으로 구조화
    토론 에이전트 컨텍스트 품질을 높이기 위한 함수.
    """
    results = brave_search(query, count=count)
    if not results or (len(results) == 1 and not results[0].get("url")):
        return ""

    # 중복 도메인 필터 (같은 도메인 최대 2개)
    from urllib.parse import urlparse
    domain_count: dict[str, int] = {}
    deduped: list[dict] = []
    for r in results:
        url = r.get("url", "")
        try:
            domain = urlparse(url).netloc.lower().replace("www.", "")
        except Exception:
            domain = url
        if domain_count.get(domain, 0) < 2:
            deduped.append(r)
            domain_count[domain] = domain_count.get(domain, 0) + 1

    # 섹션 분류: 설명이 있는 것은 사실/쟁점, 없는 것은 출처만
    confirmed_facts: list[str] = []
    key_sources:     list[str] = []

    for r in deduped:
        title = r.get("title", "")
        desc  = r.get("description", "").strip()
        url   = r.get("url", "")
        if desc:
            confirmed_facts.append(f"- **{title}**: {desc[:250]}")
        if url:
            key_sources.append(f"  - [{title}]({url})")

    lines = ["### 웹 검색 Evidence Pack"]
    if confirmed_facts:
        lines.append("\n**수집된 사실 / 주요 정보**")
        lines.extend(confirmed_facts[:6])
    if key_sources:
        lines.append("\n**출처 목록**")
        lines.extend(key_sources[:8])
    lines.append(
        "\n> 위 정보를 토론 근거로 적극 활용하되, "
        "불확실한 내용은 팩트체커가 별도 검증해야 합니다."
    )
    return "\n".join(lines)

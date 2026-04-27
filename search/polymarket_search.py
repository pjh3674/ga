"""
Polymarket Gamma API 연동 — 토론 주제 관련 예측 시장 확률을 컨텍스트로 주입.

공개 Gamma API 사용 (인증 불필요). 결과를 debate.py의 context_block에 포함.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"
GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"
_HEADERS = {"User-Agent": "GA-DebateBot/1.0", "Accept": "application/json"}
_FETCH_LIMIT = 200  # 클라이언트 필터링을 위해 충분히 가져옴
_TOP_K = 5          # 최종 컨텍스트에 포함할 최대 마켓 수
_MIN_VOLUME = 5000  # 볼륨 하한 필터 (너무 작은 마켓 제외)


def _fetch(url: str) -> Any:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _keyword_score(text: str, keywords: list[str]) -> int:
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw in text_lower)


def _extract_keywords(topic: str) -> list[str]:
    """토론 주제에서 검색 키워드 추출 (불용어 제거)."""
    stopwords = {
        # 한국어 조사·어미
        "은", "는", "이", "가", "을", "를", "의", "에", "와", "과",
        "하는", "해야", "인가", "것인가", "것은", "한다", "됩니다",
        "대한", "위한", "통한", "있는", "없는", "되는", "하고",
        # 영어 불용어 (단음절 포함)
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "will", "would", "should", "could", "can", "may", "might",
        "for", "of", "in", "to", "and", "or", "that", "this",
        "it", "its", "by", "at", "on", "do", "did", "has", "have",
        "new", "old", "big", "more", "most", "any", "all", "no",
        "not", "with", "from", "as", "if", "us", "we",
    }
    # 영어는 4자 이상, 한국어는 2자 이상
    tokens = re.findall(r"[가-힣]{2,}|[a-zA-Z]{4,}", topic.lower())
    return [t for t in tokens if t not in stopwords]


def _format_market(m: dict) -> str:
    question = m.get("question", "")
    outcomes_raw = m.get("outcomes", [])
    prices_raw = m.get("outcomePrices", [])
    if isinstance(outcomes_raw, str):
        outcomes_raw = json.loads(outcomes_raw)
    if isinstance(prices_raw, str):
        prices_raw = json.loads(prices_raw)

    pairs = []
    for outcome, price in zip(outcomes_raw, prices_raw):
        try:
            pct = round(float(price) * 100, 1)
            pairs.append(f"{outcome} {pct}%")
        except (ValueError, TypeError):
            pass

    vol = m.get("volumeNum", m.get("volume", 0))
    try:
        vol_str = f"${float(vol):,.0f}"
    except (ValueError, TypeError):
        vol_str = "N/A"

    outcome_str = " | ".join(pairs) if pairs else "N/A"
    return f"- **{question}**\n  확률: {outcome_str}  거래량: {vol_str}"


def search_polymarket(topic: str, top_k: int = _TOP_K) -> str:
    """
    토론 주제와 관련된 Polymarket 예측 시장을 검색해 포맷된 컨텍스트 문자열 반환.
    관련 마켓이 없거나 오류 시 빈 문자열 반환.
    """
    keywords = _extract_keywords(topic)
    if not keywords:
        return ""

    try:
        # 활성 마켓 상위 볼륨 순 가져오기
        url = f"{GAMMA_MARKETS_URL}?active=true&closed=false&limit={_FETCH_LIMIT}"
        markets: list[dict] = _fetch(url)
    except Exception as e:
        return f"[Polymarket 검색 실패: {e}]"

    # 클라이언트사이드 키워드 매칭 + 볼륨 필터
    scored = []
    for m in markets:
        vol = m.get("volumeNum", 0)
        try:
            if float(vol) < _MIN_VOLUME:
                continue
        except (ValueError, TypeError):
            continue

        question = m.get("question", "")
        desc = m.get("description", "")
        score = _keyword_score(question + " " + desc, keywords)
        if score > 0:
            scored.append((score, float(vol), m))

    if not scored:
        return ""

    # score 내림차순, 동점이면 볼륨 내림차순
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    top_markets = [m for _, _, m in scored[:top_k]]

    lines = ["### 📊 Polymarket 예측 시장 (관련 마켓 현황)"]
    lines.extend(_format_market(m) for m in top_markets)
    lines.append(f"\n_출처: Polymarket Gamma API (2026-04-25 기준 활성 마켓)_")
    return "\n".join(lines)

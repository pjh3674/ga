from __future__ import annotations

import os
import re
import time
import requests

RAG_API_BASE = "http://172.17.0.1:8400"

# ── 파일명 패턴에서 메타 자동 추출 ─────────────────────────────────────────────
# 예: "/nas/budget_chunks/[2026예산](연안이용·개발) 국민들의 주요_020.md"
#       → year=2026, doc_type=예산, section=연안이용·개발, chunk_no=020
_BRACKET_TAG_RE = re.compile(r"\[(\d{4})([가-힣A-Za-z]+)\]")     # [2026예산]
_PAREN_SECTION_RE = re.compile(r"\(([^)]+)\)")                    # (연안이용·개발)
_CHUNK_NO_RE = re.compile(r"_(\d{3,4})\.(?:md|txt|json)$")       # _020.md

def _enrich_metadata_from_source(source: str) -> dict:
    """파일경로/파일명에서 year, doc_type, section, chunk_no 추출."""
    extra: dict[str, str] = {}
    if not source:
        return extra
    name = source.rsplit("/", 1)[-1]
    if (m := _BRACKET_TAG_RE.search(name)):
        extra["year"], extra["doc_type"] = m.group(1), m.group(2)
    if (m := _PAREN_SECTION_RE.search(name)):
        extra["section"] = m.group(1)
    if (m := _CHUNK_NO_RE.search(name)):
        extra["chunk_no"] = m.group(1)
    return extra

# ── Archived 문서 필터링 캐시 ────────────────────────────────────────────────
# hwp-rag /query는 where 절을 지원하지 않아 사후 필터링한다.
# 컬렉션별 archived 파일경로 set을 짧은 TTL로 캐싱하여 매 검색마다 GET하지 않음.
_ARCHIVED_TTL_SEC = 60
_archived_cache: dict[str, tuple[float, set[str]]] = {}

def _get_archived_set(collection: str) -> set[str]:
    """주어진 컬렉션의 archived 파일경로 집합. TTL 캐시."""
    now = time.time()
    cached = _archived_cache.get(collection)
    if cached and now - cached[0] < _ARCHIVED_TTL_SEC:
        return cached[1]
    try:
        r = requests.get(f"{RAG_API_BASE}/list_archived",
                         params={"collection": collection}, timeout=5)
        r.raise_for_status()
        data = r.json()
        items = data.get("archived", []) or []
        # items 원소가 dict({filepath:...}) 또는 str 모두 허용
        paths: set[str] = set()
        for it in items:
            if isinstance(it, dict):
                fp = it.get("filepath") or it.get("source") or it.get("path")
                if fp:
                    paths.add(fp)
            elif isinstance(it, str):
                paths.add(it)
        _archived_cache[collection] = (now, paths)
        return paths
    except Exception:
        # 실패 시 빈 set로 캐싱하지 않음 (다음 호출에서 재시도)
        return set()


def _invalidate_archived_cache(collection: str | None = None) -> None:
    """archive/unarchive 직후 호출해 다음 검색에 즉시 반영."""
    if collection:
        _archived_cache.pop(collection, None)
    else:
        _archived_cache.clear()


def list_archived_docs(collection: str) -> list[dict]:
    """hwp-rag /list_archived를 그대로 노출. 실패 시 [] 반환."""
    try:
        r = requests.get(f"{RAG_API_BASE}/list_archived",
                         params={"collection": collection}, timeout=8)
        r.raise_for_status()
        data = r.json()
        items = data.get("archived", []) or []
        # 통일된 dict 형태로 정규화
        normalized: list[dict] = []
        for it in items:
            if isinstance(it, dict):
                normalized.append({
                    "filepath": it.get("filepath") or it.get("source") or it.get("path") or "",
                    "title": it.get("title") or "",
                    "chunk_count": int(it.get("chunk_count") or it.get("count") or 0),
                })
            elif isinstance(it, str):
                normalized.append({"filepath": it, "title": "", "chunk_count": 0})
        return normalized
    except Exception:
        return []


def set_archived(collection: str, filepath: str, archived: bool) -> tuple[bool, str]:
    """hwp-rag /archive_doc 호출. (ok, error_message)."""
    try:
        r = requests.post(
            f"{RAG_API_BASE}/archive_doc",
            json={"collection": collection, "filepath": filepath, "archived": archived},
            timeout=10,
        )
        if r.status_code in (200, 201, 204):
            _invalidate_archived_cache(collection)
            return True, ""
        return False, f"status={r.status_code} body={r.text[:200]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

# ── Cross-encoder rerank (LLM 기반, sentence-transformers 불필요) ─────────────

def _rerank_with_llm(query: str, results: list[dict], top_k: int) -> list[dict]:
    """
    LLM에게 쿼리-청크 관련도 점수(0~10)를 매기게 하여 재정렬.
    API 호출 실패 시 원래 순서 그대로 반환.
    """
    if len(results) <= 1:
        return results
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL

        snippets = "\n\n".join(
            f"[{i}] {r.get('content','')[:300]}"
            for i, r in enumerate(results)
        )
        prompt = (
            f"쿼리: {query}\n\n"
            f"아래 {len(results)}개 문서 각각의 쿼리 관련도를 0~10 정수로 평가하라.\n"
            f"출력 형식(한 줄에 하나씩): 인덱스:점수  예) 0:8\n\n{snippets}"
        )
        resp = requests.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={
                "model": "google/gemini-3-flash-preview",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 64,
            },
            timeout=10,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        scores: dict[int, int] = {}
        for line in text.splitlines():
            line = line.strip()
            if ":" in line:
                parts = line.split(":")
                try:
                    idx, score = int(parts[0].strip()), int(parts[1].strip())
                    scores[idx] = score
                except ValueError:
                    pass
        if scores:
            ranked = sorted(
                enumerate(results),
                key=lambda x: scores.get(x[0], 0),
                reverse=True,
            )
            reranked = [r for _, r in ranked[:top_k]]
            for i, r in enumerate(reranked, 1):
                r["_ref_id"] = f"근거{i}"
                r["_rerank_score"] = scores.get(ranked[i - 1][0], 0)
            return reranked
    except Exception:
        pass
    return results[:top_k]

def rag_search(query: str, collection: str = "budget", count: int = 5,
               rerank: bool = False, include_archived: bool = False) -> list[dict]:
    """
    ChromaDB RAG API 호출.
    rerank=True 시 LLM cross-encoder로 결과 재정렬.
    include_archived=False(기본) 시 hwp-rag에서 archived 처리된 문서를 결과에서 제외.
    반환: [{"content": "...", "metadata": {...}, "score": ..., "_ref_id": "근거N"}]
    """
    url = f"{RAG_API_BASE}/query"
    # archived 제외를 사후 필터로 처리하므로, 여유 있게 더 많이 받아옴
    fetch_limit = count * 2 if not include_archived else count
    payload = {
        "question": query,
        "collection": collection,
        "limit": fetch_limit,
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        # /query 응답: {"answer": "...", "sources": [...], "chunks_used": N}
        # sources를 개별 결과로 변환하고, answer는 첫 번째 항목의 content로 포함
        answer  = data.get("answer", "")
        sources = data.get("sources", [])
        if not answer:
            return []
        # archived 사후 필터링
        if not include_archived and sources:
            archived = _get_archived_set(collection)
            if archived:
                sources = [s for s in sources if s not in archived]
        # 에이전트가 인용할 수 있도록 출처별 결과 목록 구성
        if sources:
            results = []
            for i, src in enumerate(sources):
                meta = {"source": src, "filename": src.split("/")[-1]}
                meta.update(_enrich_metadata_from_source(src))
                results.append({
                    "content":  answer,
                    "metadata": meta,
                    "_ref_id":  f"근거{i+1}",
                })
        else:
            results = [{"content": answer, "metadata": {}, "_ref_id": "근거1"}]
        if rerank and len(results) > 1:
            results = _rerank_with_llm(query, results, top_k=count)
        return results[:count]
    except Exception as e:
        print(f"[RAG 검색 실패] {e}")
        return []


def format_rag_results(results: list[dict], collection_name: str = "예산") -> str:
    """
    RAG 결과를 에이전트 컨텍스트용 문자열로 변환.
    출처 메타데이터(파일명, 페이지, 표번호 등)를 포함하여 근거 추적을 지원한다.
    에이전트는 답변 시 [근거N] 태그로 인용해야 한다.
    """
    if not results:
        return ""

    lines = [
        f"[{collection_name} 실무 데이터 검색 결과]",
        "※ 아래 근거를 인용할 때는 반드시 [근거N] 태그를 사용하라.",
        "",
    ]
    for item in results:
        ref_id  = item.get("_ref_id", "근거?")
        content = item.get("content", "")
        meta    = item.get("metadata", {})

        # 출처 정보 최대한 상세하게 추출
        source   = meta.get("source") or meta.get("path") or meta.get("file") or "출처 불명"
        page     = meta.get("page") or meta.get("page_number") or ""
        table_id = meta.get("table_id") or meta.get("table") or ""
        chunk_id = meta.get("chunk_id") or meta.get("id") or ""
        section  = meta.get("section") or meta.get("chapter") or ""
        year     = meta.get("year") or ""
        doc_type = meta.get("doc_type") or ""
        chunk_no = meta.get("chunk_no") or ""

        # 출처 라벨 조립
        source_parts = [str(source)]
        if year and doc_type:
            source_parts.append(f"{year}{doc_type}")
        if page:
            source_parts.append(f"p.{page}")
        if table_id:
            source_parts.append(f"표{table_id}")
        if section:
            source_parts.append(str(section))
        if chunk_no:
            source_parts.append(f"청크#{chunk_no}")
        source_label = " / ".join(source_parts)

        lines.append(f"[{ref_id}] {content[:350]}")
        lines.append(f"   📎 출처: {source_label}")
        if chunk_id:
            lines.append(f"   🔖 청크ID: {chunk_id}")
        lines.append("")

    return "\n".join(lines)


def format_rag_citations(results: list[dict]) -> str:
    """
    보고서 하단 참고문헌 목록 생성용.
    반환: 마크다운 형식의 참고 출처 목록
    """
    if not results:
        return ""
    lines = ["### 📚 참고 출처"]
    for item in results:
        ref_id  = item.get("_ref_id", "근거?")
        meta    = item.get("metadata", {})
        source  = meta.get("source") or meta.get("path") or "출처 불명"
        page    = meta.get("page") or ""
        table_id = meta.get("table_id") or ""
        entry = f"- [{ref_id}] `{source}`"
        if page:
            entry += f" p.{page}"
        if table_id:
            entry += f" 표{table_id}"
        lines.append(entry)
    return "\n".join(lines)


# ── Phase 3: 정제소 전용 RAG 컬렉션 ─────────────────────────────────────────

def wisdom_search(query: str, top_k: int = 5, filters: dict | None = None,
                  rerank: bool = True) -> list[dict]:
    """
    Wisdom RAG: NAS 기존 보고서·심의자료 인덱스에서 검색.
    컬렉션명: wisdom_base
    rerank=True(기본값)로 LLM 재정렬 적용.
    """
    results = rag_search(query, collection="wisdom_base", count=top_k * 2 if rerank else top_k,
                         rerank=False)
    if filters and results:
        for key, val in filters.items():
            results = [r for r in results if r.get("metadata", {}).get(key) == val]
    if rerank and results:
        results = _rerank_with_llm(query, results, top_k=top_k)
    return results


def alignment_search(query: str, top_k: int = 3) -> list[dict]:
    """
    상위계획 정렬 RAG: 국정과제·업무보고·기본계획 컬렉션에서 검색.
    컬렉션명: alignment_base
    """
    return rag_search(query, collection="alignment_base", count=top_k)


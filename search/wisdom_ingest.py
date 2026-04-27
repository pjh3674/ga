"""
wisdom_ingest.py — Wisdom RAG 및 상위계획 정렬 지식베이스 인덱싱 스크립트 (Phase 3)

사용법:
  # wisdom_base 구축 (NAS 기존 보고서)
  python3 wisdom_ingest.py --collection wisdom_base --dir /mnt/nas/88.작업

  # alignment_base 구축 (국정과제·업무보고 등 수동 관리 문서)
  python3 wisdom_ingest.py --collection alignment_base --dir /mnt/nas/00.상위계획

  # 특정 파일만 인덱싱
  python3 wisdom_ingest.py --collection wisdom_base --file /mnt/nas/88.작업/검토보고서_예시.md

  # 인덱싱된 목록 확인
  python3 wisdom_ingest.py --list --collection wisdom_base

ChromaDB API: http://172.17.0.1:8400
지원 형식: .txt, .md (직접) / .pdf (pymupdf 또는 pdfminer 필요) / .hwp (hwpx2md 변환 결과 재사용)
"""
from __future__ import annotations

import os
import sys
import json
import hashlib
import logging
import argparse
import datetime
import unicodedata
from pathlib import Path
from typing import Generator

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

RAG_API_BASE = "http://172.17.0.1:8400"
CHUNK_SIZE   = 600   # 한글 기준 약 600자/청크
CHUNK_OVERLAP = 80   # 청크 간 중복 (컨텍스트 연속성)

# LLM 요약 추출 설정
SUMMARY_MAX_CHARS = 4000   # 요약 대상 원문 최대 글자 (API 비용 절감)
SUMMARY_ENABLED  = True    # --no-summary 플래그로 비활성화 가능

# 기본 탐색 경로 (--dir 미지정 시)
DEFAULT_WISDOM_DIRS = [
    "/mnt/nas/88.작업",
    "/mnt/nas/02예산자료",
]
DEFAULT_ALIGNMENT_DIRS = [
    "/mnt/nas/00.상위계획",  # 국정과제, 업무보고 등 수동 관리 폴더
]

# 인덱싱 대상 확장자
SUPPORTED_EXTS = {".txt", ".md"}
try:
    import fitz  # pymupdf
    SUPPORTED_EXTS.add(".pdf")
    _HAS_PYMUPDF = True
except ImportError:
    _HAS_PYMUPDF = False


# ── 텍스트 추출 ──────────────────────────────────────────────────────────────

def _extract_text(file_path: Path) -> str:
    """파일에서 텍스트 추출."""
    suffix = file_path.suffix.lower()
    try:
        if suffix in (".txt", ".md"):
            return file_path.read_text(encoding="utf-8", errors="ignore")
        elif suffix == ".pdf" and _HAS_PYMUPDF:
            doc = fitz.open(str(file_path))
            return "\n".join(page.get_text() for page in doc)
        else:
            log.warning(f"지원하지 않는 형식: {file_path.name}")
            return ""
    except Exception as e:
        log.error(f"텍스트 추출 실패 {file_path}: {e}")
        return ""


def _infer_doc_type(file_path: Path) -> str:
    """파일명·경로에서 문서 유형 추정."""
    name = file_path.name.lower()
    if any(k in name for k in ["국감", "국정감사", "질의", "답변"]):
        return "국감"
    if any(k in name for k in ["심의", "기재부", "예산안", "예산실"]):
        return "심의"
    if any(k in name for k in ["국정과제", "업무보고", "기본계획"]):
        return "상위계획"
    if any(k in name for k in ["보고서", "검토", "분석", "계획"]):
        return "보고서"
    return "기타"


# ── 청킹 ─────────────────────────────────────────────────────────────────────

def _chunk_text(text: str, file_path: Path) -> Generator[dict, None, None]:
    """
    섹션 헤더 기준 우선, 그 외 크기 기반 청킹.
    각 청크에 메타데이터 부여.
    """
    doc_type = _infer_doc_type(file_path)
    year = ""
    # 파일명에서 연도 추정 (YYYY 패턴)
    import re
    m = re.search(r"(19|20)\d{2}", file_path.name)
    if m:
        year = m.group()

    # 섹션 기반 청킹 (## 또는 숫자. 으로 시작하는 줄)
    section_pattern = re.compile(r"^(#{1,3} .+|[0-9]+[.가-힣]\s.+)$", re.MULTILINE)
    sections = section_pattern.split(text)

    chunk_idx = 0
    buffer = ""
    current_section = ""

    for part in sections:
        if section_pattern.match(part.strip()):
            if buffer.strip():
                yield from _emit_chunks(
                    buffer, file_path, doc_type, year, current_section, chunk_idx
                )
                chunk_idx += 10  # 섹션 구분자
            current_section = part.strip()[:80]
            buffer = part
        else:
            buffer += part

    # 마지막 버퍼
    if buffer.strip():
        yield from _emit_chunks(buffer, file_path, doc_type, year, current_section, chunk_idx)


def _emit_chunks(
    text: str, file_path: Path, doc_type: str, year: str, section: str, start_idx: int
) -> Generator[dict, None, None]:
    """긴 텍스트를 CHUNK_SIZE 단위로 분할해 yield."""
    text = text.strip()
    if len(text) <= CHUNK_SIZE:
        if len(text) > 30:
            yield _make_chunk(text, file_path, doc_type, year, section, start_idx)
        return
    pos = 0
    i = start_idx
    while pos < len(text):
        end = min(pos + CHUNK_SIZE, len(text))
        chunk = text[pos:end]
        if len(chunk) > 30:
            yield _make_chunk(chunk, file_path, doc_type, year, section, i)
        pos = end - CHUNK_OVERLAP
        i += 1


def _make_chunk(text: str, file_path: Path, doc_type: str, year: str, section: str, idx: int,
                llm_summary: str = "", llm_keywords: list[str] | None = None) -> dict:
    chunk_id = hashlib.md5(
        f"{file_path.name}:{idx}:{text[:50]}".encode()
    ).hexdigest()[:12]
    meta: dict = {
        "source":   file_path.name,
        "path":     str(file_path),
        "doc_type": doc_type,
        "year":     year,
        "section":  section,
        "chunk_id": chunk_id,
    }
    if llm_summary:
        meta["summary"] = llm_summary
    if llm_keywords:
        meta["keywords"] = ",".join(llm_keywords[:10])
    return {
        "content":  text,
        "metadata": meta,
        "id": chunk_id,
    }


# ── ChromaDB API 호출 ─────────────────────────────────────────────────────────

def _upsert_chunks(chunks: list[dict], collection: str, dry_run: bool = False) -> int:
    """ChromaDB REST API로 청크 업서트. 성공 건수 반환."""
    if not chunks:
        return 0
    if dry_run:
        log.info(f"  [DRY RUN] {len(chunks)}개 청크 업서트 예정")
        return len(chunks)

    url = f"{RAG_API_BASE}/upsert"
    try:
        payload = {
            "collection": collection,
            "chunks": [
                {
                    "text":     c["content"],
                    "source":   c["metadata"].get("source", c.get("id", "")),
                    "chunk_id": c.get("id", ""),
                    "metadata": c["metadata"],
                }
                for c in chunks
            ],
        }
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()
        return len(chunks)
    except Exception as e:
        log.error(f"ChromaDB 업서트 실패: {e}")
        return 0


def _list_collection(collection: str) -> None:
    """컬렉션에 인덱싱된 항목 수와 샘플 출력."""
    try:
        r = requests.get(f"{RAG_API_BASE}/count", params={"collection": collection}, timeout=10)
        count = r.json().get("count", "?") if r.ok else "API 오류"
        log.info(f"컬렉션 '{collection}': 총 {count}개 청크")
    except Exception as e:
        log.error(f"컬렉션 목록 조회 실패: {e}")


# ── 문서 생애주기 관리 (Phase 1-1) ────────────────────────────────────────────

def _archive_doc(filepath: str, collection: str | None, archived: bool) -> bool:
    """문서를 archived(true/false) 상태로 토글. hwp-rag /archive_doc 호출."""
    try:
        payload: dict[str, object] = {"filepath": filepath, "archived": archived}
        if collection:
            payload["collection"] = collection
        r = requests.post(f"{RAG_API_BASE}/archive_doc", json=payload, timeout=15)
        r.raise_for_status()
        action = "보관" if archived else "복구"
        log.info(f"{action} 완료: {filepath}  (응답: {r.json()})")
        return True
    except Exception as e:
        log.error(f"archive_doc 실패 {filepath}: {e}")
        return False


def _list_archived(collection: str | None) -> None:
    """보관 처리된 문서 목록 출력. hwp-rag /list_archived 호출."""
    try:
        params = {"collection": collection} if collection else {}
        r = requests.get(f"{RAG_API_BASE}/list_archived", params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        items = data.get("items") or data.get("archived") or data
        if isinstance(items, list):
            log.info(f"보관 문서 {len(items)}건:")
            for it in items:
                log.info(f"  - {it}")
        else:
            log.info(f"응답: {data}")
    except Exception as e:
        log.error(f"list_archived 실패: {e}")


# ── LLM 요약 ─────────────────────────────────────────────────────────────────

def _llm_summarize(text: str, file_path: Path) -> tuple[str, list[str]]:
    """OpenRouter를 통해 문서 요약과 핵심 키워드를 추출. 실패 시 빈 값 반환."""
    try:
        import sys, os
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
        import requests as _req

        snippet = text[:SUMMARY_MAX_CHARS]
        prompt = (
            f"다음 문서를 2~3문장으로 요약하고, 핵심 키워드를 쉼표로 구분하여 출력하라.\n"
            f"형식: 요약: <요약문>\n키워드: <키워드1>, <키워드2>, ...\n\n문서:\n{snippet}"
        )
        resp = _req.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={
                "model": "google/gemini-3-flash-preview",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 256,
            },
            timeout=20,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        summary, keywords = "", []
        for line in content.splitlines():
            if line.startswith("요약:"):
                summary = line[3:].strip()
            elif line.startswith("키워드:"):
                keywords = [k.strip() for k in line[4:].split(",") if k.strip()]
        return summary, keywords
    except Exception as e:
        log.debug(f"LLM 요약 실패 ({file_path.name}): {e}")
        return "", []


# ── 메인 인덱싱 로직 ──────────────────────────────────────────────────────────

def ingest_directory(
    directory: Path,
    collection: str,
    recursive: bool = True,
    dry_run: bool = False,
    batch_size: int = 50,
    use_llm_summary: bool = True,
) -> dict:
    """디렉토리의 모든 지원 파일을 인덱싱. 결과 통계 반환."""
    stats = {"files": 0, "chunks": 0, "errors": 0, "skipped": 0, "summaries": 0}

    if not directory.exists():
        log.warning(f"경로 없음: {directory}")
        return stats

    pattern = "**/*" if recursive else "*"
    files = [
        f for f in directory.glob(pattern)
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS
        and not f.name.startswith(".")
    ]
    log.info(f"탐색 완료: {len(files)}개 파일 in {directory}")

    batch: list[dict] = []
    for file_path in files:
        text = _extract_text(file_path)
        if not text.strip():
            stats["skipped"] += 1
            continue

        chunks = list(_chunk_text(text, file_path))
        if not chunks:
            stats["skipped"] += 1
            continue

        # LLM 요약 추출 (파일당 1회)
        llm_summary, llm_keywords = "", []
        if use_llm_summary and SUMMARY_ENABLED:
            llm_summary, llm_keywords = _llm_summarize(text, file_path)
            if llm_summary:
                stats["summaries"] += 1
                log.debug(f"  요약 생성: {file_path.name}")

        # 청크 0번(=첫 번째 청크)에 요약+키워드 주입
        enriched_chunks = []
        for i, chunk in enumerate(chunks):
            if i == 0 and llm_summary:
                meta = dict(chunk["metadata"])
                meta["summary"]  = llm_summary
                meta["keywords"] = ",".join(llm_keywords)
                enriched_chunks.append({**chunk, "metadata": meta})
            else:
                # 나머지 청크에도 키워드만 포함 (요약 생략으로 주제 취 절감)
                if llm_keywords:
                    meta = dict(chunk["metadata"])
                    meta["keywords"] = ",".join(llm_keywords)
                    enriched_chunks.append({**chunk, "metadata": meta})
                else:
                    enriched_chunks.append(chunk)

        batch.extend(enriched_chunks)
        stats["files"] += 1
        stats["chunks"] += len(enriched_chunks)

        # 배치 업서트
        if len(batch) >= batch_size:
            _upsert_chunks(batch, collection, dry_run=dry_run)
            log.info(f"  업서트: {len(batch)}청크 ({stats['files']}파일 처리) | 요약 {stats['summaries']}건")
            batch = []

    # 남은 배치
    if batch:
        _upsert_chunks(batch, collection, dry_run=dry_run)

    return stats


def ingest_file(file_path: Path, collection: str, dry_run: bool = False,
                use_llm_summary: bool = True) -> dict:
    """단일 파일 인덱싱."""
    text = _extract_text(file_path)
    if not text.strip():
        return {"files": 0, "chunks": 0, "summaries": 0}

    chunks = list(_chunk_text(text, file_path))
    llm_summary, llm_keywords = "", []
    if use_llm_summary and SUMMARY_ENABLED:
        llm_summary, llm_keywords = _llm_summarize(text, file_path)

    if llm_summary and chunks:
        meta = dict(chunks[0]["metadata"])
        meta["summary"]  = llm_summary
        meta["keywords"] = ",".join(llm_keywords)
        chunks[0] = {**chunks[0], "metadata": meta}
        for i in range(1, len(chunks)):
            if llm_keywords:
                m = dict(chunks[i]["metadata"])
                m["keywords"] = ",".join(llm_keywords)
                chunks[i] = {**chunks[i], "metadata": m}

    _upsert_chunks(chunks, collection, dry_run=dry_run)
    return {"files": 1, "chunks": len(chunks), "summaries": 1 if llm_summary else 0}


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="GA Wisdom RAG 인덱싱 스크립트")
    ap.add_argument("--collection", default="wisdom_base",
                    choices=["wisdom_base", "alignment_base", "budget"],
                    help="대상 ChromaDB 컬렉션")
    ap.add_argument("--dir",  default=None, help="인덱싱할 디렉토리 경로")
    ap.add_argument("--file", default=None, help="인덱싱할 단일 파일 경로")
    ap.add_argument("--list", action="store_true", help="컬렉션 현황 조회 후 종료")
    ap.add_argument("--list-archived", action="store_true", help="보관 처리된 문서 목록 조회 후 종료")
    ap.add_argument("--archive", default=None, metavar="FILEPATH", help="해당 파일을 보관 상태로 처리 후 종료")
    ap.add_argument("--unarchive", default=None, metavar="FILEPATH", help="해당 파일의 보관 상태를 해제 후 종료")
    ap.add_argument("--dry-run", action="store_true", help="실제 업서트 없이 청킹만 확인")
    ap.add_argument("--no-recursive", action="store_true", help="하위 폴더 탐색 안 함")
    ap.add_argument("--no-summary", action="store_true", help="LLM 요약 생성 비활성화 (빠르게 인덱싱할 때)")
    args = ap.parse_args()

    if args.no_summary:
        import wisdom_ingest as _self
        _self.SUMMARY_ENABLED = False

    if args.list:
        _list_collection(args.collection)
        sys.exit(0)

    if args.list_archived:
        _list_archived(args.collection)
        sys.exit(0)

    if args.archive:
        ok = _archive_doc(args.archive, args.collection, archived=True)
        sys.exit(0 if ok else 1)

    if args.unarchive:
        ok = _archive_doc(args.unarchive, args.collection, archived=False)
        sys.exit(0 if ok else 1)

    if args.file:
        path = Path(args.file)
        stats = ingest_file(path, args.collection, dry_run=args.dry_run)
        log.info(f"단일 파일 완료: {stats}")
        sys.exit(0)

    if args.dir:
        dirs = [Path(args.dir)]
    else:
        dirs = [Path(d) for d in (
            DEFAULT_ALIGNMENT_DIRS if args.collection == "alignment_base"
            else DEFAULT_WISDOM_DIRS
        )]

    total = {"files": 0, "chunks": 0, "errors": 0, "skipped": 0}
    for d in dirs:
        log.info(f"인덱싱 시작: {d} → {args.collection}")
        s = ingest_directory(d, args.collection,
                             recursive=not args.no_recursive,
                             dry_run=args.dry_run)
        for k in total:
            total[k] += s.get(k, 0)

    print(f"\n{'='*50}")
    print(f"인덱싱 완료: {total['files']}개 파일, {total['chunks']}개 청크")
    print(f"건너뜀: {total['skipped']}개, 오류: {total['errors']}개")
    if args.dry_run:
        print("[DRY RUN] 실제 업서트는 수행되지 않았습니다.")
    print("=" * 50)

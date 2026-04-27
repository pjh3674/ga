"""
template_engine.py — Jinja2 기반 행정 보고서 템플릿 엔진 (Phase 1-1)

역할:
  - LLM이 생성한 5섹션 마크다운 초안을 파싱하여 템플릿 변수로 분리
  - Jinja2 템플릿(templates/*.j2)으로 최종 Obsidian 저장용 문서 조립
  - 신규 템플릿 추가는 templates/ 폴더에 .j2 파일을 넣기만 하면 됨

사용 예:
  from template_engine import render_report, parse_sections

  ctx = parse_sections(llm_draft, topic="항만 노후 구조물 정비")
  ctx["alignment_intro"] = alignment_intro
  ctx["critique_md"] = critique_md
  ctx["citations"] = citations
  ctx["model_log"] = model_log
  doc = render_report("jangan_base", ctx)
"""
from __future__ import annotations

import re
import logging
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape, TemplateNotFound

log = logging.getLogger(__name__)

# ── 환경 설정 ─────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE_DIR = _PROJECT_ROOT / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape([]),      # 마크다운이므로 HTML 이스케이프 OFF
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)

# 사용 가능한 템플릿 ID (j2 확장자 제거)
AVAILABLE_TEMPLATES: list[str] = [
    p.stem for p in _TEMPLATE_DIR.glob("*.j2")
]

# ── 5섹션 파서 ────────────────────────────────────────────────────────────────

# LLM이 생성하는 섹션 제목 패턴 (## 1. 배경, # 배경, 1. 배경 등 허용)
_SECTION_PATTERNS: list[tuple[str, str]] = [
    ("section1_bg",  r"(?:##?\s*)?(?:\d\.\s*)?배경"),
    ("section2_cur", r"(?:##?\s*)?(?:\d\.\s*)?현황"),
    ("section3_prb", r"(?:##?\s*)?(?:\d\.\s*)?문제점"),
    ("section4_dir", r"(?:##?\s*)?(?:\d\.\s*)?추진\s*방향"),
    ("section5_pln", r"(?:##?\s*)?(?:\d\.\s*)?향후\s*계획"),
]


def parse_sections(draft: str, topic: str = "") -> dict[str, Any]:
    """
    LLM 초안 텍스트에서 5개 섹션을 파싱하여 dict로 반환.

    반환 dict 키:
      title, doc_date, author_dept,
      section1_bg, section2_cur, section3_prb, section4_dir, section5_pln
    섹션 파싱 실패 시 전체 원문을 section1_bg에 넣고 나머지는 빈 문자열.
    """
    ctx: dict[str, Any] = {
        "title":       topic or "정책 검토 보고서",
        "doc_date":    _today_str(),
        "author_dept": "항만연안재생과",
        "section1_bg":  "",
        "section2_cur": "",
        "section3_prb": "",
        "section4_dir": "",
        "section5_pln": "",
    }

    # 섹션 헤더 위치 탐색
    boundaries: list[tuple[str, int]] = []
    for var, pattern in _SECTION_PATTERNS:
        # 줄 단위로 헤더 매칭
        for m in re.finditer(
            r"^" + pattern + r"\s*$",
            draft,
            flags=re.MULTILINE | re.IGNORECASE,
        ):
            boundaries.append((var, m.end()))

    if not boundaries:
        # 헤더 없음 → 전체를 배경 섹션으로
        ctx["section1_bg"] = draft.strip()
        log.debug("parse_sections: 섹션 헤더 미탐지, 전체를 section1_bg로 처리")
        return ctx

    # 위치 기준으로 정렬
    boundaries.sort(key=lambda x: x[1])

    # 각 섹션 내용 추출
    for i, (var, start) in enumerate(boundaries):
        end = boundaries[i + 1][1] - _header_len(draft, boundaries[i + 1][1]) if i + 1 < len(boundaries) else len(draft)
        content = draft[start:end].strip()
        # 다음 섹션 헤더 직전까지만 (헤더 줄 제거)
        content = re.sub(r"^#{1,3}\s.*$", "", content, flags=re.MULTILINE).strip()
        ctx[var] = content

    return ctx


def _header_len(text: str, end_pos: int) -> int:
    """end_pos 이전 줄의 길이(헤더 줄) 반환."""
    start = text.rfind("\n", 0, end_pos - 1) + 1
    return end_pos - start


def _today_str() -> str:
    d = date.today()
    return f"{d.year}. {d.month}. {d.day}."


# ── 렌더러 ────────────────────────────────────────────────────────────────────

def render_report(template_id: str, ctx: dict[str, Any]) -> str:
    """
    지정된 템플릿으로 보고서 문자열 생성.

    Args:
      template_id: 템플릿 파일명 (확장자 제외, 예: "jangan_base")
      ctx:         템플릿 변수 dict

    Returns:
      렌더링된 마크다운 문자열

    Raises:
      TemplateNotFound: 템플릿 파일이 없을 때
    """
    template_file = f"{template_id}.j2"
    try:
        tmpl = _env.get_template(template_file)
    except TemplateNotFound:
        available = ", ".join(AVAILABLE_TEMPLATES) or "(없음)"
        raise TemplateNotFound(
            f"템플릿 '{template_id}' 없음. 사용 가능: {available}"
        )

    # 기본값 보충
    ctx.setdefault("doc_date",    _today_str())
    ctx.setdefault("author_dept", "항만연안재생과")
    ctx.setdefault("alignment_intro", "")
    ctx.setdefault("critique_md",     "")
    ctx.setdefault("citations",       [])
    ctx.setdefault("model_log",       [])
    ctx.setdefault("run_id",          0)

    return tmpl.render(**ctx)


def render_from_draft(
    draft: str,
    topic: str = "",
    template_id: str = "jangan_base",
    *,
    alignment_intro: str = "",
    critique_md: str = "",
    citations: list[str] | None = None,
    model_log: list[dict] | None = None,
    run_id: int = 0,
    extra: dict | None = None,
) -> str:
    """
    LLM 초안 → 섹션 파싱 → 템플릿 렌더링 원스톱 함수.

    refiner.py의 _step3_transmute 결과를 바로 넘기면 됨.
    """
    ctx = parse_sections(draft, topic=topic)
    ctx["alignment_intro"] = alignment_intro
    ctx["critique_md"]     = critique_md
    ctx["citations"]       = citations or []
    ctx["model_log"]       = model_log or []
    ctx["run_id"]          = run_id
    if extra:
        ctx.update(extra)
    return render_report(template_id, ctx)


# ── CLI 테스트 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _sample_draft = """
## 1. 배경
- 전국 항만 노후 구조물 비율이 30%를 초과하여 안전 위험 증대
- 연안관리법 제27조에 따라 정기점검 의무화 근거 확보

## 2. 현황
- 2025년 기준 노후 구조물 172개소, 추정 보수비용 약 1,850억 원
- 최근 3년간 안전 사고 14건 발생, 인명피해 3건

## 3. 문제점
- 예산 분산으로 집중 투자 불가 → 사업 효율성 저하
- 점검 주기 법정 기준(5년) 미준수 사례 다수

## 4. 추진방향
- 3단계 정비 로드맵 수립 (2026~2028)
- 항만공사와 공동 재원 조달로 재정 부담 분산

## 5. 향후계획
- 2026. 1. 세부 용역 발주
- 2026. 6. 1단계 착공 (20개소 우선 정비)
"""
    result = render_from_draft(
        draft=_sample_draft,
        topic="항만 노후 구조물 정비 사업 검토",
        alignment_intro="본 사업은 국정과제 40번 '안전한 해양환경 조성' 실현을 위한 핵심 과제임.",
        critique_md="### 감사·법령 리스크\n| 예상 지적 | 대응 논리 | 근거 |\n|---|---|---|\n| 예산 집행률 저조 | 단계별 집행계획 제출 | 국가재정법 제97조 |",
        citations=["- [근거1] `항만노후구조물현황_2025.xlsx` p.3"],
        model_log=[{"step": "parse", "model": "gemini-flash"}, {"step": "transmute", "model": "claude-sonnet-4-5"}],
        run_id=1,
    )
    print(result)

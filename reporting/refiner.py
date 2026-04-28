"""
refiner.py — AI 지식 정제소 코어 엔진 (Phase 1)

외부 AI(Gemini, Claude, DeepSeek 등)의 원문 답변을 4단계 파이프라인으로 변환:
  Step 1 (parse)      : 원문에서 주장·수치·법령 키워드 구조 추출
  Step 2 (align)      : 상위계획 정렬 문장 생성 (정책 명분)
  Step 3 (transmute)  : Master Persona + Wisdom RAG로 장문 기안형 초안 생성
  Step 4 (critique)   : Critic Persona(DeepSeek R1)로 예상 쟁점 부속 검토서 생성

산출물: RefineryOutput (보고서 본문, 정렬 서두, 부속 검토서, 근거 목록, 치환 내역)
"""
from __future__ import annotations

import re
import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger(__name__)

# ── 공통 설정 import ─────────────────────────────────────────────────────────
from config import (
    DEFAULT_BACKEND_KEY,
    get_report_writer_backend,
    get_reviewer_backend,
    WEAK_PHRASE_REPLACEMENTS,
    get_routed_backends,
)

# ── 프롬프트 (debate.py에서 공유) ────────────────────────────────────────────
try:
    from debate import MASTER_PERSONA_PROMPT, CRITIC_PERSONA_PROMPT
except ImportError:
    MASTER_PERSONA_PROMPT = ""
    CRITIC_PERSONA_PROMPT = ""

# ── RAG 검색 ─────────────────────────────────────────────────────────────────
try:
    from search.rag_search import (
        rag_search, format_rag_results, format_rag_citations,
        wisdom_search, alignment_search,
    )
    _RAG_AVAILABLE = True
except Exception as _e:
    log.warning(f"rag_search 일부 함수 없음: {_e}")
    _RAG_AVAILABLE = False

    def rag_search(*a, **kw): return []
    def format_rag_results(*a, **kw): return ""
    def format_rag_citations(*a, **kw): return ""
    def wisdom_search(*a, **kw): return []
    def alignment_search(*a, **kw): return []


# ── 데이터 모델 ──────────────────────────────────────────────────────────────

@dataclass
class RefineryInput:
    raw_text:     str           # 외부 AI 원문 (필수)
    topic:        str           # 문서 주제/제목
    source_ai:    str  = ""     # "gemini" | "claude" | "deepseek" | 기타
    context_hint: str  = ""     # 추가 컨텍스트 힌트 (선택)
    use_wisdom_rag:   bool = True
    use_alignment:    bool = True
    use_critique:     bool = True
    template_id:  str  = "jangan_base"
    quality:      str  = "balanced"  # economy | balanced | quality
    backend_key:  str  = ""     # 비어 있으면 model_routing.yaml 라우팅 사용


@dataclass
class RefineryOutput:
    report_md:      str         = ""      # 장문 기안형 보고서 본문 (Markdown)
    alignment_intro: str        = ""      # 정책 명분 서두 1~2문장
    critique_md:    str         = ""      # 예상 쟁점 부속 검토서
    citations:      list[str]   = field(default_factory=list)   # 근거 출처 목록
    replacements:   list[dict]  = field(default_factory=list)   # 문체 치환 내역
    model_log:      list[dict]  = field(default_factory=list)   # 모델 호출 이력
    error:          str         = ""      # 실패 시 오류 메시지
    run_id:         int         = 0       # DB refinery_runs.id


# ── 문체 치환 함수 ───────────────────────────────────────────────────────────

def apply_style_rules(text: str) -> tuple[str, list[dict]]:
    """
    config.WEAK_PHRASE_REPLACEMENTS 규칙 적용.
    반환: (변환된 텍스트, 치환 내역 목록)
    """
    applied = []
    result = text
    for weak, strong in WEAK_PHRASE_REPLACEMENTS.items():
        if weak in result:
            result = result.replace(weak, strong)
            applied.append({"from": weak, "to": strong})
    return result, applied


# ── 내부 파이프라인 단계 ─────────────────────────────────────────────────────

def _make_llm_caller(backend_key: str):
    """단일 LLM 호출 래퍼 (autogen AssistantAgent 없이 OpenRouter 직접 호출)."""
    from config import AGENT_BACKEND_OPTIONS, OPENROUTER_API_KEY, OPENROUTER_BASE_URL
    import requests as _req

    model_id, api_key, base_url = AGENT_BACKEND_OPTIONS.get(
        backend_key, (backend_key, OPENROUTER_API_KEY, OPENROUTER_BASE_URL)
    )
    if backend_key.startswith("free/"):
        model_id = backend_key[len("free/"):]
        api_key  = OPENROUTER_API_KEY
        base_url = OPENROUTER_BASE_URL

    def call(system_prompt: str, user_msg: str, max_tokens: int = 2000) -> str:
        try:
            r = _req.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model":    model_id,
                    "messages": [
                        {"role": "system",  "content": system_prompt},
                        {"role": "user",    "content": user_msg},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.3,
                },
                timeout=60,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"[LLM 호출 실패: {e}]"

    return call, model_id


def _step1_parse(raw_text: str, topic: str, backend_key: str) -> dict:
    """원문에서 주장·수치·법령 키워드 JSON 추출 (저비용 모델)."""
    call, model_id = _make_llm_caller(backend_key)

    system = (
        "너는 행정 문서 분석기다. 입력된 텍스트에서 아래 항목을 JSON으로 추출하라.\n"
        "출력은 순수 JSON만 (마크다운 코드블록 없이).\n"
        "{\n"
        "  \"main_claims\": [\"주장1\", ...],       // 핵심 주장 최대 5개\n"
        "  \"numbers\": [\"수치·금액·비율\", ...],   // 언급된 수치 최대 10개\n"
        "  \"laws\": [\"법령명·조항\", ...],          // 언급된 법령 최대 10개\n"
        "  \"keywords\": [\"핵심키워드\", ...],       // 주제 키워드 최대 10개\n"
        "  \"risks\": [\"리스크·우려사항\", ...]      // 위험·문제점 최대 5개\n"
        "}"
    )
    user = f"주제: {topic}\n\n원문:\n{raw_text[:3000]}"
    result = call(system, user, max_tokens=600)

    try:
        # JSON 파싱 시도
        parsed = json.loads(result)
        except Exception as e:
        log.warning("Step 1 JSON 파싱 실패 (%s), 최소 구조 반환", e)
        parsed = {
            "main_claims": [], "numbers": [], "laws": [],
            "keywords": [topic], "risks": [],
        }
    return {"parsed": parsed, "model": model_id}


def _step2_align(topic: str, keywords: list[str], use_alignment: bool, backend_key: str) -> str:
    """상위계획 RAG에서 정책 명분 서두 1~2문장 생성."""
    if not use_alignment or not _RAG_AVAILABLE:
        return ""

    query = f"{topic} {' '.join(keywords[:3])}"
    try:
        results = alignment_search(query, top_k=2)
        if not results:
            return ""
        refs = format_rag_results(results, collection_name="상위계획")
    except Exception:
        return ""

    call, _ = _make_llm_caller(backend_key)
    system = (
        "너는 정부 보고서 서두를 작성하는 행정 전문가다.\n"
        "아래 국정과제·업무보고 참고자료를 활용하여, '본 사업은 [국정기조] 실현을 위해 "
        "[구체 내용]하는 핵심 과제임'의 형식으로 1~2문장의 정책 명분 서두를 작성하라.\n"
        "과장 없이, 검증 가능한 근거만 사용하라. 문장만 출력 (제목·설명 없이)."
    )
    user = f"주제: {topic}\n\n참고자료:\n{refs}"
    intro = call(system, user, max_tokens=200)
    return intro if not intro.startswith("[LLM") else ""


def _step3_transmute(
    topic: str,
    raw_text: str,
    parsed: dict,
    alignment_intro: str,
    use_wisdom_rag: bool,
    backend_key: str,
) -> tuple[str, list[str]]:
    """Master Persona + Wisdom RAG로 장문 기안형 초안 생성."""
    call, model_id = _make_llm_caller(backend_key)

    # Wisdom RAG 검색
    citations = []
    rag_context = ""
    if use_wisdom_rag and _RAG_AVAILABLE:
        try:
                        query = f"{topic} {' '.join(parsed.get('keywords', [])[:3])}"
            wisdom_results = wisdom_search(query, top_k=5)
            if wisdom_results:
                rag_context = format_rag_results(wisdom_results, collection_name="향정지식베이스")
                citations_text = format_rag_citations(wisdom_results)
                citations = [c.strip() for c in citations_text.split("\n") if c.strip().startswith("-")]
        except Exception as e:
            log.warning("Step 3 wisdom_search 실패: %s", e)

    # 추출된 수치·법령 목록
    numbers_str = "\n".join(f"- {n}" for n in parsed.get("numbers", []))
    laws_str    = "\n".join(f"- {l}" for l in parsed.get("laws", []))
    claims_str  = "\n".join(f"- {c}" for c in parsed.get("main_claims", []))

    persona = MASTER_PERSONA_PROMPT or _default_master_persona()

    system = persona + (
        "\n\n출력 형식은 반드시 아래 5개 섹션으로 구성하라 (섹션 제목 그대로 사용):\n\n"
        "## 1. 배경\n"
        "## 2. 현황\n"
        "## 3. 문제점\n"
        "## 4. 추진방향\n"
        "## 5. 향후계획\n\n"
        "각 섹션은 개조식(- 또는 ○)으로 작성하고, 수치·법령 근거를 반드시 포함하라.\n"
        "약한 표현(사료됨, 가능할 것으로, 보임 등)은 절대 사용하지 말 것.\n"
        "붙임에 [근거N] 형식으로 사용된 근거를 목록화하라."
    )

    context_parts = []
    if alignment_intro:
        context_parts.append(f"[정책 명분]\n{alignment_intro}")
    if rag_context:
        context_parts.append(f"[행정 지식베이스 참고자료]\n{rag_context}")
    if claims_str:
        context_parts.append(f"[원문 핵심 주장]\n{claims_str}")
    if numbers_str:
        context_parts.append(f"[원문 수치·근거]\n{numbers_str}")
    if laws_str:
        context_parts.append(f"[원문 법령 키워드]\n{laws_str}")

    user = (
        f"주제: {topic}\n\n"
        + "\n\n".join(context_parts)
        + f"\n\n[원문 전문]\n{raw_text[:4000]}"
    )

    draft = call(system, user, max_tokens=2500)
    return draft, citations


def _step4_critique(topic: str, draft: str, backend_key: str) -> str:
    """Critic Persona(DeepSeek R1)로 예상 쟁점 부속 검토서 생성."""
    call, _ = _make_llm_caller(backend_key)

    persona = CRITIC_PERSONA_PROMPT or _default_critic_persona()
    system = persona + (
        "\n\n아래 보고서 초안을 검토하여 4축 예상 쟁점 부속 검토서를 작성하라.\n\n"
        "형식:\n"
        "## 예상 쟁점 및 대응 논리\n\n"
        "### 감사·법령 리스크\n"
        "| 예상 지적 | 대응 논리 | 근거 |\n|---|---|---|\n\n"
        "### 언론·여론 리스크\n"
        "| 예상 비판 | 대응 논리 | 근거 |\n|---|---|---|\n\n"
        "### 민원·지역 리스크\n"
        "| 예상 민원 | 대응 논리 | 근거 |\n|---|---|---|\n\n"
        "### 국회·정무 리스크\n"
        "| 예상 질의 | 대응 논리 | 근거 |\n|---|---|---|\n\n"
        "각 축마다 최소 1행 이상. 총 분량은 A4 2페이지 이내.\n"
        "확인 안 된 사실을 단정짓지 말 것."
    )
    user = f"주제: {topic}\n\n보고서 초안:\n{draft[:3000]}"
    critique = call(system, user, max_tokens=1500)
    return critique if not critique.startswith("[LLM") else ""


# ── 기본 페르소나 (debate.py import 실패 시 폴백) ────────────────────────────

def _default_master_persona() -> str:
    return (
        "너는 30년 경력의 행정전문가다. 다음 3계층 사고를 항상 적용하라.\n\n"
        "① 법규 검토: 연안관리법·항만법·국가재정법·관련 훈령의 적합성을 먼저 판단한다.\n"
        "② 예산 논리: 집행 효율성, 중복 투자 방지, 재정 지속 가능성, "
        "기재부 예산 편성 기준에 부합하는지 검토한다.\n"
        "③ 행정 문체: 단정적이고 책임 있는 표현을 사용한다. "
        "모호한 표현(사료됨, 가능할 것으로, 보임)은 금지한다. "
        "대신 '즉시 착수 가능', '연내 가시적 성과 창출', '추진 필요', "
        "'우선 검토 필요' 같은 명확한 행정 동사를 쓴다."
    )


def _default_critic_persona() -> str:
    return (
        "너는 20년 이상 정책 심의를 해온 까다로운 국장급 검토관이다. "
        "보고서의 약점을 찾아내는 것이 임무다. "
        "감사원의 시각, 언론의 비판, 현장 민원, 국회 질의를 동시에 고려한다. "
        "대안 없는 비판보다 '예상 공격 → 대응 논리 → 근거' 순서로 건설적 검토를 한다. "
        "확인되지 않은 사실을 단정하지 않는다."
    )


# ── 메인 진입점 ──────────────────────────────────────────────────────────────

def refine(
    inp: RefineryInput,
    on_progress: Callable[[str], None] | None = None,
) -> RefineryOutput:
    """
    4단계 정제 파이프라인 실행.
    on_progress: 진행 메시지 콜백 (Streamlit st.write 등)
    """
    from db import create_refinery_run, update_refinery_run_status, log_refinery_source

    def _progress(msg: str):
        if on_progress:
            on_progress(msg)
        log.info(msg)

    # DB 실행 기록 생성
    try:
        run_id = create_refinery_run(
            topic=inp.topic,
            source_ai=inp.source_ai,
            template_id=inp.template_id,
            options={
                "use_wisdom_rag": inp.use_wisdom_rag,
                "use_alignment":  inp.use_alignment,
                "use_critique":   inp.use_critique,
                "quality":        inp.quality,
            },
        )
    except Exception:
        run_id = 0

    out = RefineryOutput(run_id=run_id)

    # 모델 키 결정
    routed = get_routed_backends(inp.quality)
    backend_parse    = routed.get("fact",   DEFAULT_BACKEND_KEY)  # 저비용 분석용
    backend_transmute = inp.backend_key or get_report_writer_backend(inp.quality)
    backend_align    = backend_transmute
    backend_critique = routed.get("judge",  DEFAULT_BACKEND_KEY)  # 추론 특화

    try:
        # ── Step 1: 구조 분석 ─────────────────────────────────────────────
        _progress("📋 Step 1/4: 원문 구조 분석 중…")
        step1 = _step1_parse(inp.raw_text, inp.topic, backend_parse)
        parsed = step1["parsed"]
        out.model_log.append({"step": "parse", "model": step1["model"]})

        # ── Step 2: 상위계획 정렬 ─────────────────────────────────────────
        _progress("🔗 Step 2/4: 상위계획 정렬 문장 생성 중…")
        if inp.use_alignment:
            out.alignment_intro = _step2_align(
                inp.topic, parsed.get("keywords", []), True, backend_align
            )
            out.model_log.append({"step": "align", "model": backend_align})

        # ── Step 3: 장문 기안 변환 ────────────────────────────────────────
        _progress("✍️ Step 3/4: 행정전문가 문체로 보고서 초안 작성 중…")
        draft, citations = _step3_transmute(
            inp.topic, inp.raw_text, parsed,
            out.alignment_intro, inp.use_wisdom_rag, backend_transmute,
        )
        # 문체 치환 규칙 적용
        draft, replacements = apply_style_rules(draft)
        out.replacements = replacements
        out.citations    = citations
        out.model_log.append({"step": "transmute", "model": backend_transmute})

        # ── Step 3b: 템플릿 엔진으로 최종 문서 조립 ──────────────────────
        try:
            from reporting.template_engine import render_from_draft
            out.report_md = render_from_draft(
                draft=draft,
                topic=inp.topic,
                template_id=inp.template_id,
                alignment_intro=out.alignment_intro,
                citations=citations,
                model_log=out.model_log,
                run_id=run_id,
            )
            _progress("📄 템플릿 조립 완료")
        except Exception as _te:
            log.warning(f"템플릿 엔진 실패, 원문 사용: {_te}")
            out.report_md = draft

        # RAG 근거 DB 기록
        if run_id and citations:
            for i, c in enumerate(citations[:20]):
                try:
                    log_refinery_source(run_id, "wisdom", f"근거{i+1}", c)
                except Exception:
                    pass

        # ── Step 4: 비판 검토 부속서 ──────────────────────────────────────
        if inp.use_critique:
            _progress("🔍 Step 4/4: 예상 쟁점 및 대응 논리 검토 중…")
            out.critique_md = _step4_critique(inp.topic, draft, backend_critique)
            out.model_log.append({"step": "critique", "model": backend_critique})

            # critique가 추가됐으므로 템플릿 재렌더링 (critique_md 포함)
            try:
                from reporting.template_engine import render_from_draft
                out.report_md = render_from_draft(
                    draft=draft,
                    topic=inp.topic,
                    template_id=inp.template_id,
                    alignment_intro=out.alignment_intro,
                    critique_md=out.critique_md,
                    citations=out.citations,
                    model_log=out.model_log,
                    run_id=run_id,
                )
        else:
            _progress("✅ 정제 완료 (비판 검토 생략)")

        _progress("✅ 정제 완료")
        if run_id:
            try:
                update_refinery_run_status(run_id, "completed")
            except Exception:
                pass









        except Exception as e:
        out.error = str(e)
        log.error("정제 파이프라인 오류: %s", e)
        if run_id:
            try:
                update_refinery_run_status(run_id, "failed")
            except Exception as _e:
                log.warning("정제소 실패 상태 갱신 실패: %s", _e)

    return out


def refine_and_save(inp: RefineryInput, on_progress: Callable | None = None):
    """
    refine() 실행 후 자동으로 Obsidian에 저장.
    반환: (RefineryOutput, SaveResult)
    """
    from integrations.obsidian_save import save_refinery_output
    from db import log_save_result

    out = refine(inp, on_progress=on_progress)
    if not out.error and out.report_md:
        save_result = save_refinery_output(
            topic=inp.topic,
            report_md=out.report_md,
            critique_md=out.critique_md,
            citations=out.citations,
            run_id=out.run_id,
        )
        try:
            log_save_result(save_result, ref_id=out.run_id, ref_type="refinery")
        except Exception:
            pass
        return out, save_result
    return out, None


# ── CLI 테스트 진입점 ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="AI 정제소 CLI 테스트")
    ap.add_argument("--topic", default="항만 노후 구조물 정비 사업")
    ap.add_argument("--source_ai", default="gemini")
    ap.add_argument("--no-rag", action="store_true")
    ap.add_argument("--no-critique", action="store_true")
    ap.add_argument("--text", default=None, help="원문 직접 입력 (없으면 샘플 사용)")
    args = ap.parse_args()

    sample_text = args.text or (
        "항만 노후 구조물 정비가 시급합니다. 현재 전국 항만의 약 30%가 준공 후 30년 이상 "
        "경과하여 안전 위험이 있습니다. 연안관리법 제27조에 따라 정기점검을 의무화해야 하며, "
        "예산은 약 2,000억 원이 필요합니다. 2026년부터 3단계 사업으로 추진할 수 있을 것으로 "
        "사료됩니다. 주민들의 반발이 있을 수 있으나 적절히 대응 가능할 것으로 판단됩니다."
    )

    inp = RefineryInput(
        raw_text=sample_text,
        topic=args.topic,
        source_ai=args.source_ai,
        use_wisdom_rag=not args.no_rag,
        use_alignment=not args.no_rag,
        use_critique=not args.no_critique,
    )

    print(f"\n{'='*60}")
    print(f"주제: {inp.topic}")
    print(f"원문 길이: {len(inp.raw_text)}자")
    print("=" * 60)

    out = refine(inp, on_progress=lambda m: print(f"  {m}"))

    if out.error:
        print(f"\n[오류] {out.error}")
    else:
        if out.alignment_intro:
            print(f"\n[정책 명분 서두]\n{out.alignment_intro}\n")
        print(f"\n[보고서 초안]\n{out.report_md[:1500]}")
        if out.replacements:
            print(f"\n[문체 치환 {len(out.replacements)}건]")
            for r in out.replacements[:5]:
                print(f"  '{r['from']}' → '{r['to']}'")
        if out.critique_md:
            print(f"\n[부속 검토서 (앞 500자)]\n{out.critique_md[:500]}")
        print(f"\n[모델 사용]\n" + "\n".join(f"  {m['step']}: {m['model']}" for m in out.model_log))

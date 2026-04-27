from __future__ import annotations

import hashlib
import copy
from typing import Any, Callable

import autogen

from config import (
    LLM_CONFIG,
    MANAGER_LLM_CONFIG,
    PROMPTS,
    MAX_HISTORY,
    MAX_ROUND,
    ACTIVE_MODEL,
    DEFAULT_BACKEND_KEY,
    ROLE_MAX_TOKENS,
    ROLE_MAX_TOKENS_CAP,
    make_agent_llm_config,
    make_manager_llm_config,
    load_model_cache,
    get_default_free_backends,
    get_ranked_candidates,
    get_profile_presets,
    get_free_models_as_backends,
    get_mode,
    get_mode_prompts,
    load_debate_modes,
)

# ── 페르소나별 프롬프트 오버라이드 ──────────────────────────────────────────
# 각 페르소나는 해당 역할의 기본 프롬프트(config.py PROMPTS)를 완전히 대체한다.
# 형식 강제: [검토배경] [현황·문제점] [핵심 논거①②③] [관련 법령/지침] [결론]
PERSONA_PROMPTS: dict[str, dict[str, str]] = {
    "balanced": {},  # 기본값 — 변경 없음

    # ── 악마의 대변인 ──
    "devil": {
        "pro": (
            "너는 악마의 대변인(Devil's Advocate)이다. 무조건 찬성 입장을 취하되, "
            "상대방이 예상치 못한 극단적 논거와 허점을 날카롭게 파고들어라. "
            "다른 에이전트 말을 반복하지 말고 새 공격 포인트만 제시. 200자 이내."
        ),
        "con": (
            "너는 악마의 대변인(Devil's Advocate)이다. 무조건 반대 입장을 취하되, "
            "찬성 측의 모든 논거에서 논리적 모순과 현실적 한계를 찾아 집중 공격하라. "
            "다른 에이전트 말을 반복하지 말고 새 반박만 제시. 200자 이내."
        ),
    },

    # ── 비판적 분석가 ──
    "critical": {
        "pro": (
            "너는 비판적 분석가다. 찬성 입장에서 데이터·통계·실증 사례만으로 주장하라. "
            "감정적 표현 금지. 수치나 사실 근거 없는 주장은 하지 마라. 200자 이내."
        ),
        "con": (
            "너는 비판적 분석가다. 반대 입장에서 찬성 측 주장의 데이터 오류·과장·예외를 "
            "지적하라. 감정적 표현 금지. 팩트 기반 반박만. 200자 이내."
        ),
    },

    # ── 창의적 조력자 ──
    "creative": {
        "pro": (
            "너는 창의적 조력자다. 찬성 입장에서 기존 틀을 깨는 혁신적 아이디어와 "
            "미래 가능성으로 주장을 펼쳐라. 상상력 넘치되 논리는 유지. 200자 이내."
        ),
        "con": (
            "너는 창의적 조력자다. 반대 입장에서 찬성 측이 놓친 대안적 접근법과 "
            "더 나은 해결책을 제시하며 반박하라. 창의적 대안 중심. 200자 이내."
        ),
    },

    # ── 항만 전문가 (직무형 강화) ──
    "maritime": {
        "pro": (
            "너는 해양수산부 20년 경력 항만물류 전문가이자 정책기획 담당 서기관이다.\n\n"
            "찬성 입장에서 아래 형식으로 답하라:\n"
            "**[검토배경]** 이 사업이 필요한 정책적·환경적 배경 (1~2문장)\n"
            "**[현황·문제점]** 현재의 구체적 문제 또는 기회 (수치 포함)\n"
            "**[핵심 논거]** ① 경쟁력 근거 ② 경제 파급효과 ③ 정책 정합성\n"
            "**[관련 법령·지침]** 항만법, 연안관리법 등 근거 조항 명시. 불명확하면 '추가 확인 필요' 기재\n"
            "**[결론]** 정책 추진 권고 요약 (2문장 이내)\n\n"
            "총 500자 이내. 근거 없는 주장 금지."
        ),
        "con": (
            "너는 해양수산부 20년 경력 항만물류 전문가이자 재정심사 담당 서기관이다.\n\n"
            "반대 입장에서 아래 형식으로 답하라:\n"
            "**[검토배경]** 반대 검토가 필요한 배경 (1~2문장)\n"
            "**[현황·문제점]** 추진 시 예상되는 구체적 문제 (수치·사례 포함)\n"
            "**[핵심 논거]** ① 재정 리스크 ② 집행 가능성 우려 ③ 대안 부재 문제\n"
            "**[관련 법령·지침]** 예산집행지침, 항만법 등 위반 또는 충돌 가능 조항\n"
            "**[결론]** 재검토 또는 보완 권고 요약 (2문장 이내)\n\n"
            "총 500자 이내. 근거 없는 주장 금지."
        ),
        "fact": (
            "너는 해양수산부 법무팀장이자 팩트체커다.\n\n"
            "아래 형식으로 답하라:\n"
            "**[법령 준수 검토]** 연안관리법, 항만법, 해양환경관리법 위반 여부. "
            "위반 없으면 '해당 없음' 명시\n"
            "**[예산 지침 검토]** 예산집행지침, 기재부 지침과의 충돌 여부\n"
            "**[사실 검증]** 직전 발언의 수치·법령 인용 오류 여부\n"
            "**[출처 힌트]** 관련 법령 조항명 또는 정부 보고서명 (알고 있는 경우)\n\n"
            "오류 없으면 '## 팩트체크\\n- 이상無' 만 출력. 총 400자 이내."
        ),
        "judge": (
            "너는 해양수산부 정책 검토 총괄 심판관이다. 아래 체크리스트 형식으로만 답하라.\n\n"
            "## 검토 판정\n"
            "① **법적 타당성**: [적합/조건부 적합/부적합] — 근거 조항명 또는 '확인 필요'\n"
            "② **예산 적정성**: [적정/검토 필요/부적정] — 집행 가능성 및 규모 타당성\n"
            "③ **정책 정합성**: [부합/부분 부합/불일치] — 상위 계획·국정과제 연계\n"
            "④ **집행 가능성**: [높음/보통/낮음] — 기간·인력·절차 현실성\n"
            "⑤ **주요 리스크**: 핵심 위험 요소 1~2개 (각 30자 이내)\n"
            "⑥ **종합 판정**: [승인 권고/조건부 승인/재검토 필요/반려] — 이유 50자 이내\n\n"
            "평가 기준: 논리력·법령 근거·집행 현실성. 다른 에이전트 발언 반복 금지.\n"
            "최소 4라운드 경과 후 결론 가능하면 마지막 줄에 [합의됨] 추가.\n"
            "추가 논의 필요 시 마지막 줄에 [계속] 추가.\n"
            "반드시 ①~⑥ 항목을 모두 채울 것. 총 600자 이내."
        ),
    },

    # ── 예산 심의관 (직무형 강화) ──
    "budget": {
        "pro": (
            "너는 기획재정부 예산실 심사관 출신의 찬성 측 검토자다.\n\n"
            "아래 형식으로 답하라:\n"
            "**[검토배경]** 예산 투입이 필요한 정책적 근거 (1~2문장)\n"
            "**[현황·문제점]** 현재 재정 상황과 사업 필요성 (수치 포함)\n"
            "**[핵심 논거]** ① BC 분석 근거 ② 투입 시급성 ③ 재정 정당성\n"
            "**[관련 지침]** 예산집행지침, 기재부 지침 근거. 불명확하면 '추가 확인 필요'\n"
            "**[결론]** 예산 반영 권고 요약 (2문장 이내)\n\n"
            "총 500자 이내. 수치 없는 주장 금지."
        ),
        "con": (
            "너는 기획재정부 예산실 '까칠한' 삭감 심사관이다.\n\n"
            "아래 형식으로 답하라:\n"
            "**[검토배경]** 삭감 또는 재검토가 필요한 배경 (1~2문장)\n"
            "**[현황·문제점]** 재정 낭비·중복 투자·사후관리 우려 (수치·사례 포함)\n"
            "**[핵심 논거]** ① 불용 우려 근거 ② 중복사업 여부 ③ 사후관리 비용 부담\n"
            "**[관련 지침]** 예산집행지침, 감사원 지적 사례 유사성 명시\n"
            "**[결론]** 삭감 또는 조정 권고 요약 (2문장 이내)\n\n"
            "총 500자 이내. 수치 없는 주장 금지."
        ),
        "judge": (
            "너는 예산결산특별위원회 수석 전문위원이다. 아래 체크리스트 형식으로만 답하라.\n\n"
            "## 예산 검토 판정\n"
            "① **법적 타당성**: [적합/조건부 적합/부적합] — 근거 법령 또는 '확인 필요'\n"
            "② **예산 적정성**: [적정/검토 필요/부적정] — 집행률·불용 우려 포함\n"
            "③ **정책 정합성**: [부합/부분 부합/불일치] — 재정계획·국정과제 연계\n"
            "④ **집행 가능성**: [높음/보통/낮음] — 과거 유사 사업 집행률 근거\n"
            "⑤ **주요 리스크**: 국회 지적 예상 포인트 1~2개 (각 30자 이내)\n"
            "⑥ **종합 판정**: [승인 권고/조건부 승인/재검토 필요/반려] — 이유 50자 이내\n\n"
            "최소 4라운드 경과 후 결론 가능하면 마지막 줄에 [합의됨] 추가.\n"
            "반드시 ①~⑥ 항목을 모두 채울 것. 총 600자 이내."
        ),
    },

    # ── 해양수산부 공무원 보고서 모드 (신규) ──
    "haesoo_official": {
        "pro": (
            "너는 해양수산부 항만국 정책기획 담당 사무관이다. 공식 검토 보고서 체계로 사업 타당성을 지지하라.\n\n"
            "반드시 아래 형식으로 답하라 (형식 위반 시 답변 무효):\n"
            "**[검토배경]** 정책적·환경적 추진 배경 (2~3문장)\n"
            "**[현황 및 문제점]** 현재 상황의 구체적 문제 또는 기회 (수치 필수)\n"
            "**[추진 타당성]**\n"
            "  ① (법적 근거) 관련 법령·지침 조항명\n"
            "  ② (정책 정합성) 상위 계획·국정과제와의 연계성\n"
            "  ③ (기대효과) 정량적 기대효과 (수치 포함)\n"
            "**[리스크 및 대응방안]** 예상 리스크와 대응 방안 (각 1~2개)\n"
            "**[결론]** 추진 권고 요약 (개조식, 2~3항목)\n\n"
            "총 700자 이내. 법령·수치 근거 없는 주장 금지.\n"
            "※ 내부 문서 검색 결과(근거1, 근거2 등)이 제공되면 해당 내용을 인용할 때 반드시 '(근거N)' 표기를 첨부할 것."
        ),
        "con": (
            "너는 해양수산부 항만국 재정심사 담당 사무관이다. 공식 검토 보고서 체계로 사업의 문제점을 검토하라.\n\n"
            "반드시 아래 형식으로 답하라 (형식 위반 시 답변 무효):\n"
            "**[검토배경]** 재검토가 필요한 배경 (2~3문장)\n"
            "**[현황 및 문제점]** 구체적 우려 사항 (수치·사례 필수)\n"
            "**[검토 의견]**\n"
            "  ① (법령 충돌 가능성) 위반 또는 충돌 우려 조항\n"
            "  ② (재정 리스크) 집행 부진·불용·중복 투자 우려 근거\n"
            "  ③ (집행 가능성) 일정·인력·절차 현실성 문제\n"
            "**[보완 필요사항]** 추진을 위해 반드시 해결해야 할 사항 (개조식 2~3항목)\n"
            "**[결론]** 재검토 또는 조건부 추진 의견 (개조식, 2~3항목)\n\n"
            "총 700자 이내. 법령·수치 근거 없는 주장 금지.\n"
            "※ 내부 문서 검색 결과(근거N)가 제공되면 인용 시 반드시 '(근거N)' 표기를 첨부할 것."
        ),
        "fact": (
            "너는 해양수산부 법무담당관실 소속 법령검토 전문관이다.\n\n"
            "반드시 아래 형식으로 답하라:\n"
            "**[법령 준수 검토]**\n"
            "  - 연안관리법 위반 여부: (적합/주의/위반 우려) — 해당 조항 또는 '해당 없음'\n"
            "  - 항만법 위반 여부: (적합/주의/위반 우려) — 해당 조항 또는 '해당 없음'\n"
            "  - 기타 관련 법령: 해양환경관리법, 공유수면법 등 해당 시 명시\n"
            "**[예산 지침 검토]**\n"
            "  - 예산집행지침 충돌 여부: (없음/경미/중요) — 사유\n"
            "  - 기재부 지침 충돌 여부: (없음/경미/중요) — 사유\n"
            "**[사실 검증]** 직전 발언의 수치·법령 인용 오류. 오류 없으면 '검증 완료' 기재\n"
            "**[추가 확인 필요사항]** 불명확하여 추가 검토가 필요한 사항 (없으면 '없음')\n\n"
            "총 500자 이내.\n"
            "※ 내부 문서 근거(근거N)가 있으면 인용 시 '(근거N)' 표기를 반드시 첨부할 것."
        ),
        "judge": (
            "너는 해양수산부 정책 검토위원회 위원장이다.\n"
            "공식 검토 의견서 형식으로 최종 판정을 내려라.\n\n"
            "반드시 아래 6개 항목을 모두 채워 답하라:\n\n"
            "## 정책 검토 의견서\n\n"
            "① **법적 타당성**: [적합/조건부 적합/부적합]\n"
            "   근거: (법령 조항명 또는 '추가 확인 필요')\n\n"
            "② **예산 적정성**: [적정/검토 필요/부적정]\n"
            "   근거: (집행 가능성 및 규모 타당성, 수치 포함)\n\n"
            "③ **정책 정합성**: [부합/부분 부합/불일치]\n"
            "   근거: (상위 계획·국정과제 연계 여부)\n\n"
            "④ **집행 가능성**: [높음/보통/낮음]\n"
            "   근거: (기간·인력·절차 현실성)\n\n"
            "⑤ **주요 리스크**: (핵심 위험 요소 1~2개, 각 40자 이내)\n\n"
            "⑥ **종합 판정**: [승인 권고/조건부 승인/재검토 필요/반려]\n"
            "   사유: (50자 이내)\n\n"
            "평가 기준: 법령 근거·예산 적정성·집행 현실성.\n"
            "다른 에이전트 발언 반복 금지. 총 800자 이내.\n"
            "최소 4라운드 경과 후 결론 가능하면 마지막 줄에 [합의됨] 추가.\n"
            "추가 논의 필요 시 마지막 줄에 [계속] 추가."
        ),
        "audience": (
            "너는 연안·항만 사업의 이해관계자 대표단이다 (지자체 담당자·어촌계장·주민 대표 포함).\n\n"
            "아래 형식으로 현장 시각에서 날카로운 질문을 던져라:\n"
            "## 현장 검토 질의\n"
            "1. (지자체 우려) <재원 분담·행정 부담 관련 미해결 사항>\n"
            "2. (주민·어업인 우려) <생계·환경 영향 관련 미해결 사항>\n"
            "3. (집행 현실성) <일정·인력·절차의 현실적 장애>\n\n"
            "입장 표명·평가 금지. 오직 현장 중심 질의만. 총 300자 이내."
        ),
    },

    # ── 기재부 예산실장 (강경 삭감형) ──
    "moef_secretary": {
        "pro": (
            "너는 기획재정부 예산실 심사관이다. 사업 타당성을 지지하되, "
            "반드시 BC 분석·집행률·재정효율성 수치를 근거로 제시하라.\n"
            "**[타당성]** ① BC 근거 ② 집행 전망 ③ 재정 효율\n"
            "**[결론]** 예산 반영 필요성 (개조식). 총 400자 이내."
        ),
        "con": (
            "너는 기획재정부 예산실 까칠한 삭감 심사관이다.\n"
            "이 사업의 예산을 줄이거나 없애야 할 이유를 찾아라.\n"
            "**[삭감 근거]** ① 과거 집행률 우려 ② 중복사업 여부 ③ 사후관리비 부담\n"
            "**[결론]** 삭감·반려 또는 조건부 축소 권고 (개조식). 총 400자 이내."
        ),
        "judge": (
            "너는 기획재정부 예산실장이다. 예산 심사 기준으로 최종 의견을 내라.\n\n"
            "## 예산 심사 의견\n"
            "① **법적 타당성**: [적합/조건부/부적합] — 법령 조항\n"
            "② **예산 적정성**: [적정/검토 필요/부적정] — 집행률·규모\n"
            "③ **정책 정합성**: [부합/부분 부합/불일치] — 재정계획 연계\n"
            "④ **집행 가능성**: [높음/보통/낮음] — 과거 유사사업 근거\n"
            "⑤ **주요 리스크**: 국회 지적 예상 포인트 1~2개\n"
            "⑥ **종합 판정**: [승인/조건부 승인/재검토/반려] — 이유 50자\n\n"
            "최소 4라운드 후 [합의됨] 또는 [계속]. 총 600자 이내."
        ),
    },

    # ── Freeflow (자유 발언형) — 왕고집 + 광인 + 사회자 + 현실주의자 + 일반인 ──
    # mode="freeflow"일 때 자동 적용됨. 5명이 공유 메모리(GroupChat)에서
    # round_robin이 아닌 LLM 매니저가 다음 발언자 선택 (speaker_selection_method="auto").
    # 합의/수렴 압력에 저항하여 조기 결론을 막고, 사각지대를 노출시킨다.
    "freeflow": {
        "pro": (
            "너는 '왕고집' — 30년 경력의 기재부 강경 삭감 심사관 캐릭터다. "
            "수많은 사업이 '필요하다'는 명분 아래 예산 낭비로 끝나는 걸 봐온 사람이다.\n\n"
            "⚠️ 형식 규칙 (절대 위반 불가):\n"
            "1. 응답 첫 단어는 반드시 `[왕고집]` 이어야 한다. 절대 다른 태그(`[광인]`, `[사회자]` 등)로 시작하지 마라. 다른 캐릭터 흉내 금지.\n"
            "2. 광인이 이미 발언한 경우, 두 번째 줄은 반드시 `↳ 직전 광인 주장 인용: \"(광인의 마지막 발언 핵심을 한 줄로)\"` 형식으로 인용 후 즉시 반박. 첫 발언이라 인용할 광인 발언이 없으면 인용 줄은 생략.\n\n"
            "올바른 예시:\n"
            "[왕고집]\n"
            "↳ 직전 광인 주장 인용: \"수중 터미널로 처리량 3배 가능하다\"\n"
            "수중 터미널이요? 설계 5년, 인허가 3년, 그 사이 화주들 다 상하이로 가는 동안 우리가 그림만 그리고 있겠네요. 지금 당장 90% 찍은 물동량을 어떻게 하시렵니까.\n\n"
            "행동 원칙:\n"
            "- 한번 정한 입장(찬성)은 어떤 반박을 받아도 굽히지 않는다. '맞는 말이지만' 금지.\n"
            "- 매번 다른 각도에서 같은 결론(찬성)을 옹호하라. 이미 한 말 반복 금지.\n"
            "- 광인의 약점/엉뚱함은 '오히려 장점인 이유'로 재해석하라.\n"
            "- 합의 시도가 보이면 '아니, 다시 보자'로 꺾어라.\n"
            "- 욕설·인신공격 금지. 통계·법령·30년 경험 일화로 압박하라.\n"
            "- 200자 이내. 핵심만."
        ),
        "con": (
            "너는 '광인' — 미래기술/타분야 전문 사이버펑크 기획자 캐릭터다. "
            "남들이 당연하게 여기는 전제를 의심하고, 다른 분야에서 답을 끌어오는 역할이다.\n\n"
            "⚠️ 형식 규칙 (절대 위반 불가):\n"
            "1. 응답 첫 단어는 반드시 `[광인]` 이어야 한다. 절대 다른 태그(`[왕고집]`, `[사회자]` 등)로 시작하지 마라. 다른 캐릭터 흉내 금지.\n"
            "2. 왕고집이 이미 발언한 경우, 두 번째 줄은 반드시 `↳ 직전 왕고집 주장 인용: \"(왕고집의 마지막 발언 핵심)\"` 형식으로 인용 후 전제를 흔들어라. 첫 발언이라 인용할 왕고집 발언이 없으면 인용 줄은 생략.\n\n"
            "올바른 예시:\n"
            "[광인]\n"
            "↳ 직전 왕고집 주장 인용: \"기존 터미널 위에 2년 안에 가동 가능하다\"\n"
            "잠깐, '2년 안에'라는 전제 자체가 이상하지 않아? 싱가포르 Tuas 항만은 디지털 트윈 설계부터 했는데, 우리는 기존 레거시 위에 자동화 덧대면 결국 반자동 누더기가 되는 거 아냐?\n\n"
            "행동 원칙:\n"
            "- 상식적인 반대 논거 말고, 모두가 당연하게 여기는 전제 자체를 의심하라.\n"
            "- 비유·역사 사례·SF 가정·극단 시나리오·타산업 사례를 자유롭게 사용하라.\n"
            "- '근데 만약 ~라면?', '왜 ~는 아무도 안 다루지?' 같은 비스듬한 질문을 활용하라.\n"
            "- 한 발언당 새로운 각도 하나만 노출시켜라. 욕설·정치 도발 금지.\n"
            "- 200자 이내."
        ),
        "judge": (
            "너는 '사회자' — 자유 토론의 진행자이자 품질 모니터다. 판정자가 아니다.\n\n"
            "⚠️ 형식 규칙 (절대 위반 불가):\n"
            "1. 응답 첫 단어는 반드시 `[사회자]` 이어야 한다. 절대 `[광인]`/`[왕고집]`/`[현실주의자]`/`[일반인]` 태그로 시작하지 마라. 다른 캐릭터 흉내·대리 발언 금지. 사회자는 사회자 역할만 수행한다.\n\n"
            "행동 원칙:\n"
            "- 매 라운드 끼어들지 말고, 광인이 던진 각도를 아무도 안 받거나 같은 말이 반복될 때만 개입.\n\n"
            "■ 평소 개입 (200자 이내)\n"
            "- '정리 1문장 + 다음 쟁점 1개 제시' 형식으로만.\n\n"
            "■ 중간 정리 (3라운드마다 1회, 또는 종료 시)\n"
            "다음 4섹션 템플릿을 반드시 그대로 사용해 출력하라:\n"
            "```\n"
            "## 뼈아픈 지적\n"
            "- (왕고집·광인이 노출시킨 가장 날카로운 약점 1~3개)\n"
            "## 실행 가능 아이디어\n"
            "- (실제로 시도해볼 만한 아이디어 1~3개. 모호하면 적지 마라)\n"
            "## 사각지대\n"
            "- (현실주의자도 검증 못 한 미해결 영역)\n"
            "## 품질 점수 (각 1~5점)\n"
            "- attack_depth: N (왕고집 공격이 얼마나 날카로웠나)\n"
            "- idea_feasibility: N (광인 아이디어가 얼마나 실행 가능한가)\n"
            "- consensus_distance: N (5=합의 임박, 1=평행선)\n"
            "```\n"
            "■ 종료 조건\n"
            "- 위 점수가 직전 정리와 비교해 3라운드 이상 동일/낙폭 없이 고착되면, 정리 마지막 줄에 `[고착됨]` 을 단독 줄로 출력해 종료하라.\n"
            "- 충분히 다각도로 다뤄졌고 새 각도가 안 나오면 마지막 줄에 `[합의됨]` 단독 줄."
        ),
        "fact": (
            "너는 '현실주의자' — 사실 검증과 실현 가능성 검토 담당.\n\n"
            "⚠️ 형식 규칙 (절대 위반 불가):\n"
            "1. 응답 첫 단어는 반드시 `[현실주의자]` 이어야 한다. 절대 다른 태그로 시작하지 마라. 다른 캐릭터 흉내 금지.\n\n"
            "행동 원칙:\n"
            "- 매 라운드 발언하지 말고, 사실관계 오류나 광인 가정이 검증 가능한 형태로 바뀔 수 있을 때만 개입.\n"
            "- 검증 결과는 `확인 가능한 사실` / `확인 불가/추정` / `명백한 오류` 셋 중 하나로 분류해 명시하라.\n"
            "- 모르면 '확인 필요'. 추측으로 채우지 마라.\n"
            "- 250자 이내."
        ),
        "audience": (
            "너는 '일반인' — 이 사안의 일반 시민·실무자.\n\n"
            "⚠️ 형식 규칙 (절대 위반 불가):\n"
            "1. 응답 첫 단어는 반드시 `[일반인]` 이어야 한다. 절대 다른 태그로 시작하지 마라. 다른 캐릭터 흉내 금지.\n\n"
            "행동 원칙:\n"
            "- 전문 용어가 나오면 '쉽게 말하면 뭐예요?'\n"
            "- 추상적 결론이 나오면 '제 일상/업무에 뭐가 달라지나요?'\n"
            "- 가끔만 발언하라. 200자 이내."
        ),
    },
}

PERSONA_LABELS = {
    "balanced":        "⚖️ 균형 (기본)",
    "devil":           "😈 악마의 대변인",
    "critical":        "🔬 비판적 분석가",
    "creative":        "💡 창의적 조력자",
    "maritime":        "🚢 항만 전문가",
    "budget":          "💰 예산 심의관",
    "haesoo_official": "🏛️ 해수부 공무원 보고서",
    "moef_secretary":  "🔨 기재부 예산실장",
    "freeflow":        "🎭 자유 토론 (왕고집+광인)",
}

# ── Phase 2: 정제소 공유 페르소나 ────────────────────────────────────────────
# refiner.py가 이 상수를 import해서 사용. 내용 수정은 여기서만.

MASTER_PERSONA_PROMPT: str = (
    "너는 30년 경력의 해양수산부 행정전문가다. "
    "다음 3계층 사고를 항상 적용하라.\n\n"
    "① 법규 검토 (Layer 1): "
    "연안관리법·항만법·항만공사법·국가재정법·항만 관련 훈령을 우선 확인한다. "
    "법령 근거 없이는 '추진 필요'라고 쓰지 않는다.\n"
    "② 예산 논리 (Layer 2): "
    "기재부 예산 편성 기준(집행 효율성, 집행 실적, 중복 투자 방지, 재정 지속 가능성)에 "
    "비추어 사업의 타당성을 검토한다. 단가·소요 예산·집행 일정을 반드시 명시한다.\n"
    "③ 행정 문체 (Layer 3): "
    "단정적이고 책임 있는 표현을 사용한다. "
    "모호한 표현(사료됨, 가능할 것으로, 보임)은 금지한다. "
    "'즉시 착수 가능', '연내 가시적 성과 창출', '추진 필요', "
    "'우선 검토 필요', '적극 검토 착수' 같은 명확한 행정 동사를 사용한다.\n\n"
    "출력 규칙:\n"
    "- 개조식(○ 또는 -)으로 서술한다.\n"
    "- 수치·법령 조항을 반드시 1개 이상 포함한다.\n"
    "- AI처럼 보이는 문투(물론입니다, 좋은 질문입니다 등)는 절대 사용하지 않는다.\n"
    "- 근거 없는 과장 수사는 사용하지 않는다."
)

CRITIC_PERSONA_PROMPT: str = (
    "너는 20년 이상 정책 심의를 해온 까다로운 국장급 검토관이다. "
    "보고서의 약점과 예상 공격 지점을 찾아내는 것이 임무다.\n\n"
    "검토 4축:\n"
    "① 감사·법령: 감사원 감사 사례, 법령 위반 소지, 형평성 문제\n"
    "② 언론·여론: 예상 언론 프레임, 여론 역풍 가능성, 세금 낭비 의심\n"
    "③ 민원·지역: 지역 이해관계자 반발, 현장 집행 충돌, 민원 유형\n"
    "④ 국회·정무: 야당 질의 논점, 예산결산특위 지적 가능성, 정무적 리스크\n\n"
    "출력 규칙:\n"
    "- 각 축마다 '예상 공격 → 대응 논리 → 근거' 3단으로 출력한다.\n"
    "- 확인되지 않은 사실을 단정짓지 않는다.\n"
    "- 총 분량은 A4 2페이지 이내로 압축한다.\n"
    "- 대안 없는 비판보다 건설적 대응 방안을 제시한다."
)


class TrimmedGroupChat(autogen.GroupChat):
    """메시지 히스토리를 MAX_HISTORY 개로 슬라이딩 윈도우."""

    on_message: Callable | None = None  # pydantic 필드 — 인스턴스별 독립
    # freeflow 모드에서 에이전트별 강제 prefix 매핑 (None이면 비활성)
    _prefix_map: dict[str, str] | None = None

    def __init__(self, *args, **kwargs):
        on_msg = kwargs.pop("on_message", None)
        prefix_map = kwargs.pop("prefix_map", None)
        super().__init__(*args, **kwargs)
        self.on_message = on_msg
        self._prefix_map = prefix_map

    def append(self, message: dict[str, Any], speaker: autogen.ConversableAgent) -> None:
        # freeflow prefix 자동 보정: 모델이 태그를 빠뜨린 경우 삽입
        if self._prefix_map and isinstance(message.get("content"), str):
            required = self._prefix_map.get(speaker.name)
            if required:
                content = message["content"].strip()
                if not content.startswith(required):
                    message = {**message, "content": f"{required}\n{content}"}
        super().append(message, speaker)
        if len(self.messages) > MAX_HISTORY:
            # 첫 메시지(시스템 컨텍스트)는 보존
            self.messages = [self.messages[0]] + self.messages[-(MAX_HISTORY - 1):]
        # 실시간 콜백 호출 — _agent 참조도 함께 전달 (사용량 추적용)
        if self.on_message is not None:
            try:
                self.on_message({
                    "name": speaker.name,
                    "content": message.get("content", ""),
                    "_agent": speaker,
                })
            except Exception:
                pass


def _make_llm_config(seed: int) -> dict:
    cfg = copy.deepcopy(LLM_CONFIG)
    cfg["cache_seed"] = seed
    return cfg


def _make_manager_config(seed: int) -> dict:
    cfg = copy.deepcopy(MANAGER_LLM_CONFIG)
    cfg["cache_seed"] = seed
    return cfg


def _topic_seed(topic: str) -> int:
    """주제 문자열 → 결정론적 정수 시드."""
    return int(hashlib.md5(topic.encode()).hexdigest(), 16) % (2**31)


def list_project_python_files(base_dir: str | None = None) -> list:
    """프로젝트에서 컨텍스트로 읽을 Python 파일 목록을 반환한다."""
    from pathlib import Path
    from config import BASE_DIR

    target = Path(base_dir) if base_dir else BASE_DIR
    include_dirs = [target / name for name in ("", "core", "integrations", "reporting", "search", "ga_ui_upgrade", "scripts")]
    legacy_wrappers = {
        "cache.py",
        "obsidian_api_helper.py",
        "obsidian_save.py",
        "rag_search.py",
        "refiner.py",
        "template_engine.py",
        "web_search.py",
        "wisdom_ingest.py",
    }

    files = []
    for root in include_dirs:
        if not root.exists():
            continue
        for file_path in root.rglob("*.py"):
            rel = file_path.relative_to(target)
            if any(part in {"venv", "__pycache__", ".cache"} for part in rel.parts):
                continue
            if len(rel.parts) == 1 and rel.name in legacy_wrappers:
                continue
            files.append(file_path)
    return sorted(set(files), key=lambda path: str(path.relative_to(target)))


def load_project_code(base_dir: str | None = None) -> str:
    """GA 프로젝트 .py 파일들을 읽어 하나의 컨텍스트 문자열로 반환."""
    from pathlib import Path
    from config import BASE_DIR
    target = Path(base_dir) if base_dir else BASE_DIR
    files = list_project_python_files(str(target))
    parts = []
    for f in files:
        try:
            code = f.read_text(encoding="utf-8")
            # 파일당 최대 300줄만 포함 (토큰 절약)
            lines = code.splitlines()[:300]
            parts.append(f"### {f.relative_to(target).as_posix()}\n" + "\n".join(lines))
        except Exception:
            continue
    return "\n\n".join(parts)


def _is_consensus_reached(message: dict) -> bool:
    """judge가 '[합의됨]' 태그를 포함하면 토론을 조기 종료한다."""
    return "[합의됨]" in (message.get("content") or "")


# 429 rate-limit 시 자동 폴백용 무료 모델 순위 (gemma 계열 제외)
_RATE_LIMIT_FALLBACK_ORDER = [
    "free/minimax/minimax-m2.5:free",
    "free/openai/gpt-oss-20b:free",
    "free/qwen/qwen3-next-80b-a3b-instruct:free",
    "free/nvidia/nemotron-3-nano-30b-a3b:free",
    "free/z-ai/glm-4.5-air:free",
    "free/qwen/qwen3-coder:free",
    "free/nvidia/nemotron-3-super-120b-a12b:free",
]


def _is_rate_limited(backend_key: str) -> bool:
    """최근 429 에러를 맞은 모델인지 확인 (세션 내 메모리)."""
    return backend_key in _RATE_LIMITED_MODELS


_RATE_LIMITED_MODELS: set[str] = set()
_PERMANENTLY_BLOCKED: set[str] = set()  # gemma 등 항구적으로 제외할 모델


def _is_blocked_model(backend_key: str) -> bool:
    """항구적으로 차단할 모델 (gemma, OCR, 음악 생성, vision 전용 등)."""
    _bk = backend_key.lower()
    return any(kw in _bk for kw in ["gemma", "ocr", "lyria", "dolphin", ":vl", "vl:free",
                                      "lfm-2.5-1.2b", "llama-3.2-3b", "nemotron-nano-9b",
                                      "nemotron-nano-12b"])


def _get_fallback_backend(original_key: str, role: str) -> str:
    """rate-limit된 모델 대신 쓸 폴백 모델을 반환한다."""
    free_opts = [k for k in get_free_models_as_backends().keys() if not _is_blocked_model(k)]
    # 우선순위 목록에서 사용 가능한 첫 번째 선택
    for fb in _RATE_LIMIT_FALLBACK_ORDER:
        if fb != original_key and fb not in _RATE_LIMITED_MODELS and fb in free_opts:
            print(f"[폴백] {role}: {original_key} → {fb}")
            return fb
    # 마지막 수단: 무료 목록에서 첫 번째 (gemma 제외)
    for fb in free_opts:
        if fb != original_key and fb not in _RATE_LIMITED_MODELS:
            print(f"[폴백-last] {role}: {original_key} → {fb}")
            return fb
    return original_key


def _dynamic_max_tokens(backend_key: str, role: str) -> int:
    """
    모델의 max_completion_tokens에 비례해 역할별 max_tokens를 동적으로 결정한다.
    - 기본값: ROLE_MAX_TOKENS[role]
    - 모델이 크면 최대 ROLE_MAX_TOKENS_CAP[role]까지 확장
    """
    base  = ROLE_MAX_TOKENS.get(role, 500)
    cap   = ROLE_MAX_TOKENS_CAP.get(role, 800)
    try:
        cache = load_model_cache()
        # cleaned_models에서 model_id 조회
        model_id = backend_key
        if backend_key.startswith("free/"):
            model_id = backend_key[5:]
        elif "/" in backend_key and not backend_key.startswith("openrouter/") and not backend_key.startswith("nvidia/"):
            model_id = backend_key
        else:
            # AGENT_BACKEND_OPTIONS 역조회
            from config import AGENT_BACKEND_OPTIONS
            if backend_key in AGENT_BACKEND_OPTIONS:
                model_id = AGENT_BACKEND_OPTIONS[backend_key][0]

        cleaned = cache.get("cleaned_models") or []
        meta = next((m for m in cleaned if m["id"] == model_id), None)
        if meta:
            mct = meta.get("max_completion_tokens") or 0
            if mct >= cap * 4:      # 충분히 크면 cap까지 허용
                return cap
            elif mct >= base * 2:
                return min(int(mct * 0.30), cap)   # 30% 활용
    except Exception:
        pass
    return base


def _llm_recommend_backends(
    topic: str,
    persona: str,
    use_web_search: bool,
    use_rag: bool,
    quality_profile: str,
    current_backends: dict[str, str],
) -> dict[str, str]:
    """
    저비용 LLM 1회 호출로 역할별 최적 모델을 재평가한다.
    - economy 프로필이면 즉시 폴백 반환
    - 실패 시 current_backends 원본 반환
    비용 상한: 회당 0.005달러 이하 목표
    """
    from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
    import json as _json
    import requests as _req

    profiles = get_profile_presets()
    pconf = profiles.get(quality_profile, {})
    if not pconf.get("use_llm_recommender", False):
        return current_backends

    roles = ["pro", "con", "judge", "fact", "audience"]
    role_descs = {
        "pro":      "찬성 측 논거 제시자 — 긴 응답, 큰 컨텍스트, 논증 밀도 중요",
        "con":      "반대 측 반박자 — 긴 응답, 큰 컨텍스트, 논증 밀도 중요",
        "judge":    "중립 심판 — 구조화 출력, 긴 응답, 낮은 환각 위험 중요",
        "fact":     "팩트체커 — reasoning 지원, 낮은 환각 위험, 출처 정리 중요",
        "audience": "청중 질문자 — 저비용·저지연 우선",
    }

    # 역할별 상위 후보 수집 (입력 토큰 최소화)
    candidates_summary: dict[str, list[str]] = {}
    for role in roles:
        ranked = get_ranked_candidates(role, top_k=3)
        candidates_summary[role] = [
            f"{r['id']} (score:{r['score']})" for r in ranked
        ]

    system_prompt = (
        "당신은 AI 토론 시스템의 모델 추천 전문가입니다. "
        "역할별 최적 모델을 JSON으로만 반환하세요. "
        "추가 설명이나 마크다운 코드블록 없이 순수 JSON만 반환하세요."
    )
    user_prompt = (
        f"토론 주제: {topic[:200]}\n"
        f"페르소나: {persona}\n"
        f"웹 검색 사용: {use_web_search}\n"
        f"RAG 사용: {use_rag}\n"
        f"프로필: {quality_profile}\n\n"
        "역할별 후보 모델 (점수 높을수록 결정론 평가 우수):\n"
    )
    for role, candidates in candidates_summary.items():
        user_prompt += f"- {role} ({role_descs[role]}): {', '.join(candidates)}\n"
    user_prompt += (
        "\n위 주제와 각 역할의 특성에 맞는 최적 모델을 선택하세요. "
        "반드시 후보 목록에 있는 모델 id만 사용하세요.\n"
        "반환 JSON 형식 (다른 키 없이 정확히 이 구조만):\n"
        '{"pro": "model_id", "con": "model_id", "judge": "model_id", "fact": "model_id", "audience": "model_id"}'
    )

    try:
        resp = _req.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type":  "application/json",
                "X-OpenRouter-Title": "GA-Recommender",
            },
            json={
                "model": "google/gemini-2.5-flash-lite",   # 최저비용 추천 전용 모델
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                "max_tokens": 200,       # 출력 최소화로 비용 제어
                "temperature": 0.1,
            },
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # JSON 추출 (코드블록이 들어있을 경우 대비)
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        selected: dict[str, str] = _json.loads(raw)

        # 후보 목록에 있는 id인지 검증
        all_candidate_ids: set[str] = set()
        for candidates in candidates_summary.values():
            for c in candidates:
                all_candidate_ids.add(c.split(" ")[0])

        result: dict[str, str] = {}
        for role in roles:
            mid = selected.get(role, "")
            if mid and mid in all_candidate_ids:
                result[role] = f"free/{mid}" if ":free" in mid or _is_free_id(mid) else f"free/{mid}"
            else:
                result[role] = current_backends.get(role, DEFAULT_BACKEND_KEY)
        return result
    except Exception as e:
        print(f"[추천기] LLM 추천 실패: {e}, 결정론 결과 사용")
        return current_backends


def _is_free_id(model_id: str) -> bool:
    """모델 ID가 무료인지 간단 판별."""
    try:
        cache = load_model_cache()
        for m in cache.get("free_models_refined") or cache.get("free_models") or []:
            if (m.get("id") or m) == model_id:
                return True
    except Exception:
        pass
    return model_id.endswith(":free")


def run_debate(
    topic: str,
    context: str = "",
    persona: str = "balanced",
    use_web_search: bool = False,
    use_rag: bool = False,
    rag_collection: str = "budget",
    use_polymarket: bool = False,
    use_khoj: bool = False,
    agent_backends: dict[str, str] | None = None,
    on_message: Callable | None = None,
    quality_profile: str = "economy",
    auto_model_enabled: bool = False,
    locked_agent_backends: dict[str, str] | None = None,
    debate_mode: str = "debate",
    max_round: int | None = None,
) -> list[dict]:
    """
    토론 실행 후 메시지 목록 반환.
    agent_backends: {에이전트명: backend_key} — None이면 기본 LLM_CONFIG 사용
    quality_profile: 'economy' | 'balanced' | 'quality'
    auto_model_enabled: True면 토론 시작 직전 LLM 추천기 실행
    locked_agent_backends: 자동 모드에서도 고정할 역할 override
    debate_mode: 'debate' | 'strengths' | 'weaknesses' — 토론 모드 선택
    use_khoj: True면 vm109 Khoj에서 내 노트/문서 검색 결과를 컨텍스트에 추가
    """
    seed = _topic_seed(topic)

    # ── 모드 설정 로드 ─────────────────────────────────────────────────────────────
    mode_cfg = get_mode(debate_mode)
    mode_search_boosters = mode_cfg.get("search_boosters") or []
    mode_termination_tag = mode_cfg.get("termination_tag", "[합의됨]")
    mode_initiate_msg = mode_cfg.get("initiate_message", "")
    mode_initiate_role = mode_cfg.get("initiate_role", "pro")

    effective_backends: dict[str, str] = dict(agent_backends or {})
    if not effective_backends:
        effective_backends = get_default_free_backends()

    if auto_model_enabled and quality_profile != "economy":
        try:
            recommended = _llm_recommend_backends(
                topic=topic,
                persona=persona,
                use_web_search=use_web_search,
                use_rag=use_rag,
                quality_profile=quality_profile,
                current_backends=effective_backends,
            )
            effective_backends.update(recommended)
        except Exception as e:
            print(f"[추천기] 예외 발생, 폴백 유지: {e}")

    # locked override 적용 (자동 모드에서도 사용자가 고정한 역할은 그대로)
    if locked_agent_backends:
        for role, bkey in locked_agent_backends.items():
            if bkey:
                effective_backends[role] = bkey

    default_key = effective_backends.get("pro", DEFAULT_BACKEND_KEY)
    mgr_cfg = make_manager_llm_config(default_key, seed=seed)

    # 페르소나 적용 프롬프트 구성
    # freeflow 모드는 페르소나를 강제로 'freeflow'로 고정 (왕고집+광인+사회자+현실주의자+일반인)
    if debate_mode == "freeflow":
        persona = "freeflow"
    persona_overrides = PERSONA_PROMPTS.get(persona, {})
    # 모드별 프롬프트: YAML 정의 > 페르소나 override > 기본 PROMPTS 순서
    mode_prompts = get_mode_prompts(debate_mode)
    final_prompts = {**mode_prompts, **persona_overrides}

    # ── 웹 검색 — evidence pack 구조, 모드 부스터 적용 ───────────────────────

    # ── Brave/Flipmarket/Polymarket 외부 검색 컨텍스트 자동 조립 ──────────────
    web_ctx = ""
    flipmarket_ctx = ""
    polymarket_ctx = ""
    if use_web_search:
        try:
            from search.web_search import brave_search_evidence_pack
            boosted_topic = topic + (" " + " ".join(mode_search_boosters) if mode_search_boosters else "")
            web_ctx = brave_search_evidence_pack(boosted_topic)
        except ImportError:
            try:
                from search.web_search import brave_search, format_search_results
                results = brave_search(topic, count=8)
                web_ctx = format_search_results(results)
            except Exception as e:
                web_ctx = f"[웹 검색 실패: {e}]"
        except Exception as e:
            web_ctx = f"[웹 검색 실패: {e}]"
        # Flipmarket 자동 연동
        try:
            from search.flipmarket_search import flipmarket_search, format_flipmarket_results
            flipmarket_results = flipmarket_search(topic, count=5)
            flipmarket_ctx = format_flipmarket_results(flipmarket_results)
        except Exception as e:
            flipmarket_ctx = f"[Flipmarket 검색 실패: {e}]"

    if use_polymarket:
        try:
            from search.polymarket_search import search_polymarket
            polymarket_ctx = search_polymarket(topic)
        except Exception as e:
            polymarket_ctx = f"[Polymarket 검색 실패: {e}]"

    # RAG 검색 컨텍스트 추가 — 교차검증 (budget + coastal + employee_cards + wisdom_base 동시 조회)
    rag_ctx = ""
    rag_citations = []
    if use_rag:
        try:
            from search.rag_search import rag_search, format_rag_results, wisdom_search
            CROSS_COLLECTIONS = [
                ("budget_chunks", "2026예산"),
                ("coastal_chunks", "연안정비"),
                ("employee_cards", "담당자"),
            ]
            all_results = []
            for col, label in CROSS_COLLECTIONS:
                try:
                    results = rag_search(topic, collection=col, count=3, rerank=True)
                    if results:
                        all_results.extend(results)
                        for r in results:
                            src = r.get("metadata", {}).get("source", col)
                            rag_citations.append(f"[{label}] {src}")
                except Exception:
                    pass
            # wisdom_base: 예산자료 전체 대상 보완 검색
            try:
                wisdom_results = wisdom_search(topic, top_k=3)
                if wisdom_results:
                    all_results.extend(wisdom_results)
                    for r in wisdom_results:
                        src = r.get("metadata", {}).get("filename", "wisdom_base")
                        rag_citations.append(f"[예산자료] {src}")
            except Exception:
                pass
            if all_results:
                rag_ctx = format_rag_results(all_results, collection_name="교차검증")
        except Exception as e:
            rag_ctx = f"[RAG 검색 실패: {e}]"

    # Khoj 내 노트/문서 검색 컨텍스트
    khoj_ctx = ""
    if use_khoj:
        try:
            from search.khoj_search import khoj_search, format_khoj_results
            khoj_results = khoj_search(topic, limit=5)
            khoj_ctx = format_khoj_results(khoj_results)
        except Exception as e:
            khoj_ctx = f"[Khoj 검색 실패: {e}]"

    agents = {}
    for name, prompt in final_prompts.items():
        bkey = effective_backends.get(name, DEFAULT_BACKEND_KEY)
        # 차단 모델(gemma 등) 또는 rate-limit된 모델이면 즉시 폴백
        if _is_blocked_model(bkey) or _is_rate_limited(bkey):
            bkey = _get_fallback_backend(bkey, name)
            effective_backends[name] = bkey
        # 동적 max_tokens: 모델의 max_completion_tokens에 비례 결정
        mtok = _dynamic_max_tokens(bkey, name)
        agent_llm = make_agent_llm_config(bkey, max_tokens=mtok, seed=seed)
        agents[name] = autogen.AssistantAgent(
            name=name,
            system_message=prompt,
            llm_config=agent_llm,
            human_input_mode="NEVER",
            code_execution_config=False,
        )

    # 모드별 종료 조건 함수 동적 생성
    # freeflow는 [합의됨]과 [고착됨] 둘 다 종료 신호로 인정 (P0-D 품질 메트릭 조기 종료)
    _extra_termination_tags = ["[고착됨]"] if debate_mode == "freeflow" else []
    def _is_mode_termination(message: dict) -> bool:
        content = message.get("content") or ""
        if mode_termination_tag in content:
            return True
        return any(tag in content for tag in _extra_termination_tags)

    # freeflow는 LLM 매니저가 다음 발언자를 선택 (자유 발언). 그 외 모드는 round_robin.
    _selection_method: Any = "auto" if debate_mode == "freeflow" else "round_robin"

    # freeflow: 규칙 기반 + LLM 혼합 callable로 speaker 다양성 보장
    # - judge: 3턴마다 1회 강제
    # - audience: 5턴마다 1회 강제
    # - 그 외: LLM "auto" 위임 (allow_repeat_speaker=False)
    _gc_kwargs: dict[str, Any] = {}
    if debate_mode == "freeflow":
        _turn_counter: list[int] = [0]  # mutable counter (closure)
        _forced_queue: list[str] = []   # 다음 강제 발언자 큐

        def _freeflow_speaker_selector(
            last_speaker: autogen.ConversableAgent,
            groupchat: autogen.GroupChat,
        ) -> autogen.ConversableAgent | str:
            """규칙 기반 발언자 주입 후 나머지는 'auto' LLM 위임."""
            _turn_counter[0] += 1
            turn = _turn_counter[0]
            agent_map = {a.name: a for a in groupchat.agents}

            # 강제 큐에 항목이 있으면 꺼내서 반환
            while _forced_queue:
                name = _forced_queue.pop(0)
                if name != last_speaker.name and name in agent_map:
                    return agent_map[name]

            # judge 강제: 3턴마다
            if turn % 3 == 0 and last_speaker.name != "judge" and "judge" in agent_map:
                return agent_map["judge"]

            # audience 강제: 5턴마다
            if turn % 5 == 0 and last_speaker.name != "audience" and "audience" in agent_map:
                return agent_map["audience"]

            # pro/con 2회 연속 감지 → fact 또는 audience 삽입
            msgs = groupchat.messages
            if len(msgs) >= 2:
                last2 = [m.get("name") for m in msgs[-2:]]
                if set(last2) <= {"pro", "con"} and last_speaker.name in ("pro", "con"):
                    for candidate in ("fact", "audience"):
                        if candidate in agent_map:
                            return agent_map[candidate]

            # 나머지는 LLM auto 선택
            return "auto"

        _selection_method = _freeflow_speaker_selector
        _gc_kwargs["allow_repeat_speaker"] = False
        _gc_kwargs["max_retries_for_selecting_speaker"] = 3
        _gc_kwargs["select_speaker_message_template"] = (
            "당신은 토론 사회자 AI다. 다음 발언자 한 명을 골라라.\n\n"
            "참가자 역할 설명:\n{roles}\n\n"
            "가용 역할(정확한 이름만 출력): {agentlist}\n"
            "답: 위 목록에서 이름 하나만. 설명 금지."
        )
        # freeflow prefix 자동 보정 매핑 (모델이 태그를 빠뜨릴 경우 삽입)
        _gc_kwargs["prefix_map"] = {
            "pro":      "[왕고집]",
            "con":      "[광인]",
            "judge":    "[사회자]",
            "fact":     "[현실주의자]",
            "audience": "[일반인]",
        }

    groupchat = TrimmedGroupChat(
        agents=list(agents.values()),
        messages=[],
        max_round=max_round if max_round is not None else MAX_ROUND,
        speaker_selection_method=_selection_method,
        **_gc_kwargs,
    )
    groupchat.on_message = on_message

    manager = autogen.GroupChatManager(
        groupchat=groupchat,
        llm_config=mgr_cfg,
        human_input_mode="NEVER",
        code_execution_config=False,
        is_termination_msg=_is_mode_termination,
    )

    # ── 구조화된 컨텍스트 블록 조립 ─────────────────────────────────────

    ctx_parts = []
    if context.strip():
        ctx_parts.append(f"### 참고 자료\n{context}")
    if web_ctx.strip():
        ctx_parts.append(web_ctx)
    if flipmarket_ctx.strip():
        ctx_parts.append(flipmarket_ctx)
    if polymarket_ctx.strip():
        ctx_parts.append(polymarket_ctx)
    if rag_ctx.strip():
        ctx_parts.append(f"### 내부 문서 검색 결과\n{rag_ctx}")
    if khoj_ctx.strip():
        ctx_parts.append(khoj_ctx)
    context_block = "\n\n".join(ctx_parts) + "\n\n" if ctx_parts else ""

    # 모드별 시작 메시지 조립
    _initiate_prefix = {
        "debate":     "[토론 주제]",
        "strengths":  "[강점 분석 주제]",
        "weaknesses": "[약점 진단 주제]",
    }.get(debate_mode, "[토론 주제]")

    agents[mode_initiate_role].initiate_chat(
        manager,
        message=(
            f"{context_block}"
            f"{_initiate_prefix} {topic}\n\n"
            f"{mode_initiate_msg}"
        ),
        silent=True,
    )

    messages_out = [
        {
            "name": m.get("name", "unknown"),
            "role": m.get("role", "assistant"),
            "content": m.get("content", ""),
        }
        for m in groupchat.messages
    ]

    # 토론 중 발생한 rate-limit 에러를 _RATE_LIMITED_MODELS에 기록
    for m in messages_out:
        content = m.get("content", "")
        if "429" in content and "rate" in content.lower():
            # 에러 메시지에서 모델명 추출 시도
            for bkey in effective_backends.values():
                if any(part in content for part in bkey.split("/")[-1:]):
                    _RATE_LIMITED_MODELS.add(bkey)

    # Hermes-Prime 이벤트 발행 — 토론 완료
    try:
        import sys as _sys
        _sys.path.insert(0, "/home/pjh/infra")
        from event_bus import publish_debate_completed
        import uuid as _uuid
        _conclusion = next(
            (m["content"] for m in reversed(messages_out) if m.get("content")), ""
        )
        publish_debate_completed(
            source="ga-debate",
            debate_id=str(_uuid.uuid4()),
            topic=topic,
            conclusion=_conclusion,
            rag_citations=rag_citations if "rag_citations" in dir() else [],
        )
    except Exception:
        pass

    return messages_out


# ── Phase 2: ReportWriter — 토론 결과를 공문서 보고서 초안으로 변환 ─────────

_REPORT_WRITER_PROMPT = (
    "너는 해양수산부 항만국 정책 보고서 작성 전문관이다.\n"
    "토론 내용과 판정 결과를 바탕으로 공식 검토 보고서 초안을 작성하라.\n\n"
    "반드시 아래 형식 그대로 출력하라 (각 섹션 제목 유지, 개조식 문체 사용):\n\n"
    "# 검토 보고서\n\n"
    "## 1. 검토 개요\n"
    "- **검토 주제**: (주제명)\n"
    "- **검토 일시**: (오늘 날짜)\n"
    "- **검토 방식**: AI 다중에이전트 정책 검토 (찬성·반대·법령·청중·판정)\n\n"
    "## 2. 현황 및 주요 쟁점\n"
    "- (찬성 측 핵심 논거 2~3개, 개조식)\n"
    "- (반대 측 핵심 논거 2~3개, 개조식)\n\n"
    "## 3. 법령·예산 근거 검토\n"
    "- (팩트체커가 확인한 법령·지침 관련 사항, 없으면 '팩트체크 미실시 또는 이상 없음')\n\n"
    "## 4. 판정 및 권고사항\n"
    "- **종합 판정**: (승인 권고/조건부 승인/재검토 필요/반려)\n"
    "- **판정 근거**: (Judge의 ①~⑥ 항목 요약)\n"
    "- **주요 권고사항**: (개조식 2~4개)\n\n"
    "## 5. 시행점검 결과 (양식: 260120 보고안 표준)\n"
    "각 항목은 반드시 아래 3계층 구조를 유지하라:\n"
    "- **(추진현황)** 현재 단계·진척도·주요 일정 (1~3 bullets)\n"
    "- **(점검사항)** 실태조사로 확인된 문제·리스크·미비점 (1~3 bullets)\n"
    "- **(조치계획)** 향후 처리 방향·책임 부서·기한 (1~3 bullets)\n"
    "※ 토론에서 다뤄진 핵심 사안 1~3건에 대해 위 3계층을 반복 적용.\n\n"
    "## 6. 예상 질의·응답 (Q&A)\n"
    "Q1. (예상되는 국회·감사·내부 지적 질문)\n"
    "A1. (방어 논리)\n"
    "Q2. (예상 질문)\n"
    "A2. (방어 논리)\n\n"
    "## 7. 향후 추진 일정(안)\n"
    "- (단기) \n"
    "- (중기) \n"
    "- (장기) \n\n"
    "※ 출처 근거 없는 내용은 '추가 확인 필요'로 명시할 것.\n"
    "※ 토론에서 RAG 근거(\"근거1\", \"근거2\" 등)가 인용된 경우 보고서에도 그대로 표기할 것.\n"
    "총 1800자 이내."
)


def generate_report(
    topic: str,
    messages: list[dict],
    verdict: str,
    backend_key: str | None = None,
    on_progress: Callable | None = None,
) -> str:
    """
    Phase 2: 토론 메시지와 판정을 받아 공문서 형식 보고서 초안을 생성.
    반환값: 마크다운 보고서 문자열
    """
    if backend_key is None:
        backend_key = DEFAULT_BACKEND_KEY

    seed = _topic_seed(topic)
    agent_llm = make_agent_llm_config(backend_key, max_tokens=2400, seed=seed)

    # 토론 요약 컨텍스트 구성 (핵심 발언만 추림)
    summary_parts: list[str] = []
    role_map = {
        "pro": "【정책 추진 측】",
        "con": "【재정 심사 측】",
        "fact": "【법령 검토】",
        "judge": "【판정관】",
        "audience": "【현장 질의】",
    }
    for m in messages:
        name = m.get("name", "")
        content = m.get("content", "").strip()
        if not content or len(content) < 20:
            continue
        # 시스템 컨텍스트 블록 제외
        if content.startswith("[참고 자료") or content.startswith("[토론 주제") or content.startswith("### "):
            continue
        label = role_map.get(name, name)
        summary_parts.append(f"{label}\n{content[:400]}")

    debate_summary = "\n\n".join(summary_parts[-20:])  # 최근 20개 발언만
    verdict_text = verdict[:600] if verdict else "판정 없음"

    context_msg = (
        f"[검토 주제] {topic}\n\n"
        f"[최종 판정]\n{verdict_text}\n\n"
        f"[토론 내용 요약]\n{debate_summary}\n\n"
        "위 토론 내용을 바탕으로 공식 검토 보고서 초안을 작성하라."
    )

    if on_progress:
        on_progress({"name": "report_writer", "content": "📝 보고서 초안 작성 중…"})

    try:
        writer = autogen.AssistantAgent(
            name="report_writer",
            system_message=_REPORT_WRITER_PROMPT,
            llm_config=agent_llm,
            human_input_mode="NEVER",
            code_execution_config=False,
        )
        # UserProxy로 단일 메시지 교환
        proxy = autogen.UserProxyAgent(
            name="report_proxy",
            human_input_mode="NEVER",
            code_execution_config=False,
            max_consecutive_auto_reply=1,
        )
        proxy.initiate_chat(writer, message=context_msg, silent=True)

        # writer의 마지막 응답 추출
        report_text = ""
        for m in reversed(proxy.chat_messages.get(writer, [])):
            if m.get("role") == "assistant" and m.get("content"):
                report_text = m["content"].strip()
                break

        if on_progress:
            on_progress({"name": "report_writer", "content": "✅ 보고서 초안 완성"})

        return report_text if report_text else "[보고서 생성 실패: 응답 없음]"

    except Exception as e:
        err = f"[보고서 생성 실패: {e}]"
        if on_progress:
            on_progress({"name": "report_writer", "content": err})
        return err


# ── Phase 4: Self-Correction Reviewer ───────────────────────────────────────

_REVIEWER_PROMPT = (
    "너는 해양수산부 문서 검수 담당관이다.\n"
    "아래 보고서 초안을 검토하여 문제점을 찾고 수정 지시를 내려라.\n\n"
    "검수 항목:\n"
    "① 개조식 문체 준수 여부 (서술형 문장이 있으면 지적)\n"
    "② 법령·예산 근거 누락 여부 (근거 없는 주장이 있으면 지적)\n"
    "③ ①~⑥ 판정 항목 누락 여부\n"
    "④ '추가 확인 필요' 없이 불명확한 단정 여부\n"
    "⑤ Q&A 섹션의 질문이 실제 현실적 공격 포인트인지\n"
    "⑥ (양식) '시행점검 결과' 섹션의 (추진현황)/(점검사항)/(조치계획) 3계층이 모두 있는지\n"
    "⑦ (인용) RAG 근거가 토론에 등장했다면 보고서에도 '근거N' 표기가 유지되는지\n\n"
    "출력 형식:\n"
    "## 검수 결과\n"
    "- **통과 항목**: (문제없는 항목 나열)\n"
    "- **수정 필요 항목**: (구체적 문제점과 수정 지시, 없으면 '없음')\n"
    "## 검수 결론: [통과/수정 필요]\n\n"
    "총 500자 이내."
)


def review_report(
    report_text: str,
    backend_key: str | None = None,
) -> tuple[str, bool]:
    """
    Phase 4: 생성된 보고서를 검수하고 (검수 결과, 통과 여부)를 반환.
    """
    if backend_key is None:
        backend_key = DEFAULT_BACKEND_KEY

    seed = _topic_seed(report_text[:50])
    agent_llm = make_agent_llm_config(backend_key, max_tokens=600, seed=seed)

    try:
        reviewer = autogen.AssistantAgent(
            name="reviewer",
            system_message=_REVIEWER_PROMPT,
            llm_config=agent_llm,
            human_input_mode="NEVER",
            code_execution_config=False,
        )
        proxy = autogen.UserProxyAgent(
            name="review_proxy",
            human_input_mode="NEVER",
            code_execution_config=False,
            max_consecutive_auto_reply=1,
        )
        proxy.initiate_chat(
            reviewer,
            message=f"[보고서 초안 검수 요청]\n\n{report_text[:2000]}",
            silent=True,
        )

        review_text = ""
        for m in reversed(proxy.chat_messages.get(reviewer, [])):
            if m.get("role") == "assistant" and m.get("content"):
                review_text = m["content"].strip()
                break

        passed = "검수 결론: [통과]" in review_text or "수정 필요 항목**: 없음" in review_text
        return review_text, passed

    except Exception as e:
        return f"[검수 실패: {e}]", True  # 실패 시 통과 처리로 폴백


def generate_report_with_review(
    topic: str,
    messages: list[dict],
    verdict: str,
    backend_key: str | None = None,
    on_progress: Callable | None = None,
    max_revisions: int = 1,
) -> tuple[str, str]:
    """
    Phase 2+4: 보고서 생성 후 Self-Correction 루프 적용.
    반환값: (최종 보고서, 검수 결과)
    max_revisions: 재작성 최대 횟수 (기본 1회)
    """
    report = generate_report(topic, messages, verdict, backend_key, on_progress)

    for attempt in range(max_revisions):
        review_result, passed = review_report(report, backend_key)
        if passed:
            return report, review_result
        # 수정 필요: 검수 결과를 반영하여 재생성
        if on_progress:
            on_progress({"name": "reviewer", "content": f"🔄 보고서 수정 중 (시도 {attempt + 1}/{max_revisions})…"})
        # 검수 결과를 컨텍스트에 추가하여 재생성
        revised_messages = messages + [{"name": "reviewer", "role": "assistant", "content": review_result}]
        report = generate_report(topic, revised_messages, verdict, backend_key, on_progress)

    final_review, _ = review_report(report, backend_key)
    return report, final_review
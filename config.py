from __future__ import annotations

import os
import functools
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

# ── 선택 가능한 백엔드 옵션 (label → (model_id, api_key, base_url)) ──────────
AGENT_BACKEND_OPTIONS: dict[str, tuple[str, str, str]] = {
    # ── Google Gemini ──────────────────────────────────────────────────────────
    "openrouter/gemini-3.1-pro":         ("google/gemini-3.1-pro-preview",        OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/gemini-3-flash":          ("google/gemini-3-flash-preview",         OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/gemini-2.5-flash":        ("google/gemini-2.5-flash",               OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/gemini-2.5-flash-lite":   ("google/gemini-2.5-flash-lite",          OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    # ── xAI Grok ──────────────────────────────────────────────────────────────
    "openrouter/grok-3":                  ("x-ai/grok-3",                           OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/grok-3-mini":             ("x-ai/grok-3-mini",                      OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    # ── DeepSeek ──────────────────────────────────────────────────────────────
    "openrouter/deepseek-r1":             ("deepseek/deepseek-r1",                  OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/deepseek-chat-v3":        ("deepseek/deepseek-chat-v3-0324",        OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    # ── Zhipu GLM ─────────────────────────────────────────────────────────────
    "openrouter/glm-5":                   ("z-ai/glm-5",                            OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    # ── Moonshot Kimi ─────────────────────────────────────────────────────────
    "openrouter/kimi-k2":                 ("moonshotai/kimi-k2",                    OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/kimi-k2-thinking":        ("moonshotai/kimi-k2-thinking",           OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/kimi-k2.5":              ("moonshotai/kimi-k2.5",                  OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    # ── Anthropic Claude ──────────────────────────────────────────────────────
    "openrouter/claude-sonnet-4.5":       ("anthropic/claude-sonnet-4.5",           OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/claude-sonnet-4":         ("anthropic/claude-sonnet-4",             OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/claude-opus-4":           ("anthropic/claude-opus-4",               OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/claude-haiku-4.5":        ("anthropic/claude-haiku-4.5",            OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    # ── OpenAI GPT / Codex ────────────────────────────────────────────────────
    "openrouter/gpt-4.1":                 ("openai/gpt-4.1",                        OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/gpt-4.1-mini":            ("openai/gpt-4.1-mini",                   OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/o3":                      ("openai/o3",                             OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/o4-mini":                 ("openai/o4-mini",                        OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/codex":                   ("openai/gpt-5-codex",                    OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/codex-mini":              ("openai/gpt-5.1-codex-mini",             OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    # ── Mistral Devstral / Codestral (개발 특화) ──────────────────────────────
    "openrouter/devstral-small":          ("mistralai/devstral-small",              OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/devstral-medium":         ("mistralai/devstral-medium",             OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/codestral":               ("mistralai/codestral-2508",              OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    # ── Qwen3 Coder (개발 특화) ───────────────────────────────────────────────
    "openrouter/qwen3-coder":             ("qwen/qwen3-coder",                      OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/qwen3-coder-flash":       ("qwen/qwen3-coder-flash",                OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/qwen3-coder:free":        ("qwen/qwen3-coder:free",                 OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    # ── Meta Llama 4 ──────────────────────────────────────────────────────────
    "openrouter/llama-4-maverick":        ("meta-llama/llama-4-maverick",           OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    "openrouter/llama-4-scout":           ("meta-llama/llama-4-scout",              OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    # ── Writer Palmyra ────────────────────────────────────────────────────────
    "openrouter/palmyra-x5":              ("writer/palmyra-x5",                     OPENROUTER_API_KEY, OPENROUTER_BASE_URL),
    # ── NVIDIA ────────────────────────────────────────────────────────────────
    "nvidia/llama-3.3-70b":               ("meta/llama-3.3-70b-instruct",           NVIDIA_API_KEY,     NVIDIA_BASE_URL),
}

# 기본 사용 백엔드
DEFAULT_BACKEND_KEY = "openrouter/gemini-3-flash"

# ── Phase 2: 행정 문체 사전 + 금칙어 ────────────────────────────────────────
# apply_style_rules(text) → (cleaned, replacements[]) 함수는 refiner.py에 있음.
# 여기서 규칙을 중앙 관리하면 debate.py / refiner.py 모두 재사용 가능.

WEAK_PHRASE_REPLACEMENTS: dict[str, str] = {
    # 막연한 가능성 표현
    "사료됩니다":           "판단됩니다",
    "사료된다":             "판단된다",
    "사료됨":               "판단됨",
    "할 수 있을 것":        "가능",
    "가능할 것으로":        "가능하며",
    "될 것으로 판단됩니다": "됩니다",
    "볼 수 있습니다":       "확인됩니다",
    "보임":                 "확인됨",
    "보입니다":             "확인됩니다",
    "생각됩니다":           "판단됩니다",
    "생각됨":               "판단됨",
    # 수동·소극적 표현
    "검토 가능합니다":      "추진 필요합니다",
    "검토가 필요할 것":     "검토가 필요하며",
    "대응 가능":            "대응 가능하며",
    "적극 검토 예정":       "즉시 검토 착수",
    "추진 예정입니다":      "추진합니다",
    "추진할 예정":          "추진",
    "추후 검토":            "차기 계획에 반영",
    "필요할 것으로 보임":   "필요함",
    # 불확실 단어
    "어느 정도":            "일부",
    "다소":                 "일부",
    "비교적":               "상대적으로",
    "상당 부분":            "대부분",
    "많은 경우":            "대다수 경우",
    "경우에 따라":          "상황에 따라",
    # 관료적 중복 표현
    "을/를 위한 방안 마련": "방안 수립",
    "을/를 위해 노력":      "추진",
    "적극 노력하겠습니다":  "추진합니다",
    "최선을 다하겠습니다":  "이행합니다",
    "지속적으로 노력":      "지속 추진",
}

FORBIDDEN_PHRASES: list[str] = [
    # 과장·정치 홍보성 수사
    "역대 최고",
    "전례 없는 성과",
    "압도적인",
    "괴물급",
    "완벽하게 장악",
    "초격차",
    "용산급",
    "대통령실 표준",
    "국정 관제",
    # AI 산출물 티 나는 표현
    "물론입니다",
    "아주 좋은 질문",
    "말씀하신 대로",
    "확실히",
    "당연히",
]

CACHE_FILE = Path(__file__).parent / "model_cache.json"


def _openrouter_static_key_by_model_id() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for key, (model_id, api_key, base_url) in AGENT_BACKEND_OPTIONS.items():
        if api_key == OPENROUTER_API_KEY and base_url == OPENROUTER_BASE_URL:
            mapping[model_id] = key
    return mapping


def _model_id_to_backend_key(model_id: str, profile: str = "economy") -> str:
    if not model_id:
        return DEFAULT_BACKEND_KEY
    if profile == "economy" or model_id.endswith(":free"):
        return f"free/{model_id}"
    static_map = _openrouter_static_key_by_model_id()
    if model_id in static_map:
        return static_map[model_id]
    return model_id


def _pick_quality_premium_candidate(candidates: list[dict], role: str = "") -> str:
    """최대 품질에서는 역할별 상급 유료 모델 티어를 우선 선택한다."""
    role_tiers = {
        "judge": (
            ("claude-opus", "claude-sonnet", "openai/o3", "openai/o4", "deepseek-r1", "chimera"),
            ("claude", "deepseek", "o3", "o4", "grok-3", "gemini-3.1"),
            ("plus", "pro", "max"),
        ),
        "fact": (
            ("claude-sonnet", "claude-opus", "deepseek-r1", "openai/o3", "openai/o4", "chimera"),
            ("claude", "deepseek", "o3", "o4", "gemini-3.1", "grok-3"),
            ("plus", "pro", "max"),
        ),
        "pro": (
            ("claude-sonnet", "claude-opus", "grok-3", "gemini-3.1", "openai/o3"),
            ("claude", "grok", "gemini", "deepseek"),
            ("plus", "pro", "max"),
        ),
        "con": (
            ("claude-sonnet", "claude-opus", "grok-3", "gemini-3.1", "openai/o3"),
            ("claude", "grok", "gemini", "deepseek"),
            ("plus", "pro", "max"),
        ),
        "audience": (
            ("minimax", "claude-haiku", "gpt-4.1-mini", "gemini-2.5-flash", "grok-3-mini"),
            ("mini", "flash", "small", "haiku"),
        ),
    }
    premium_tiers = role_tiers.get(role, role_tiers["judge"])
    paid_candidates = [c.get("id", "") for c in candidates if c.get("id") and not c.get("id", "").endswith(":free")]
    for tier in premium_tiers:
        for model_id in paid_candidates:
            lowered = model_id.lower()
            if any(keyword in lowered for keyword in tier):
                return model_id
    for model_id in paid_candidates:
        if model_id:
            return model_id
    return ""


def load_model_cache() -> dict:
    """model_cache.json 로드. 없으면 빈 dict 반환."""
    if CACHE_FILE.exists():
        try:
            import json
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def get_free_models_as_backends() -> dict[str, tuple[str, str, str]]:
    """
    캐시에서 무료 모델 목록을 읽어 AGENT_BACKEND_OPTIONS 형식으로 반환.
    free_models_refined(신규) → free_models(구버전 호환) 순으로 시도.
    gemma 계열은 rate-limit 빈번으로 제외.
    """
    cache = load_model_cache()
    result: dict[str, tuple[str, str, str]] = {}
    source = cache.get("free_models_refined") or cache.get("free_models") or []
    # 실용성 낮은 모델 제외 키워드
    _EXCLUDE_KW = ["gemma", "ocr", "lyria", "dolphin", "preview", "lfm-2.5-1.2b",
                   "llama-3.2-3b", "nemotron-nano-9b", "nemotron-nano-12b", "vl:free"]
    _EXCLUDE_IDS = {"tencent/hy3-preview"}
    for m in source:
        model_id = m["id"] if isinstance(m, dict) else m
        if any(kw in model_id.lower() for kw in _EXCLUDE_KW):
            continue
        if model_id in _EXCLUDE_IDS:
            continue
        key = f"free/{model_id}"
        result[key] = (model_id, OPENROUTER_API_KEY, OPENROUTER_BASE_URL)
    return result


def get_cached_openrouter_models_as_backends() -> dict[str, tuple[str, str, str]]:
    """
    캐시에서 사용 가능한 OpenRouter 텍스트 모델 전체를 읽어 반환한다.
    - 동적 모델 키는 실제 model_id를 그대로 사용한다.
    - 이미 고정 옵션으로 등록된 모델은 중복 추가하지 않는다.
    """
    cache = load_model_cache()
    result: dict[str, tuple[str, str, str]] = {}
    source = cache.get("curated_openrouter_models") or cache.get("cleaned_models") or []
    static_model_ids = set(_openrouter_static_key_by_model_id().keys())
    _EXCLUDE_KW = [
        "gemma", "ocr", "lyria", "dolphin", "preview", "lfm-2.5-1.2b",
        "llama-3.2-3b", "nemotron-nano-9b", "nemotron-nano-12b", "vl:free",
    ]
    _EXCLUDE_IDS = {"tencent/hy3-preview"}
    for m in source:
        model_id = m["id"] if isinstance(m, dict) else m
        if model_id in static_model_ids:
            continue
        if any(kw in model_id.lower() for kw in _EXCLUDE_KW):
            continue
        if model_id in _EXCLUDE_IDS:
            continue
        result[model_id] = (model_id, OPENROUTER_API_KEY, OPENROUTER_BASE_URL)
    return result


def get_auto_recommended_key() -> str:
    """캐시의 자동 추천 모델을 free/... 형식 key로 반환. 없으면 DEFAULT."""
    cache = load_model_cache()
    model_id = cache.get("auto_recommended", "")
    if model_id:
        return f"free/{model_id}"
    return DEFAULT_BACKEND_KEY


def get_auto_recommended_backends(
    profile: str = "economy",
) -> dict[str, str]:
    """
    역할별 최적 모델 key를 반환한다.
    - profile: 'economy' | 'balanced' | 'quality'
    - economy이면 default_free_per_role 사용
    - balanced/quality이면 ranked_candidates_all 1순위(무료 우선) 사용
    반환 형식: {"pro": "free/...", "con": "free/...", ...}
    """
    cache = load_model_cache()
    roles = ["pro", "con", "judge", "fact", "audience"]

    per_profile = cache.get("default_per_role_by_profile") or {}
    if profile in per_profile:
        selected = {
            role: per_profile.get(profile, {}).get(role, "")
            for role in roles
        }
        if profile == "quality":
            ranked_by_profile = cache.get("ranked_candidates_by_profile") or {}
            ranked_quality = ranked_by_profile.get("quality", {})
            for role in ("judge", "fact", "pro", "con", "audience"):
                premium_choice = _pick_quality_premium_candidate(ranked_quality.get(role, []), role)
                if premium_choice:
                    selected[role] = premium_choice
        return {
            role: _model_id_to_backend_key(selected.get(role, ""), profile)
            for role in roles
        }

    # 캐시에 역할별 배정이 있는지 확인
    per_role_free = cache.get("default_free_per_role") or {}
    per_role_all  = cache.get("ranked_candidates_all") or {}

    result: dict[str, str] = {}
    for role in roles:
        model_id = ""
        if profile in ("balanced", "quality") and role in per_role_all:
            candidates = [c for c in per_role_all[role] if "gemma" not in c["id"].lower()]
            if candidates:
                model_id = candidates[0]["id"]
        if not model_id and role in per_role_free:
            model_id = per_role_free[role] if "gemma" not in per_role_free[role].lower() else ""
        if not model_id:
            model_id = cache.get("auto_recommended", "")
            if "gemma" in (model_id or "").lower():
                model_id = ""
        result[role] = _model_id_to_backend_key(model_id, profile)

    return result


def get_default_free_backends() -> dict[str, str]:
    """기본값 초기화용 — 항상 무료 기본 세트만 반환."""
    cache = load_model_cache()
    per_role_free = cache.get("default_free_per_role") or {}
    roles = ["pro", "con", "judge", "fact", "audience"]
    result: dict[str, str] = {}
    for role in roles:
        model_id = per_role_free.get(role, "")
        result[role] = f"free/{model_id}" if model_id else DEFAULT_BACKEND_KEY
    return result


def get_profile_presets() -> dict:
    """캐시에서 비용 프로필 정의를 읽는다. 없으면 기본 정의 반환."""
    cache = load_model_cache()
    return cache.get("profile_presets") or {
        "economy":  {"label": "💰절약",  "use_llm_recommender": False, "recommender_cost_cap_usd": 0.0},
        "balanced": {"label": "⚡균형",  "use_llm_recommender": True,  "recommender_cost_cap_usd": 0.005},
        "quality":  {"label": "✨최대",  "use_llm_recommender": True,  "recommender_cost_cap_usd": 0.005},
    }


def get_ranked_candidates(role: str, top_k: int = 3) -> list[dict]:
    """역할별 상위 후보 모델 메타데이터를 반환 (2차 추천기 입력용)."""
    cache = load_model_cache()
    ranked = cache.get("ranked_candidates_all") or {}
    return ranked.get(role, [])[:top_k]


# ── Phase 9: 멀티모델 라우터 ─────────────────────────────────────────────────
_ROUTING_CONFIG: dict | None = None

def _load_routing_config() -> dict:
    global _ROUTING_CONFIG
    if _ROUTING_CONFIG is not None:
        return _ROUTING_CONFIG
    routing_path = Path(__file__).parent / "config" / "model_routing.yaml"
    try:
        import yaml  # type: ignore
        if routing_path.exists():
            _ROUTING_CONFIG = yaml.safe_load(routing_path.read_text(encoding="utf-8")) or {}
            return _ROUTING_CONFIG
    except Exception:
        pass
    _ROUTING_CONFIG = {}
    return _ROUTING_CONFIG


def get_routed_backends(quality_profile: str = "balanced") -> dict[str, str]:
    """
    Phase 9: model_routing.yaml 기반 역할별 최적 모델 키를 반환.
    반환 형식: {"pro": "openrouter/...", "con": "openrouter/...", ...}
    quality_profile: "economy" | "balanced" | "quality"
    """
    routing = _load_routing_config()
    roles = ["pro", "con", "judge", "fact", "audience"]

    # economy: 무료 모델 자동 배정으로 위임
    if quality_profile == "economy":
        return get_default_free_backends()

    # quality: YAML quality_profiles.quality 섹션 우선
    quality_overrides: dict = {}
    if quality_profile == "quality":
        quality_overrides = routing.get("quality_profiles", {}).get("quality", {})

    result: dict[str, str] = {}
    for role in roles:
        # quality 오버라이드 먼저 확인
        if role in quality_overrides:
            candidate = quality_overrides[role]
            if candidate in AGENT_BACKEND_OPTIONS:
                result[role] = candidate
                continue
        # roles 섹션 순서대로: primary → fallback1 → fallback2
        role_cfg = routing.get("roles", {}).get(role, {})
        assigned = ""
        for field in ("primary", "fallback1", "fallback2"):
            candidate = role_cfg.get(field, "")
            if candidate and candidate in AGENT_BACKEND_OPTIONS:
                assigned = candidate
                break
        result[role] = assigned if assigned else DEFAULT_BACKEND_KEY

    return result


def get_report_writer_backend(quality_profile: str = "balanced") -> str:
    """Phase 9: ReportWriter 전용 모델 키 반환."""
    routing = _load_routing_config()
    if quality_profile == "economy":
        return DEFAULT_BACKEND_KEY
    rw_cfg = routing.get("report_writer", {})
    primary = rw_cfg.get("primary", "")
    if primary and primary in AGENT_BACKEND_OPTIONS:
        return primary
    return DEFAULT_BACKEND_KEY


def get_reviewer_backend(quality_profile: str = "balanced") -> str:
    """Phase 9: Reviewer 전용 모델 키 반환."""
    routing = _load_routing_config()
    if quality_profile == "economy":
        return DEFAULT_BACKEND_KEY
    rv_cfg = routing.get("reviewer", {})
    primary = rv_cfg.get("primary", "")
    if primary and primary in AGENT_BACKEND_OPTIONS:
        return primary
    return DEFAULT_BACKEND_KEY

# ── 전역 단일 설정 (하위 호환용, debate.py 기본값) ──────────────────────────
BACKEND = os.environ.get("GA_BACKEND", "openrouter")
ACTIVE_MODEL = os.environ.get("GA_MODEL", "google/gemini-2.5-flash")
_api_key   = NVIDIA_API_KEY if BACKEND == "nvidia" else OPENROUTER_API_KEY
_base_url  = NVIDIA_BASE_URL if BACKEND == "nvidia" else OPENROUTER_BASE_URL

# 에이전트 공통 LLM 설정 (기본)
LLM_CONFIG: dict = {
    "config_list": [
        {
            "model": ACTIVE_MODEL,
            "api_key": _api_key,
            "base_url": _base_url,
            "max_tokens": 180,
        }
    ],
    "temperature": 0.3,
    "timeout": 40,
    "cache_seed": None,
}

# GroupChatManager 전용
MANAGER_LLM_CONFIG: dict = {
    "config_list": [
        {
            "model": ACTIVE_MODEL,
            "api_key": _api_key,
            "base_url": _base_url,
            "max_tokens": 50,
        }
    ],
    "temperature": 0.0,
    "timeout": 25,
    "cache_seed": None,
}


def _resolve_backend(backend_key: str) -> tuple[str, str, str]:
    """backend_key → (model_id, api_key, base_url). free/ 프리픽스 지원."""
    if backend_key in AGENT_BACKEND_OPTIONS:
        return AGENT_BACKEND_OPTIONS[backend_key]
    if backend_key.startswith("free/"):
        model_id = backend_key[len("free/"):]
        return (model_id, OPENROUTER_API_KEY, OPENROUTER_BASE_URL)
    # 기본값 폴백
    return AGENT_BACKEND_OPTIONS[DEFAULT_BACKEND_KEY]


def make_agent_llm_config(backend_key: str, max_tokens: int = 180, seed: int | None = None) -> dict:
    """backend_key → AutoGen LLM config dict."""
    model, api_key, base_url = _resolve_backend(backend_key)
    return {
        "config_list": [
            {"model": model, "api_key": api_key, "base_url": base_url, "max_tokens": max_tokens}
        ],
        "temperature": 0.3,
        "timeout": 40,
        "cache_seed": seed,
    }


def make_manager_llm_config(backend_key: str, seed: int | None = None) -> dict:
    model, api_key, base_url = _resolve_backend(backend_key)
    return {
        "config_list": [
            {"model": model, "api_key": api_key, "base_url": base_url, "max_tokens": 50}
        ],
        "temperature": 0.0,
        "timeout": 25,
        "cache_seed": seed,
    }


MAX_HISTORY = 8
MAX_ROUND = 6

# ── 토큰 정책 (역할별 기본값, debate.py에서 모델 상한에 맞게 동적 조정됨) ──
ROLE_MAX_TOKENS: dict[str, int] = {
    "pro":      400,
    "con":      400,
    "judge":    500,
    "fact":     450,
    "audience": 220,
}
ROLE_MAX_TOKENS_CAP: dict[str, int] = {
    "pro":      600,
    "con":      600,
    "judge":    800,
    "fact":     700,
    "audience": 300,
}

PROMPTS: dict[str, str] = {
    "pro": (
        "너는 토론의 찬성 측 전문가다. 매 발언마다 이전에 하지 않은 새로운 논거나 반박을 제시하라."
        " 다른 에이전트의 발언을 요약하거나 반복하지 마라.\n\n"
        "아래 형식을 사용하라:\n"
        "## 주장\n"
        "- <찬성 근거 1: 구체적 사실·수치·사례 포함>\n"
        "- <찬성 근거 2>\n\n"
        "## 근거\n"
        "- <뒷받침 데이터나 실증 사례>\n\n"
        "## 정책적 함의\n"
        "- <이 입장이 채택되면 나타날 실질적 결과>"
    ),
    "con": (
        "너는 토론의 반대 측 전문가다. 매 발언마다 찬성 측의 새로운 허점을 공격하거나 대안 논거를 제시하라."
        " 다른 에이전트의 발언을 요약하거나 반복하지 마라.\n\n"
        "아래 형식을 사용하라:\n"
        "## 반박\n"
        "- <반대 근거 1: 찬성 측 주장의 구체적 약점이나 오류>\n"
        "- <반대 근거 2>\n\n"
        "## 근거\n"
        "- <뒷받침 데이터나 반례>\n\n"
        "## 정책적 함의\n"
        "- <이 입장이 채택되면 나타날 실질적 결과 또는 더 나은 대안>"
    ),
    "judge": (
        "너는 정부 정책 심판 위원이다. 토론 내용을 검토하여 아래 6항목 체크리스트 형식으로 판정하라.\n\n"
        "## 정책 검토 판정\n\n"
        "① **법적 타당성**: <관련 법령·예규 근거 확인 여부, 위법 소지 판단>\n"
        "② **예산 적정성**: <요구 예산의 규모·집행 가능성·비용 대비 효과>\n"
        "③ **정책 정합성**: <상위 계획·부처 방향과의 일치 여부>\n"
        "④ **집행 가능성**: <인력·시간·협업 기관 측면에서 실현 가능성>\n"
        "⑤ **주요 리스크**: <예상되는 핵심 위험 요인 1~3가지>\n"
        "⑥ **종합 판정**: 다음 중 하나로 명시\n"
        "   - [승인권고]: 조건 없이 추진 권장\n"
        "   - [조건부승인]: 특정 조건 이행 후 추진 가능\n"
        "   - [재검토필요]: 보완 사항 해소 후 재심\n"
        "   - [반려]: 근본적 문제로 추진 불가\n\n"
        "평가 기준: 논리력·법령 근거·예산 합리성·반박력.\n"
        "핵심 논점 교환이 충분히 이뤄져 결론을 낼 수 있고 최소 4라운드가 지났으면 마지막 줄에 [합의됨]을 추가하라.\n"
        "토론을 더 진행해야 하면 마지막 줄에 [계속]을 추가하라."
    ),
    "fact": (
        "너는 팩트체커다. 직전 발언에서 사실 오류·과장·미확인 주장을 찾아라.\n\n"
        "아래 형식을 사용하라:\n"
        "## 팩트체크\n"
        "- **(주장)**: <직전 발언의 검증 대상 주장>\n"
        "- **(검증)**: <사실 여부 — 확인됨 / 과장됨 / 오류 / 미확인>\n"
        "- **(불확실성)**: <확인하지 못한 부분이 있다면 간략히>\n"
        "- **(출처 힌트)**: <관련 기관·보고서·통계 이름 (알고 있는 경우)>\n\n"
        "오류가 전혀 없으면 '## 팩트체크\n- 이상無' 라고만 답하라."
    ),
    "audience": (
        "너는 일반 시민 청중을 대표한다. 토론 내용을 바탕으로 아직 다뤄지지 않은 날카로운 질문 2~3개를 던져라.\n\n"
        "아래 형식을 사용하라:\n"
        "## 청중 질문\n"
        "1. <질문 1 — 두 측이 답하지 않은 실질적 쟁점>\n"
        "2. <질문 2 — 현실적 영향이나 구체적 이해관계>\n"
        "3. <질문 3 — 선택 사항>\n\n"
        "요약, 평가, 입장 표명은 하지 마라."
    ),
}

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / ".cache"
RESULTS_DIR = BASE_DIR / "results"
DB_PATH = Path(os.environ.get("GA_DB_PATH", str(BASE_DIR / "results" / "ga.db")))
MODES_DIR = BASE_DIR / "config" / "modes"

CACHE_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)


# ── 토론 모드 레지스트리 ────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def load_debate_modes() -> dict:
    """
    config/modes/*.yaml 을 읽어 모드 레지스트리를 반환한다.
    반환 형식: {"debate": {...}, "strengths": {...}, "weaknesses": {...}}
    YAML 없이도 작동하는 하드코딩 폴백 포함.
    """
    try:
        import yaml  # type: ignore
        _yaml_available = True
    except ImportError:
        _yaml_available = False

    modes: dict = {}
    if _yaml_available and MODES_DIR.exists():
        for yaml_file in sorted(MODES_DIR.glob("*.yaml")):
            try:
                data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                if data and "id" in data:
                    modes[data["id"]] = data
            except Exception:
                continue

    # YAML 로드 실패 시 최소 폴백 (기존 동작 유지)
    if "debate" not in modes:
        modes["debate"] = {
            "id": "debate", "label": "🥊 찬반 토론", "icon": "🥊",
            "description": "두 가지 대립 관점에서 주제를 분석합니다.",
            "theme": {"primary": "#f59e0b", "agent_colors": {
                "pro": "#3b82f6", "con": "#ef4444", "judge": "#d29922",
                "fact": "#10b981", "audience": "#8b5cf6"}},
            "roles": {
                "pro":      {"label": "🟦 찬성",  "desc": "사안을 지지하는 논리 구성"},
                "con":      {"label": "🟥 반대",  "desc": "반론 및 리스크 분석"},
                "judge":    {"label": "⚖️ 심판",  "desc": "중립적 종합 판정"},
                "fact":     {"label": "🔍 팩트",  "desc": "사실 관계 검증"},
                "audience": {"label": "👥 청중",  "desc": "시민 시각 대표"},
            },
            "stage_messages": {
                "pro": "🟦 찬성 측 논리 전개 중…", "con": "🟥 반대 측 반론 중…",
                "judge": "⚖️ 심판 합의 분석 중…", "fact": "🔍 팩트체커 검증 중…",
                "audience": "👥 청중 질문 생성 중…",
            },
            "search_boosters": [],
            "termination_tag": "[합의됨]", "min_rounds": 4,
            "initiate_role": "pro",
            "initiate_message": "찬성 측으로서 이 주제를 지지하는 핵심 논거 3가지를 구체적이고 상세하게 제시하라. 위에 제공된 검색 자료와 근거를 적극 활용하라.",
        }
    if "strengths" not in modes:
        modes["strengths"] = {
            "id": "strengths", "label": "💪 강점 분석", "icon": "💎",
            "description": "주제의 잠재력·기회·발전 전략을 다각도로 탐색합니다.",
            "theme": {"primary": "#10b981", "agent_colors": {
                "pro": "#10b981", "con": "#06b6d4", "judge": "#3b82f6",
                "fact": "#22c55e", "audience": "#34d399"}},
            "roles": {
                "pro":      {"label": "🌟 강점 발굴",   "desc": "핵심 강점과 차별화 요소 식별"},
                "con":      {"label": "🚀 발전 전략",   "desc": "강점 극대화 방안과 시너지 제안"},
                "judge":    {"label": "🏆 우선순위",    "desc": "ICE Score 기반 실행 우선순위 판정"},
                "fact":     {"label": "📈 근거 검증",   "desc": "성공 사례 및 정량 근거 검증"},
                "audience": {"label": "💬 수용성 평가", "desc": "이해관계자별 기대·반응 점검"},
            },
            "stage_messages": {
                "pro": "🌟 강점 발굴 중…", "con": "🚀 발전 전략 도출 중…",
                "judge": "🏆 우선순위 분석 중…", "fact": "📈 성공 사례 검증 중…",
                "audience": "💬 수용성 점검 중…",
            },
            "search_boosters": ["성공 사례", "best practice", "효과 및 편익"],
            "termination_tag": "[분석완료]", "min_rounds": 3,
            "initiate_role": "pro",
            "initiate_message": "이 주제의 핵심 강점과 잠재적 가치를 3가지 이상 구체적으로 제시하라. 각 강점마다 실증적 근거나 유사 사례를 포함하라.",
        }
    if "weaknesses" not in modes:
        modes["weaknesses"] = {
            "id": "weaknesses", "label": "🔍 약점 진단", "icon": "⚠️",
            "description": "주제의 리스크·취약점·실패 경로를 집중 분석합니다.",
            "theme": {"primary": "#ef4444", "agent_colors": {
                "pro": "#ef4444", "con": "#f97316", "judge": "#dc2626",
                "fact": "#fb923c", "audience": "#fbbf24"}},
            "roles": {
                "pro":      {"label": "⚠️ 취약점 탐색", "desc": "핵심 약점과 내재된 리스크 발굴"},
                "con":      {"label": "🔴 리스크 확장", "desc": "취약점이 유발할 연쇄 실패 경로"},
                "judge":    {"label": "📊 심각도 판정", "desc": "리스크 심각도·발생가능성 판정"},
                "fact":     {"label": "🧪 실패 검증",   "desc": "유사 실패 사례 및 경고 데이터"},
                "audience": {"label": "😟 우려 대표",   "desc": "피해 당사자 시각의 우려 대변"},
            },
            "stage_messages": {
                "pro": "⚠️ 취약점 발굴 중…", "con": "🔴 리스크 확장 분석 중…",
                "judge": "📊 심각도 판정 중…", "fact": "🧪 실패 사례 검증 중…",
                "audience": "😟 우려 및 반발 점검 중…",
            },
            "search_boosters": ["문제점", "실패 사례", "감사 지적", "리스크"],
            "termination_tag": "[진단완료]", "min_rounds": 3,
            "initiate_role": "pro",
            "initiate_message": "이 주제에서 가장 심각한 취약점과 잠재적 리스크를 3가지 이상 구체적으로 제시하라. 각 취약점마다 실패 가능 경로와 결과를 명확히 하라.",
        }
    return modes


def get_mode(mode_id: str) -> dict:
    """특정 모드의 설정 반환. 없으면 debate 반환."""
    return load_debate_modes().get(mode_id, load_debate_modes()["debate"])


def get_mode_prompts(mode_id: str) -> dict[str, str]:
    """모드별 역할 프롬프트 반환. YAML에 없으면 기본 PROMPTS 사용."""
    mode = get_mode(mode_id)
    yaml_prompts = mode.get("prompts") or {}
    if yaml_prompts:
        return yaml_prompts
    # debate 모드는 기존 PROMPTS 그대로 사용
    return PROMPTS


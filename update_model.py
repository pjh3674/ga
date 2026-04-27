#!/usr/bin/env python3
"""
매일 OpenRouter API에서 모델 목록을 가져와 메타데이터를 정제하고
역할별 최적 모델을 점수화하여 /home/pjh/apps/ga/model_cache.json 에 저장한다.

cron 예시:
  5 9 * * * /home/pjh/apps/ga/venv/bin/python /home/pjh/apps/ga/update_model.py >> /home/pjh/apps/ga/update_model.log 2>&1
"""
from __future__ import annotations

import json
import os
import math
import datetime
import requests
from pathlib import Path

CACHE_FILE = Path(__file__).parent / "model_cache.json"
OR_MODELS_API      = "https://openrouter.ai/api/v1/models"
OR_RANKINGS_URL    = "https://openrouter.ai/api/v1/models?order=top-weekly"

# ── 폴백 목록 (API 완전 실패 시) ──────────────────────────────────────────
FALLBACK_FREE = [
    {"id": "google/gemini-2.5-flash-lite",                   "name": "Gemini 2.5 Flash Lite",         "context_length": 1048576, "max_completion_tokens": 65536,  "pricing_prompt": "0",    "pricing_completion": "0",    "supported_parameters": []},
    {"id": "meta-llama/llama-4-scout:free",                  "name": "Llama 4 Scout (free)",           "context_length": 131072,  "max_completion_tokens": 16384,  "pricing_prompt": "0",    "pricing_completion": "0",    "supported_parameters": []},
    {"id": "meta-llama/llama-4-maverick:free",               "name": "Llama 4 Maverick (free)",        "context_length": 131072,  "max_completion_tokens": 16384,  "pricing_prompt": "0",    "pricing_completion": "0",    "supported_parameters": []},
    {"id": "deepseek/deepseek-chat-v3-0324:free",            "name": "DeepSeek Chat V3 (free)",        "context_length": 65536,   "max_completion_tokens": 8192,   "pricing_prompt": "0",    "pricing_completion": "0",    "supported_parameters": []},
    {"id": "mistralai/mistral-small-3.1-24b-instruct:free",  "name": "Mistral Small 3.1 (free)",       "context_length": 131072,  "max_completion_tokens": 16384,  "pricing_prompt": "0",    "pricing_completion": "0",    "supported_parameters": []},
]

# ── 비용 프로필 정의 ────────────────────────────────────────────────────────
# 각 프로필은 허용 가격대($/M tokens), 최소 context_length, 유료 후보 포함 여부를 선언한다.
PROFILE_PRESETS: dict[str, dict] = {
    "economy": {
        "label": "절약 (무료 전용)",
        "max_prompt_price_per_m": 0.0,       # 무료만
        "max_completion_price_per_m": 0.0,
        "min_context_length": 32768,
        "allow_paid": False,
        "use_llm_recommender": False,        # 추천 LLM 호출 생략
        "recommender_cost_cap_usd": 0.0,
    },
    "balanced": {
        "label": "균형 (저가 유료 포함)",
        "max_prompt_price_per_m": 0.5,       # ≤ $0.50/M prompt
        "max_completion_price_per_m": 1.5,
        "min_context_length": 32768,
        "allow_paid": True,
        "use_llm_recommender": True,
        "recommender_cost_cap_usd": 0.005,
    },
    "quality": {
        "label": "최대 품질 (중고가 유료 허용)",
        "max_prompt_price_per_m": 5.0,       # ≤ $5.00/M prompt
        "max_completion_price_per_m": 15.0,
        "min_context_length": 65536,
        "allow_paid": True,
        "use_llm_recommender": True,
        "recommender_cost_cap_usd": 0.005,
    },
}

# ── 역할별 배정 우선순위 키워드 (id 포함 시 가점) ─────────────────────────
ROLE_KEYWORD_BOOST: dict[str, list[str]] = {
    "judge":    ["deepseek-r1", "qwen3", "nemotron", "o3", "o4", "claude-opus", "grok-3", "gemini-3.1"],
    "fact":     ["deepseek-r1", "qwen3", "nemotron", "llama-4-maverick", "gemini-3"],
    "pro":      ["llama-4-maverick", "gemini-3", "claude-sonnet", "grok-3", "qwen3", "mistral"],
    "con":      ["llama-4-maverick", "gemini-3", "claude-sonnet", "grok-3", "qwen3", "mistral"],
    "audience": ["minimax", "gpt-oss", "glm", "scout", "flash-lite", "mini", "small", "ling"],  # gemma 제외 (rate-limit 빈번)
}

# ── 역할별 점수 가중치 (기본값, recommendation_log로 자동 조정됨) ──────────
DEFAULT_SCORING_WEIGHTS: dict[str, dict[str, float]] = {
    "judge": {
        "free_bonus":           10.0,
        "context_length":        8.0,
        "max_completion_tokens": 12.0,
        "structured_outputs":   15.0,   # supported_parameters에 있으면 가점
        "reasoning":            15.0,
        "price_penalty":         5.0,   # 가격이 높을수록 감점
        "keyword_boost":        10.0,
    },
    "fact": {
        "free_bonus":           10.0,
        "context_length":        5.0,
        "max_completion_tokens": 10.0,
        "structured_outputs":   10.0,
        "reasoning":            20.0,
        "price_penalty":         5.0,
        "keyword_boost":        10.0,
    },
    "pro": {
        "free_bonus":            8.0,
        "context_length":       12.0,
        "max_completion_tokens": 15.0,
        "structured_outputs":    3.0,
        "reasoning":             5.0,
        "price_penalty":         7.0,
        "keyword_boost":        10.0,
    },
    "con": {
        "free_bonus":            8.0,
        "context_length":       12.0,
        "max_completion_tokens": 15.0,
        "structured_outputs":    3.0,
        "reasoning":             5.0,
        "price_penalty":         7.0,
        "keyword_boost":        10.0,
    },
    "audience": {
        "free_bonus":           20.0,
        "context_length":        3.0,
        "max_completion_tokens": 5.0,
        "structured_outputs":    0.0,
        "reasoning":             0.0,
        "price_penalty":        15.0,   # 비쌀수록 크게 감점
        "keyword_boost":         7.0,
    },
}

PROFILE_WEIGHT_OVERRIDES: dict[str, dict[str, float]] = {
    "economy": {
        "free_bonus_scale": 1.0,
        "price_penalty_scale": 1.0,
        "paid_boost": 0.0,
        "reasoning_scale": 1.0,
        "structured_outputs_scale": 1.0,
        "context_length_scale": 1.0,
        "max_completion_tokens_scale": 1.0,
        "keyword_boost_scale": 1.0,
    },
    "balanced": {
        "free_bonus_scale": 0.6,
        "price_penalty_scale": 0.85,
        "paid_boost": 2.0,
        "reasoning_scale": 1.08,
        "structured_outputs_scale": 1.05,
        "context_length_scale": 1.0,
        "max_completion_tokens_scale": 1.0,
        "keyword_boost_scale": 1.0,
    },
    "quality": {
        "free_bonus_scale": 0.15,
        "price_penalty_scale": 0.3,
        "paid_boost": 7.0,
        "reasoning_scale": 1.35,
        "structured_outputs_scale": 1.25,
        "context_length_scale": 1.18,
        "max_completion_tokens_scale": 1.18,
        "keyword_boost_scale": 1.12,
    },
}

# 비텍스트·라우터·실험 preview 계열 제외 키워드 (id에 포함 시 제외)
EXCLUDE_KEYWORDS = [
    "audio", "clip", "video", "image", "tts", "stt", "embed",
    "vision-only", "free-router", "vl",          # 비전·멀티모달 제외
    "gemma",                                      # rate-limit 빈번
    "ocr",                                        # OCR 전용 모델
    "lyria",                                      # 음악 생성 모델
    "dolphin",                                    # 검열 해제 계열 불안정
    "preview",                                    # 불안정한 preview 모델
    "lfm-2.5-1.2b",                              # 1.2B 극소형 품질 낮음
    "llama-3.2-3b",                              # 3B 소형 품질 낮음
    "nemotron-nano-9b",                          # 소형 + 비전 모델
    "nemotron-nano-12b",                         # 비전 언어 모델
]
# 제외 ID 완전 일치
EXCLUDE_IDS = {
    "openrouter/free", "openrouter/auto",
    "tencent/hy3-preview",                        # 불안정 preview
}
# min max_completion_tokens 컷오프
MIN_MAX_COMPLETION_TOKENS = 1024


# ── 헬퍼 ─────────────────────────────────────────────────────────────────

def _price_to_float(val: str | float | int | None, default: float = 999.0) -> float:
    """OpenRouter 가격 문자열 → float ($/token). $/M token으로 환산 시 ×1_000_000."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def fetch_all_models(api_key: str | None = None) -> list[dict]:
    """OpenRouter /api/v1/models?order=top-weekly 전체 목록을 가져온다."""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    for url in [OR_RANKINGS_URL, OR_MODELS_API]:
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if data:
                return data
        except Exception as e:
            print(f"[WARN] {url} 요청 실패: {e}")
    return []


def _extract_meta(m: dict) -> dict:
    """원시 API 항목 → 정제된 메타데이터 dict."""
    pricing = m.get("pricing", {})
    arch    = m.get("architecture", {})
    tp      = m.get("top_provider") or {}
    params  = m.get("supported_parameters") or []
    return {
        "id":                    m["id"],
        "name":                  m.get("name", m["id"]),
        "context_length":        m.get("context_length") or 0,
        "max_completion_tokens": tp.get("max_completion_tokens") or 0,
        "output_modalities":     arch.get("output_modalities") or ["text"],
        "supported_parameters":  params,
        "pricing_prompt":        str(pricing.get("prompt",     "1")),
        "pricing_completion":    str(pricing.get("completion", "1")),
        "pricing_request":       str(pricing.get("request",    "0")),
        "pricing_internal_reasoning": str(pricing.get("internal_reasoning", "0")),
        "is_moderated":          tp.get("is_moderated", False),
        "description":           (m.get("description") or "")[:300],
    }


def _is_text_chat_model(meta: dict) -> bool:
    """토론에 쓸 수 있는 텍스트 생성 모델인지 판별."""
    mid = meta["id"].lower()
    # 제외 ID 완전 일치
    if meta["id"] in EXCLUDE_IDS:
        return False
    # 제외 키워드 포함
    for kw in EXCLUDE_KEYWORDS:
        if kw in mid:
            return False
    # output_modalities에 text 없음
    if "text" not in [x.lower() for x in meta.get("output_modalities", ["text"])]:
        return False
    # max_completion_tokens 최소선 (0이면 알 수 없음으로 허용)
    mct = meta.get("max_completion_tokens", 0)
    if mct > 0 and mct < MIN_MAX_COMPLETION_TOKENS:
        return False
    # context_length 최소선
    if meta.get("context_length", 0) < 4096:
        return False
    return True


def _is_free(meta: dict) -> bool:
    pp = _price_to_float(meta["pricing_prompt"], default=1.0)
    pc = _price_to_float(meta["pricing_completion"], default=1.0)
    return (pp == 0.0 and pc == 0.0) or meta["id"].endswith(":free")


def _score_model_for_role(meta: dict, role: str, weights: dict[str, float]) -> float:
    """역할별 점수 계산 (높을수록 좋음)."""
    score = 0.0
    w = weights

    # 무료 보너스
    if _is_free(meta):
        score += w.get("free_bonus", 0)
    else:
        score += w.get("paid_boost", 0)

    # context_length (log 스케일, 최대 10점)
    cl = meta.get("context_length", 0)
    if cl > 0:
        score += w.get("context_length", 0) * min(math.log10(cl) / math.log10(1_048_576), 1.0)

    # max_completion_tokens (log 스케일, 최대 10점)
    mct = meta.get("max_completion_tokens", 0)
    if mct > 0:
        score += w.get("max_completion_tokens", 0) * min(math.log10(mct) / math.log10(131072), 1.0)

    # structured_outputs 지원
    if "structured_outputs" in meta.get("supported_parameters", []):
        score += w.get("structured_outputs", 0)

    # reasoning 지원
    if "reasoning" in meta.get("supported_parameters", []):
        score += w.get("reasoning", 0)

    # 가격 페널티 ($/M prompt token 기준)
    pp_per_m = _price_to_float(meta["pricing_prompt"], default=0.0) * 1_000_000
    if pp_per_m > 0:
        # $1/M = 감점 없음 기준, 비쌀수록 증가
        penalty = min(math.log1p(pp_per_m) / math.log1p(15.0), 1.0)
        score -= w.get("price_penalty", 0) * penalty

    # 역할 키워드 가점
    mid_lower = meta["id"].lower()
    for kw in ROLE_KEYWORD_BOOST.get(role, []):
        if kw.lower() in mid_lower:
            score += w.get("keyword_boost", 0)
            break

    return score


def assign_per_role(
    models: list[dict],
    weights_map: dict[str, dict[str, float]] | None = None,
    top_k: int = 3,
) -> tuple[dict[str, str], dict[str, str], dict[str, list[dict]]]:
    """
    역할별 최적 모델을 배정한다.
    반환: (default_per_role, backup_per_role, ranked_candidates)
    - default_per_role: 역할명 → 1순위 model id
    - backup_per_role: 역할명 → 2순위 model id
    - ranked_candidates: 역할명 → [{id, name, score}, ...] 상위 top_k
    """
    w_map = weights_map or DEFAULT_SCORING_WEIGHTS
    roles = list(w_map.keys())

    default_per_role: dict[str, str] = {}
    backup_per_role:  dict[str, str] = {}
    ranked_candidates: dict[str, list[dict]] = {}

    for role in roles:
        scored = []
        for m in models:
            s = _score_model_for_role(m, role, w_map[role])
            scored.append((s, m))
        scored.sort(key=lambda x: x[0], reverse=True)

        ranked_candidates[role] = [
            {"id": m["id"], "name": m["name"], "score": round(s, 2)}
            for s, m in scored[:top_k]
        ]
        if scored:
            default_per_role[role] = scored[0][1]["id"]
        if len(scored) > 1:
            backup_per_role[role] = scored[1][1]["id"]
        else:
            backup_per_role[role] = default_per_role.get(role, "")

    return default_per_role, backup_per_role, ranked_candidates


def _weights_for_profile(
    weights_map: dict[str, dict[str, float]],
    profile_name: str,
) -> dict[str, dict[str, float]]:
    """프로필별 가중치 보정치를 적용한다."""
    import copy

    adjusted = copy.deepcopy(weights_map)
    override = PROFILE_WEIGHT_OVERRIDES.get(profile_name, PROFILE_WEIGHT_OVERRIDES["economy"])
    for role, weights in adjusted.items():
        weights["free_bonus"] = round(weights.get("free_bonus", 0.0) * override.get("free_bonus_scale", 1.0), 2)
        weights["price_penalty"] = round(weights.get("price_penalty", 0.0) * override.get("price_penalty_scale", 1.0), 2)
        weights["reasoning"] = round(weights.get("reasoning", 0.0) * override.get("reasoning_scale", 1.0), 2)
        weights["structured_outputs"] = round(weights.get("structured_outputs", 0.0) * override.get("structured_outputs_scale", 1.0), 2)
        weights["context_length"] = round(weights.get("context_length", 0.0) * override.get("context_length_scale", 1.0), 2)
        weights["max_completion_tokens"] = round(weights.get("max_completion_tokens", 0.0) * override.get("max_completion_tokens_scale", 1.0), 2)
        weights["keyword_boost"] = round(weights.get("keyword_boost", 0.0) * override.get("keyword_boost_scale", 1.0), 2)
        weights["paid_boost"] = round(override.get("paid_boost", 0.0), 2)

        if profile_name == "quality":
            if role in ("judge", "fact"):
                weights["free_bonus"] = round(weights.get("free_bonus", 0.0) * 0.25, 2)
                weights["price_penalty"] = round(weights.get("price_penalty", 0.0) * 0.18, 2)
                weights["reasoning"] = round(weights.get("reasoning", 0.0) * 1.35, 2)
                weights["structured_outputs"] = round(weights.get("structured_outputs", 0.0) * 1.25, 2)
                weights["keyword_boost"] = round(weights.get("keyword_boost", 0.0) * 1.2, 2)
                weights["paid_boost"] = round(weights.get("paid_boost", 0.0) + 4.0, 2)
            elif role in ("pro", "con"):
                weights["paid_boost"] = round(weights.get("paid_boost", 0.0) + 2.0, 2)
    return adjusted


def _fits_profile(meta: dict, profile_conf: dict) -> bool:
    """프로필 제약(가격, 컨텍스트, 유무료)에 맞는 모델만 통과시킨다."""
    if meta.get("context_length", 0) < profile_conf.get("min_context_length", 0):
        return False
    if _is_free(meta):
        return True
    if not profile_conf.get("allow_paid", False):
        return False
    pp_per_m = _price_to_float(meta.get("pricing_prompt"), default=999.0) * 1_000_000
    pc_per_m = _price_to_float(meta.get("pricing_completion"), default=999.0) * 1_000_000
    if pp_per_m > profile_conf.get("max_prompt_price_per_m", 999.0):
        return False
    if pc_per_m > profile_conf.get("max_completion_price_per_m", 999.0):
        return False
    return True


def _models_for_profile(models: list[dict], profile_name: str) -> list[dict]:
    """프로필에 맞는 후보만 필터링한다."""
    profile_conf = PROFILE_PRESETS.get(profile_name, PROFILE_PRESETS["economy"])
    return [m for m in models if _fits_profile(m, profile_conf)]


def _tune_weights(
    current: dict[str, dict[str, float]],
    log_entries: list[dict],
    tune_factor: float = 0.05,
) -> tuple[dict[str, dict[str, float]], list[str]]:
    """
    recommendation_log 항목을 분석해 scoring_weights를 미세 조정한다.
    tune_factor: 최대 조정 비율 (5%). 각 가중치는 기본값의 ±30% 범위를 벗어나지 않는다.
    반환: (조정된 weights, 변경 설명 목록)
    """
    import copy
    updated = copy.deepcopy(current)
    changes: list[str] = []

    # 역할별로 length(토큰 부족) 종료 비율이 높으면 max_completion_tokens 가중치 올리기
    role_length_ratio: dict[str, float] = {}
    role_count: dict[str, int] = {}

    for entry in log_entries:
        fr = (entry.get("finish_reason") or "").lower()
        selected = entry.get("per_role_selected") or {}
        for role, _mid in selected.items():
            role_count[role] = role_count.get(role, 0) + 1
            if "length" in fr:
                role_length_ratio[role] = role_length_ratio.get(role, 0) + 1

    for role, total in role_count.items():
        if total < 5:   # 표본 너무 적음
            continue
        length_rate = role_length_ratio.get(role, 0) / total
        if length_rate > 0.4 and role in updated:   # 40% 이상이 length 종료
            old_w = updated[role].get("max_completion_tokens", 0)
            new_w = min(old_w * (1 + tune_factor), DEFAULT_SCORING_WEIGHTS[role].get("max_completion_tokens", old_w) * 1.3)
            updated[role]["max_completion_tokens"] = round(new_w, 2)
            changes.append(f"{role}: max_completion_tokens {old_w:.2f} → {new_w:.2f} (length rate {length_rate:.0%})")

    return updated, changes


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))


# ── 메인 ─────────────────────────────────────────────────────────────────

def main() -> None:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] 모델 캐시 업데이트 시작")

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent / ".env")
    except ImportError:
        pass
    api_key = os.environ.get("OPENROUTER_API_KEY")

    # ── 1. API 수집 ──────────────────────────────────────────────────────
    raw_data = fetch_all_models(api_key=api_key)
    print(f"[INFO] API에서 {len(raw_data)}개 모델 수신")

    # ── 2. 메타데이터 추출 + 정제 ─────────────────────────────────────────
    all_meta = [_extract_meta(m) for m in raw_data] if raw_data else []
    cleaned  = [m for m in all_meta if _is_text_chat_model(m)]
    print(f"[INFO] 정제 후 텍스트 모델: {len(cleaned)}개")

    if not cleaned:
        print("[WARN] 정제된 모델 없음. 폴백 사용.")
        cleaned = FALLBACK_FREE

    free_models_refined = [m for m in cleaned if _is_free(m)]
    paid_candidates     = [m for m in cleaned if not _is_free(m)]
    print(f"[INFO] 무료: {len(free_models_refined)}개  유료 후보: {len(paid_candidates)}개")

    # ── 3. 기존 캐시 로드 + 가중치 로드 ──────────────────────────────────
    cache = load_cache()
    scoring_weights = cache.get("scoring_weights") or DEFAULT_SCORING_WEIGHTS

    # ── 3b. recommendation_log를 DB에서 읽어 가중치 튜닝 입력 보강 ────────
    db_log_entries: list[dict] = []
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from db import fetch_recommendation_log, init_db
        init_db()
        db_log_entries = fetch_recommendation_log(limit=200)
        print(f"[INFO] DB 추천 로그 {len(db_log_entries)}건 로드")
    except Exception as e:
        print(f"[WARN] DB 추천 로그 로드 실패: {e}")

    # ── 4. 역할별 기본 배정 (무료 모델만) ───────────────────────────────
    if free_models_refined:
        default_free, backup_free, ranked_free = assign_per_role(
            free_models_refined, scoring_weights, top_k=3
        )
    else:
        # 폴백: 모든 역할에 폴백 1순위 할당
        fb_id = FALLBACK_FREE[0]["id"]
        roles = list(DEFAULT_SCORING_WEIGHTS.keys())
        default_free = {r: fb_id for r in roles}
        backup_free  = {r: FALLBACK_FREE[min(1, len(FALLBACK_FREE)-1)]["id"] for r in roles}
        ranked_free  = {r: [{"id": fb_id, "name": FALLBACK_FREE[0]["name"], "score": 0.0}] for r in roles}

    print("[INFO] 역할별 기본 무료 배정:")
    for role, mid in default_free.items():
        print(f"  {role}: {mid}")

    # ── 5. 전체 후보(무료+유료) ranked_candidates 생성 (추천기용) ────────
    _, _, ranked_all = assign_per_role(cleaned, scoring_weights, top_k=3)

    # ── 5b. 프로필별 후보/기본 모델 생성 ───────────────────────────────
    defaults_by_profile: dict[str, dict[str, str]] = {}
    backups_by_profile: dict[str, dict[str, str]] = {}
    ranked_by_profile: dict[str, dict[str, list[dict]]] = {}
    for profile_name in PROFILE_PRESETS:
        filtered = _models_for_profile(cleaned, profile_name)
        if not filtered:
            filtered = free_models_refined or cleaned
        profile_weights = _weights_for_profile(scoring_weights, profile_name)
        default_prof, backup_prof, ranked_prof = assign_per_role(filtered, profile_weights, top_k=5)
        defaults_by_profile[profile_name] = default_prof
        backups_by_profile[profile_name] = backup_prof
        ranked_by_profile[profile_name] = ranked_prof

    curated_dynamic_models: list[dict] = []
    seen_ids: set[str] = set()
    for model in paid_candidates:
        if model["id"] in seen_ids:
            continue
        seen_ids.add(model["id"])
        curated_dynamic_models.append({
            "id": model["id"],
            "name": model["name"],
            "context_length": model.get("context_length", 0),
            "pricing_prompt": model.get("pricing_prompt", "1"),
            "pricing_completion": model.get("pricing_completion", "1"),
        })
        if len(curated_dynamic_models) >= 20:
            break

    # ── 6. 가중치 자동 튜닝 ─────────────────────────────────────────────
    log_entries = list(db_log_entries) + list(cache.get("recommendation_log") or [])
    tuned_weights, weight_changes = _tune_weights(scoring_weights, log_entries)
    if weight_changes:
        print("[INFO] scoring_weights 자동 튜닝 적용:")
        for c in weight_changes:
            print(f"  {c}")
    else:
        print("[INFO] scoring_weights 조정 없음 (표본 부족 또는 안정)")

    # ── 7. 캐시 저장 ─────────────────────────────────────────────────────
    # 기존 호환성: free_models 키는 유지
    free_models_compat = [
        {"id": m["id"], "name": m["name"], "context_length": m["context_length"]}
        for m in free_models_refined[:8]
    ]

    cache.update({
        "updated_at":             now,
        "schema_version":         2,
        # 호환성 키 (구 get_free_models_as_backends 등 지원)
        "free_models":            free_models_compat,
        "auto_recommended":       default_free.get("pro", ""),
        # 신규 구조
        "cleaned_models":         cleaned,
        "free_models_refined":    free_models_refined,
        "paid_candidates":        paid_candidates[:30],  # 상위 30개만 저장
        "default_free_per_role":  default_free,
        "backup_free_per_role":   backup_free,
        "ranked_candidates_free": ranked_free,
        "ranked_candidates_all":  ranked_all,
        "default_per_role_by_profile": defaults_by_profile,
        "backup_per_role_by_profile": backups_by_profile,
        "ranked_candidates_by_profile": ranked_by_profile,
        "curated_openrouter_models": curated_dynamic_models,
        "scoring_weights":        tuned_weights,
        "profile_presets":        PROFILE_PRESETS,
        "recommendation_metadata": {
            "generated_at":      now,
            "schema_version":    2,
            "cost_cap_usd":      0.005,
            "free_count":        len(free_models_refined),
            "paid_count":        len(paid_candidates),
            "cleaned_total":     len(cleaned),
            "excluded_total":    len(all_meta) - len(cleaned),
            "curated_dynamic_count": len(curated_dynamic_models),
            "weight_changes":    weight_changes,
        },
    })

    save_cache(cache)
    print(f"[OK] 캐시 저장 완료 → {CACHE_FILE}")
    print(f"[OK] 역할별 기본 모델(judge): {default_free.get('judge','?')}")


if __name__ == "__main__":
    main()

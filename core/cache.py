"""
Hermes Cache Module
질문 fingerprint 기반 Exact-Match 캐시 (Redis)
API 비용 절감 + 응답 속도 향상
"""
from __future__ import annotations

import hashlib
import json
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

_redis_client = None


def _get_redis():
    """Redis 클라이언트 (lazy init, 실패해도 앱은 정상 동작)"""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis
        url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        _redis_client = redis.from_url(url, socket_connect_timeout=2, decode_responses=True)
        _redis_client.ping()
        logger.info("Redis 캐시 연결 성공: %s", url)
    except Exception as e:
        logger.warning("Redis 연결 실패 (캐시 비활성화): %s", e)
        _redis_client = None
    return _redis_client


def make_key(topic: str, personas: list[str], model: str, mode: str = "") -> str:
    """질문 fingerprint 생성 (정규화 후 SHA256)"""
    normalized = json.dumps(
        {"topic": topic.strip().lower(), "personas": sorted(personas), "model": model, "mode": mode},
        ensure_ascii=False, sort_keys=True
    )
    return "ga:cache:" + hashlib.sha256(normalized.encode()).hexdigest()


def get_cached(key: str) -> Any | None:
    """캐시 조회. 없거나 Redis 오류면 None 반환"""
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(key)
        if raw:
            logger.debug("캐시 히트: %s", key[:20])
            return json.loads(raw)
    except Exception as e:
        logger.warning("캐시 조회 오류: %s", e)
    return None


def set_cached(key: str, value: Any, ttl: int = 3600 * 6) -> bool:
    """캐시 저장. TTL 기본 6시간. 실패해도 False 반환"""
    r = _get_redis()
    if r is None:
        return False
    try:
        r.setex(key, ttl, json.dumps(value, ensure_ascii=False))
        return True
    except Exception as e:
        logger.warning("캐시 저장 오류: %s", e)
        return False


def get_cache_stats() -> dict:
    """캐시 통계 (Obsidian 리포트용)"""
    r = _get_redis()
    if r is None:
        return {"status": "disconnected"}
    try:
        info = r.info("stats")
        return {
            "status": "connected",
            "hits": info.get("keyspace_hits", 0),
            "misses": info.get("keyspace_misses", 0),
            "hit_rate": round(
                info.get("keyspace_hits", 0) /
                max(info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0), 1) * 100, 1
            ),
            "total_keys": r.dbsize(),
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def invalidate_pattern(pattern: str = "ga:cache:*") -> int:
    """특정 패턴 캐시 전체 삭제 (데이터 갱신 시 사용)"""
    r = _get_redis()
    if r is None:
        return 0
    try:
        keys = r.keys(pattern)
        if keys:
            return r.delete(*keys)
    except Exception as e:
        logger.warning("캐시 삭제 오류: %s", e)
    return 0

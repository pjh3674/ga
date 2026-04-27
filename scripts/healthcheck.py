#!/usr/bin/env python3
"""
Hermes Health Check
Docker healthcheck에서 실행: 앱 응답 + DB 연결 + Redis 연결 확인
종료코드 0 = 정상, 1 = 비정상
"""
import sys
import os
import urllib.request

errors = []

# 1. API 서버 응답 확인 (컨테이너 내부 8600, 호스트 노출 8500)
try:
    with urllib.request.urlopen("http://localhost:8600/api/health", timeout=5) as r:
        if r.status != 200:
            errors.append(f"API HTTP {r.status}")
except Exception as e:
    errors.append(f"API 응답 없음: {e}")

# 2. DB 파일 접근 확인
import sqlite3
db_path = os.environ.get("GA_DB_PATH", "/app/ga.db")
try:
    conn = sqlite3.connect(db_path, timeout=3)
    conn.execute("SELECT 1")
    conn.close()
except Exception as e:
    errors.append(f"DB 오류: {e}")

# 3. Redis 연결 확인 (설치된 경우만)
redis_url = os.environ.get("REDIS_URL", "redis://redis:6379")
try:
    import redis as _redis
    r = _redis.from_url(redis_url, socket_connect_timeout=2)
    r.ping()
except ImportError:
    pass  # redis 라이브러리 없으면 건너뜀
except Exception as e:
    errors.append(f"Redis 오류: {e}")

if errors:
    print("UNHEALTHY:", " | ".join(errors))
    sys.exit(1)

print("HEALTHY")
sys.exit(0)

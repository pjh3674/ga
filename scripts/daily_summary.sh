#!/usr/bin/env bash
# Phase 4: GA 일일 요약 자동 생성 (cron 06:00 KST 권장)
#
# crontab 등록 예:
#   0 6 * * * /home/pjh/apps/ga/scripts/daily_summary.sh >> /home/pjh/apps/ga/results/daily_summary.log 2>&1
#
# 또는 ga-api 컨테이너 안에서 직접:
#   docker exec ga-api python3 -m integrations.daily_summary
set -euo pipefail
cd "$(dirname "$0")/.."

# 컨테이너가 살아있으면 컨테이너 내부에서 실행 (DB 일관성 보장)
if docker ps --format '{{.Names}}' | grep -q '^ga-api$'; then
    docker exec ga-api python3 -m integrations.daily_summary "$@"
else
    # 폴백: 호스트 venv 사용
    if [[ -d venv ]]; then
        source venv/bin/activate
    fi
    python3 -m integrations.daily_summary "$@"
fi

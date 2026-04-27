#!/usr/bin/env bash
# Phase 5: 모델 캐시 자동 갱신 (cron 09:05 KST 권장)
#
# crontab 등록 예:
#   5 9 * * * /home/pjh/apps/ga/scripts/update_model.sh >> /home/pjh/apps/ga/results/update_model.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."

if docker ps --format '{{.Names}}' | grep -q '^ga-api$'; then
    docker exec ga-api python3 update_model.py
else
    if [[ -d venv ]]; then
        source venv/bin/activate
    fi
    python3 update_model.py
fi

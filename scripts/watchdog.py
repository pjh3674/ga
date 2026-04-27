#!/usr/bin/env python3
"""
Hermes Watchdog: 핵심 장애 4종 Telegram 알림
cron으로 5분마다 실행:
  */5 * * * * /usr/bin/python3 /home/pjh/apps/ga/scripts/watchdog.py >> /home/pjh/logs/watchdog.log 2>&1

필요 환경변수 (.env에 추가):
  TELEGRAM_BOT_TOKEN=...
  TELEGRAM_CHAT_ID=...
"""
from __future__ import annotations

import os
import sys
import json
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# 상태 파일 (중복 알림 방지)
STATE_FILE = "/tmp/hermes_watchdog_state.json"

def send_telegram(msg: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        print("경고: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정")
        return False
    try:
        data = urllib.parse.urlencode({
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data=data, method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        print(f"Telegram 전송 오류: {e}")
        return False


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def check_container_health(name: str) -> tuple[bool, str]:
    """컨테이너 상태 확인 (running 필수, healthcheck 있으면 healthy)"""
    try:
        # Status는 항상 존재, Health는 healthcheck 정의된 컨테이너만 존재
        result = subprocess.run(
            ["docker", "inspect", "--format",
             "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
             name],
            capture_output=True, text=True, timeout=5
        )
        out = result.stdout.strip()
        if not out or "running" not in out:
            return False, f"컨테이너 중단됨: {out or 'not found'}"
        if "unhealthy" in out:
            return False, f"헬스체크 실패: {out}"
        return True, "OK"
    except Exception as e:
        return False, str(e)


def check_disk_space(threshold_pct: float = 90.0) -> tuple[bool, str]:
    """디스크 여유 공간 확인"""
    try:
        result = subprocess.run(
            ["df", "-h", "/"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 5:
                used_pct = float(parts[4].replace("%", ""))
                if used_pct >= threshold_pct:
                    return False, f"디스크 {used_pct:.0f}% 사용 중 (여유 {100-used_pct:.0f}%)"
                return True, f"디스크 {used_pct:.0f}%"
    except Exception as e:
        return True, str(e)
    return True, "OK"


def check_api_errors() -> tuple[bool, str]:
    """Docker 로그에서 최근 5분 429/5xx 에러 감지"""
    try:
        result = subprocess.run(
            ["docker", "logs", "--since", "5m", "ga-api"],
            capture_output=True, text=True, timeout=10
        )
        logs = result.stdout + result.stderr
        error_429 = logs.count("429")
        error_5xx = sum(logs.count(f" {c}") for c in ["500", "502", "503", "504"])
        total = error_429 + error_5xx
        if total >= 5:
            return False, f"최근 5분 API 오류 {total}건 (429: {error_429}, 5xx: {error_5xx})"
        return True, f"API 오류 {total}건"
    except Exception as e:
        return True, str(e)


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    state = load_state()
    alerts = []

    # 1. 앱 다운 확인 (신규 UI 스택: ga-api + ga-web)
    for cname in ("ga-api", "ga-web"):
        ok, msg = check_container_health(cname)
        key = f"container_alert_{cname}"
        if not ok:
            if state.get(key) != msg:
                alerts.append(f"🔴 <b>[앱 다운]</b> {cname} 컨테이너 이상\n{msg}\n→ <code>docker compose up -d {cname}</code> 로 복구")
                state[key] = msg
        else:
            state.pop(key, None)
    # legacy hermes-ga 키 제거 (Streamlit 폐기)
    state.pop("container_alert", None)

    # 2. Redis 다운 확인
    ok, msg = check_container_health("redis")
    if not ok:
        if state.get("redis_alert") != msg:
            alerts.append(f"🟡 <b>[Redis 중단]</b>\n{msg}\n→ 캐시 비활성화 상태로 계속 동작")
            state["redis_alert"] = msg
    else:
        state.pop("redis_alert", None)

    # 3. 디스크 여유 공간 (90%)
    ok, msg = check_disk_space(90.0)
    if not ok:
        if not state.get("disk_alert"):
            alerts.append(f"💾 <b>[디스크 부족]</b> {msg}\n→ 오래된 백업 및 로그 정리 필요")
            state["disk_alert"] = True
    else:
        state.pop("disk_alert", None)

    # 4. API 에러 급증
    ok, msg = check_api_errors()
    if not ok:
        if not state.get("api_alert"):
            alerts.append(f"⚠️ <b>[API 오류 급증]</b> {msg}\n→ 모델 할당량 확인 또는 fallback 모델로 전환 권장")
            state["api_alert"] = True
    else:
        state.pop("api_alert", None)

    # 알림 전송
    if alerts:
        header = f"🚨 <b>Hermes 경보</b> [{now}]\n"
        for alert in alerts:
            send_telegram(header + alert)
            print(f"[{now}] 알림 전송: {alert[:60]}")
    else:
        print(f"[{now}] 정상 — 모든 체크 통과")

    save_state(state)


if __name__ == "__main__":
    # .env 파일 로드 (cron 환경에서도 동작)
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
    main()

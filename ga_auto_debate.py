#!/usr/bin/env python3
"""
ga_auto_debate.py
NAS 폴더 감시 -> 자동 토론 트리거 -> Obsidian 저장 + Telegram 알림 + 파일 아카이빙
"""

import os
import sys
import time
import json
import logging
import requests
import threading
import shutil
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 프로젝트 경로 설정
GA_DIR = Path(__file__).parent
sys.path.insert(0, str(GA_DIR))
sys.path.insert(0, "/home/pjh")

from debate import run_debate
from integrations.obsidian_save import save_to_obsidian
from db import save_debate, log_save_result
try:
    from kordoc_helper import parse_to_markdown
except ImportError:
    def parse_to_markdown(path) -> str:  # type: ignore
        """kordoc_helper 미설치 시 텍스트 파일 단순 읽기로 대체."""
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"[변환 실패: {e}]"

# ── 설정 ──────────────────────────────────────────────────────────────────────
WATCH_DIR = Path("/mnt/nas/02예산자료/01_검토필요")
DONE_DIR  = Path("/mnt/nas/02예산자료/02_검토완료")
HOLD_DIR  = Path("/mnt/nas/02예산자료/03_보류")       # 승인 게이트: 보류 폴더
LOG_FILE  = GA_DIR / "ga_auto_debate.log"

# Telegram 설정
TG_CONF = Path("/home/pjh/.cokacdir/bot_settings.json")
TG_TOKEN = ""
TG_CHAT_ID = ""

# ── Phase 5: 승인 게이트 — 처리 중인 파일 상태 관리 ──────────────────────────
# key: 원본 파일명, value: {"topic", "messages", "verdict", "report", "debate_id", "path"}
_PENDING_APPROVALS: dict[str, dict] = {}

def load_tg_config():
    global TG_TOKEN, TG_CHAT_ID
    if TG_CONF.exists():
        try:
            bots = json.loads(TG_CONF.read_text())
            if bots:
                bot = next(iter(bots.values()))
                TG_TOKEN = bot.get("token", "")
                # 그룹 대화방 ID (박준하, 클로, 헤르메스 그룹방 ID)
                TG_CHAT_ID = bot.get("chat_id", bot.get("owner_user_id", ""))
                if not TG_CHAT_ID:
                    TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
        except Exception:
            pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

def send_telegram(text: str):
    if not TG_TOKEN or not TG_CHAT_ID:
        log.warning("Telegram 설정이 없어 메시지를 보내지 못했습니다.")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=10)
        r.raise_for_status()
    except Exception as e:
        log.error(f"Telegram 알림 실패: {e}")

def process_file(file_path: Path):
    log.info(f"자동 토론 시작: {file_path.name}")

    # 1. 파일 파싱
    content = parse_to_markdown(file_path)
    if "변환 실패" in content:
        log.warning(f"파일 변환 실패: {file_path.name}")
        send_telegram(f"⚠️ [GA 변환 실패]\n파일명: {file_path.name}\n수동 확인이 필요합니다.")
        return

    # 2. 중복 파일 감지 (같은 파일명이 이미 처리 대기 중인 경우)
    if file_path.name in _PENDING_APPROVALS:
        log.warning(f"이미 승인 대기 중인 파일: {file_path.name}")
        send_telegram(f"⚠️ [GA 중복 감지]\n'{file_path.name}'은(는) 이미 검토 대기 중입니다.")
        return

    # 3. 토론 주제 설정
    topic = file_path.stem
    if "검토" not in topic:
        topic = f"{topic}에 대한 사업 적정성 및 실행 계획 검토"

    # 4. 토론 시작 알림
    send_telegram(f"🔍 [GA 자동 검토 시작]\n파일명: {file_path.name}\n주제: {topic}")

    try:
        from config import DEFAULT_BACKEND_KEY
        from debate import generate_report_with_review
        _auto_backends = {a: DEFAULT_BACKEND_KEY for a in ["pro", "con", "judge", "fact", "audience"]}

        # 5. 토론 실행 (haesoo_official 페르소나 기본 적용)
        messages = run_debate(
            topic=topic,
            context=content,
            persona="haesoo_official",
            use_rag=True,
            rag_collection="budget",
            agent_backends=_auto_backends,
        )

        # 6. 판정 추출 (구조화 체크리스트형)
        import re
        verdict = ""
        for m in reversed(messages):
            if m.get("name") == "judge" and m.get("content"):
                raw = m["content"]
                # "## 정책 검토 의견서" 또는 "## 예산 검토 판정" 섹션 우선 추출
                match = re.search(r"(## (?:정책 검토 의견서|예산 검토 판정|검토 판정).*?)(?=\n##|\Z)", raw, re.DOTALL)
                verdict = match.group(1).strip()[:800] if match else raw[:800]
                break

        # 7. Phase 2+4: 보고서 초안 생성 + Self-Correction
        report_draft, review_result = generate_report_with_review(
            topic=topic,
            messages=messages,
            verdict=verdict,
            backend_key=DEFAULT_BACKEND_KEY,
            max_revisions=1,
        )

        # 8. DB 저장 (pending 상태)
        debate_id = save_debate(topic, messages, verdict)

        # 9. Phase 5: 승인 게이트 — Obsidian 저장 보류, 승인 대기
        _PENDING_APPROVALS[file_path.name] = {
            "topic":       topic,
            "messages":    messages,
            "verdict":     verdict,
            "report":      report_draft,
            "review":      review_result,
            "debate_id":   debate_id,
            "file_path":   str(file_path),
        }

        # 10. 텔레그램 승인 요청 알림
        verdict_summary = verdict[:300].replace("\n", " ") if verdict else "판정 없음"
        report_preview  = report_draft[:400].replace("\n", " ") if report_draft and not report_draft.startswith("[") else "(보고서 생성 실패)"

        approval_msg = (
            f"✅ [GA 검토 완료 — 승인 대기]\n"
            f"📄 파일: {file_path.name}\n"
            f"📋 주제: {topic}\n\n"
            f"⚖️ 판정 요약:\n{verdict_summary}\n\n"
            f"📝 보고서 미리보기:\n{report_preview}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"승인 방법:\n"
            f"  ✅ 승인: '/approve {file_path.name}' 전송\n"
            f"  🔄 재검토: '/retry {file_path.name}' 전송\n"
            f"  ❌ 보류: '/hold {file_path.name}' 전송\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"※ 승인 전까지 Obsidian 저장 및 파일 이동 없음"
        )
        send_telegram(approval_msg)
        log.info(f"승인 대기 등록: {file_path.name} (debate_id={debate_id})")

    except Exception as e:
        log.error(f"토론 실행 중 오류: {e}")
        send_telegram(f"❌ [GA 오류]\n'{topic}' 검토 중 오류 발생\n오류: {str(e)[:200]}")


def approve_file(file_name: str) -> bool:
    """
    Phase 5: 승인 처리 — Obsidian 저장 + 파일 아카이빙 수행.
    텔레그램 봇의 '/approve 파일명' 명령으로 호출.
    """
    pending = _PENDING_APPROVALS.get(file_name)
    if not pending:
        log.warning(f"승인 대상 없음: {file_name}")
        return False

    try:
        # Obsidian 저장 (보고서 초안 포함)
        _sr = save_to_obsidian(
            pending["topic"],
            pending["messages"],
            pending["verdict"],
            pending["debate_id"],
            report_draft=pending.get("report", ""),
        )
        try:
            log_save_result(_sr, pending["debate_id"], "debate")
        except Exception:
            pass
        if _sr.errors:
            log.warning(f"Obsidian 저장 경고: {' | '.join(_sr.errors)}")

        # 파일 아카이빙 (검토 완료 폴더)
        file_path = Path(pending["file_path"])
        if file_path.exists():
            archive_dir = DONE_DIR / datetime.now().strftime("%Y-%m")
            archive_dir.mkdir(parents=True, exist_ok=True)
            dest_path = archive_dir / file_path.name
            if dest_path.exists():
                dest_path = archive_dir / f"{file_path.stem}_{int(time.time())}{file_path.suffix}"
            shutil.move(str(file_path), str(dest_path))

        _PENDING_APPROVALS.pop(file_name, None)
        send_telegram(f"✅ [GA 승인 완료]\n'{pending['topic']}'\nObsidian 저장 및 아카이빙 완료.")
        log.info(f"승인 완료: {file_name}")
        return True

    except Exception as e:
        log.error(f"승인 처리 오류: {e}")
        send_telegram(f"❌ [GA 승인 오류]\n'{file_name}' 승인 처리 중 오류: {e}")
        return False


def hold_file(file_name: str) -> bool:
    """Phase 5: 보류 처리 — 파일을 03_보류 폴더로 이동."""
    pending = _PENDING_APPROVALS.get(file_name)
    if not pending:
        return False
    try:
        file_path = Path(pending["file_path"])
        if file_path.exists():
            HOLD_DIR.mkdir(parents=True, exist_ok=True)
            dest = HOLD_DIR / file_path.name
            if dest.exists():
                dest = HOLD_DIR / f"{file_path.stem}_{int(time.time())}{file_path.suffix}"
            shutil.move(str(file_path), str(dest))
        _PENDING_APPROVALS.pop(file_name, None)
        send_telegram(f"⏸️ [GA 보류]\n'{file_name}' → 03_보류 폴더로 이동했습니다.")
        return True
    except Exception as e:
        log.error(f"보류 처리 오류: {e}")
        return False


def retry_file(file_name: str) -> bool:
    """Phase 5: 재검토 처리 — 보류 후 다시 처리."""
    pending = _PENDING_APPROVALS.pop(file_name, None)
    if not pending:
        return False
    try:
        file_path = Path(pending["file_path"])
        if file_path.exists():
            send_telegram(f"🔄 [GA 재검토]\n'{file_name}' 재검토를 시작합니다.")
            process_file(file_path)
        return True
    except Exception as e:
        log.error(f"재검토 오류: {e}")
        return False

class AutoDebateHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            path = Path(event.src_path)
            if path.suffix.lower() in (".hwpx", ".hwp", ".pdf", ".xlsx", ".md"):
                log.info(f"새 파일 감지: {path.name}")
                time.sleep(3) # 안정적인 읽기를 위해 대기
                process_file(path)


# ── Phase 5: Telegram 명령 핸들러 (long-polling) ─────────────────────────────
_TG_OFFSET_FILE = GA_DIR / ".tg_update_offset"

def _load_tg_offset() -> int:
    try:
        return int(_TG_OFFSET_FILE.read_text().strip())
    except Exception:
        return 0

def _save_tg_offset(offset: int) -> None:
    try:
        _TG_OFFSET_FILE.write_text(str(offset))
    except Exception:
        pass

def _resolve_pending_key(arg: str) -> str | None:
    """
    /approve 인자가 정확한 파일명이 아니어도 부분일치/공백 무시로 매칭.
    여러 후보가 있으면 None.
    """
    if not arg:
        return None
    if arg in _PENDING_APPROVALS:
        return arg
    norm = arg.replace(" ", "").lower()
    matches = [k for k in _PENDING_APPROVALS if norm in k.replace(" ", "").lower()]
    if len(matches) == 1:
        return matches[0]
    return None

def _handle_tg_command(text: str) -> None:
    """텔레그램 메시지 텍스트 1건 처리."""
    text = (text or "").strip()
    if not text.startswith("/"):
        return
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]  # /approve@MyBot → /approve
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/list", "/pending"):
        if not _PENDING_APPROVALS:
            send_telegram("📭 승인 대기 중인 파일이 없습니다.")
            return
        lines = [f"📋 승인 대기 ({len(_PENDING_APPROVALS)}건):"]
        for i, (name, info) in enumerate(_PENDING_APPROVALS.items(), 1):
            lines.append(f"{i}. {name}\n   주제: {info.get('topic','')[:60]}")
        send_telegram("\n".join(lines))
        return

    if cmd in ("/approve", "/hold", "/retry"):
        key = _resolve_pending_key(arg)
        if not key:
            send_telegram(f"⚠️ 매칭 실패: '{arg}'\n/list 로 대기 목록을 확인하세요.")
            return
        if cmd == "/approve":
            approve_file(key)
        elif cmd == "/hold":
            hold_file(key)
        elif cmd == "/retry":
            retry_file(key)
        return

    if cmd == "/help":
        send_telegram(
            "🤖 GA Auto Debate 명령어\n"
            "/list — 승인 대기 목록\n"
            "/approve <파일명> — Obsidian 저장 + 아카이빙\n"
            "/hold <파일명> — 03_보류 폴더로 이동\n"
            "/retry <파일명> — 재검토 실행"
        )

def telegram_command_loop() -> None:
    """[DEPRECATED] OpenClaw와 같은 봇 토큰으로 polling 충돌 발생.
    대신 HTTP 명령 서버(command_http_server)를 사용하고 OpenClaw에서 forward.
    환경변수 GA_ENABLE_TG_POLLING=1 로 명시한 경우만 활성화.
    """
    if not TG_TOKEN:
        log.warning("TG_TOKEN 미설정 — 명령 핸들러 비활성")
        return
    offset = _load_tg_offset()
    log.info(f"Telegram 명령 핸들러 시작 (offset={offset})")
    while True:
        try:
            url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
            r = requests.get(url, params={"offset": offset, "timeout": 25}, timeout=30)
            r.raise_for_status()
            data = r.json()
            for upd in data.get("result", []):
                offset = max(offset, upd.get("update_id", 0) + 1)
                msg = upd.get("message") or upd.get("channel_post") or {}
                text = msg.get("text") or ""
                chat_id = str((msg.get("chat") or {}).get("id", ""))
                # 인가된 채팅방만 처리
                if TG_CHAT_ID and chat_id != str(TG_CHAT_ID):
                    continue
                if text.startswith("/"):
                    log.info(f"TG 명령 수신: {text[:80]}")
                    try:
                        _handle_tg_command(text)
                    except Exception as e:
                        log.error(f"명령 처리 오류: {e}")
                        send_telegram(f"❌ 명령 처리 오류: {e}")
            _save_tg_offset(offset)
        except requests.exceptions.RequestException as e:
            log.warning(f"Telegram polling 일시 오류: {e}")
            time.sleep(5)
        except Exception as e:
            log.error(f"Telegram polling 예외: {e}")
            time.sleep(10)


# ── HTTP 명령 서버 (OpenClaw → GA forward 전용) ────────────────────────────
GA_CMD_HOST = os.environ.get("GA_CMD_HOST", "127.0.0.1")
GA_CMD_PORT = int(os.environ.get("GA_CMD_PORT", "8610"))
GA_CMD_TOKEN = os.environ.get("GA_CMD_TOKEN", "")  # 비어있으면 인증 생략

def command_http_server() -> None:
    """
    경량 HTTP 명령 서버.
    POST /cmd  body: {"text": "/approve 파일명", "token": "<옵션>"}
    GET  /pending → {"items": [{name, topic}, ...]}

    OpenClaw 봇 게이트웨이에서 텔레그램 메시지를 수신해 이 엔드포인트로 forward한다.
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # 시끄러움 방지
            log.info("HTTP %s - %s", self.address_string(), fmt % args)

        def do_GET(self):
            if self.path == "/pending":
                items = [
                    {"name": k, "topic": (v.get("topic") or "")[:120]}
                    for k, v in _PENDING_APPROVALS.items()
                ]
                self._json(200, {"count": len(items), "items": items})
            elif self.path == "/health":
                self._json(200, {"ok": True, "pending": len(_PENDING_APPROVALS)})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/cmd":
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                payload = json.loads(raw.decode() or "{}")
            except Exception as e:
                self._json(400, {"error": f"bad json: {e}"})
                return
            if GA_CMD_TOKEN and payload.get("token") != GA_CMD_TOKEN:
                self._json(401, {"error": "unauthorized"})
                return
            text = (payload.get("text") or "").strip()
            if not text:
                self._json(400, {"error": "missing text"})
                return
            try:
                _handle_tg_command(text)
                self._json(200, {"ok": True})
            except Exception as e:
                log.error(f"명령 실행 오류: {e}")
                self._json(500, {"error": str(e)})

    try:
        server = ThreadingHTTPServer((GA_CMD_HOST, GA_CMD_PORT), Handler)
        log.info(f"GA 명령 HTTP 서버 시작: http://{GA_CMD_HOST}:{GA_CMD_PORT}/cmd (auth={'on' if GA_CMD_TOKEN else 'off'})")
        server.serve_forever()
    except Exception as e:
        log.error(f"HTTP 서버 실패: {e}")


def main():
    load_tg_config()
    log.info(f"GA Auto Debate Watcher 2.0 시작 (감시: {WATCH_DIR})")

    if not WATCH_DIR.exists():
        WATCH_DIR.mkdir(parents=True)

    # 명령 수신 채널: 기본은 HTTP (OpenClaw forward용).
    # GA_ENABLE_TG_POLLING=1 설정 시에만 직접 polling (단독 봇 환경 한정).
    if os.environ.get("GA_ENABLE_TG_POLLING") == "1" and TG_TOKEN:
        log.warning("GA_ENABLE_TG_POLLING=1 — Telegram polling 활성. 다른 봇과 충돌 주의.")
        threading.Thread(target=telegram_command_loop, daemon=True).start()
    else:
        threading.Thread(target=command_http_server, daemon=True).start()

    event_handler = AutoDebateHandler()
    observer = Observer()
    observer.schedule(event_handler, str(WATCH_DIR), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()

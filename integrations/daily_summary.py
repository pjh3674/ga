"""
Phase 4: Obsidian Daily Note 자동 요약.

- 지정 일자(기본: 어제)의 토론/정제소/비용을 집계해 마크다운으로 빌드.
- Obsidian Daily Note (`OBSIDIAN_DAILY_NOTE_DIR/YYYY-MM-DD.md`)에 prepend.
- 별도 보관용 노트도 `88.작업/GA토론결과/일일요약/YYYY-MM-DD.md`에 atomic write.

사용:
    python3 -m integrations.daily_summary               # 어제분
    python3 -m integrations.daily_summary 2026-04-24    # 특정일
"""
from __future__ import annotations

import os
import sys
import datetime
from pathlib import Path
from typing import Optional

# integrations.obsidian_save 의 경로/유틸을 그대로 활용
from integrations.obsidian_save import (
    NAS_VAULT_ROOT,
    VAULT_DIR,
    SaveResult,
    _atomic_write,
    _nas_writable,
    _unique_path,
    _REST_AVAILABLE,
    _obsidian_put,
)
from integrations.obsidian_api_helper import obsidian_get
import db


DAILY_NOTE_DIR = os.environ.get("OBSIDIAN_DAILY_NOTE_DIR", "02.일일노트")
SUMMARY_MARKER_BEGIN = "<!-- GA-DAILY-SUMMARY:BEGIN -->"
SUMMARY_MARKER_END = "<!-- GA-DAILY-SUMMARY:END -->"


# ── 마크다운 빌더 ────────────────────────────────────────────────────────────

def build_summary_markdown(date_iso: str) -> str:
    debates = db.fetch_debates_by_date(date_iso)
    runs = db.fetch_refinery_runs_by_date(date_iso)
    usage = db.fetch_token_usage_by_date(date_iso)

    lines: list[str] = []
    lines.append(SUMMARY_MARKER_BEGIN)
    lines.append(f"## 🤖 GA 토론 일일 요약 — {date_iso}")
    lines.append("")
    lines.append(
        f"- 토론 **{len(debates)}건** · 정제소 **{len(runs)}건** · "
        f"비용 **${usage['total'].get('cost') or 0:.4f}** "
        f"(calls {usage['total'].get('calls') or 0})"
    )
    lines.append("")

    # ── 토론 요약 ───────────────────────────────────────────────
    if debates:
        lines.append("### 📝 토론")
        for d in debates:
            mode = d.get("debate_mode") or "debate"
            verdict = (d.get("verdict") or "").strip().replace("\n", " ")
            verdict_short = (verdict[:80] + "…") if len(verdict) > 80 else verdict
            tid = d.get("thread_id")
            tag = f" 🧵#{tid}" if tid and tid != d["id"] else ""
            lines.append(
                f"- **#{d['id']}** [{mode}]{tag} — {d['topic']}"
                + (f"  \n  > {verdict_short}" if verdict_short else "")
            )
        lines.append("")

    # ── 정제소 요약 ─────────────────────────────────────────────
    if runs:
        lines.append("### 🧪 정제소")
        for r in runs:
            status_emoji = {
                "completed": "✅", "failed": "❌", "pending": "⏳",
                "running": "🔄",
            }.get(r.get("status", ""), "•")
            lines.append(
                f"- {status_emoji} **#{r['id']}** ({r.get('template_id', '-')}) — {r['topic']}"
            )
        lines.append("")

    # ── 비용 ─────────────────────────────────────────────────────
    if usage["by_model"]:
        lines.append("### 💰 비용 (모델별)")
        for m in usage["by_model"]:
            lines.append(
                f"- `{m['model']}` — ${m.get('cost') or 0:.4f} "
                f"(prompt {m.get('p_tok') or 0:,} / complete {m.get('c_tok') or 0:,} · {m.get('calls')}콜)"
            )
        lines.append("")

    if not (debates or runs or usage["by_model"]):
        lines.append("_이 날짜에는 기록이 없습니다._")
        lines.append("")

    lines.append(f"*생성: {datetime.datetime.now().isoformat(timespec='seconds')}*")
    lines.append(SUMMARY_MARKER_END)
    return "\n".join(lines) + "\n"


# ── Daily Note prepend / 보관 ───────────────────────────────────────────────

def _strip_existing_marker_block(text: str) -> str:
    """이전 GA 요약 블록을 제거(중복 방지)."""
    if SUMMARY_MARKER_BEGIN not in text or SUMMARY_MARKER_END not in text:
        return text
    start = text.find(SUMMARY_MARKER_BEGIN)
    end = text.find(SUMMARY_MARKER_END) + len(SUMMARY_MARKER_END)
    if end <= start:
        return text
    cleaned = text[:start] + text[end:]
    return cleaned.lstrip("\n")


def _prepend_to_daily_note(date_iso: str, summary_md: str) -> tuple[bool, str, str]:
    """Obsidian REST API로 daily note에 prepend. (rest_ok, daily_path, error)."""
    daily_path = f"{DAILY_NOTE_DIR}/{date_iso}.md"
    existing = ""
    try:
        r = obsidian_get(daily_path)
        if r is not None and r.status_code == 200:
            existing = r.text or ""
    except Exception:
        existing = ""

    cleaned = _strip_existing_marker_block(existing)
    new_body = summary_md + ("\n" + cleaned if cleaned.strip() else "")

    if not (_REST_AVAILABLE and _obsidian_put):
        return False, daily_path, "REST API 비활성"

    try:
        resp = _obsidian_put(daily_path, new_body)
        if resp is not None and resp.status_code in (200, 201, 204):
            return True, daily_path, ""
        return False, daily_path, f"REST status={getattr(resp, 'status_code', '?')}"
    except Exception as e:
        return False, daily_path, f"REST 예외: {e}"


def _save_archive_copy(date_iso: str, summary_md: str) -> tuple[bool, str, str]:
    """별도 보관용 노트 (NAS 직접). (nas_ok, nas_path, error)."""
    if not _nas_writable():
        return False, "", "NAS 미마운트"
    vault_path = f"{VAULT_DIR}/일일요약/{date_iso}.md"
    target = _unique_path(NAS_VAULT_ROOT / vault_path)
    body = (
        f"---\ntype: ga-daily-summary\ndate: {date_iso}\n---\n\n"
        f"# GA 토론 일일 요약 — {date_iso}\n\n"
        + summary_md
    )
    try:
        _atomic_write(target, body)
        return True, str(target), ""
    except Exception as e:
        return False, str(target), f"NAS 저장 실패: {e}"


# ── 공개 API ────────────────────────────────────────────────────────────────

def generate_daily_summary(date_iso: Optional[str] = None) -> dict:
    """
    하루치 요약을 생성/저장. date_iso 생략 시 어제(KST) 기준.
    반환: {date, summary_markdown, daily_note: {ok,path,error}, archive: {ok,path,error}}
    """
    if not date_iso:
        date_iso = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

    summary_md = build_summary_markdown(date_iso)
    rest_ok, daily_path, rest_err = _prepend_to_daily_note(date_iso, summary_md)
    nas_ok, nas_path, nas_err = _save_archive_copy(date_iso, summary_md)

    return {
        "date": date_iso,
        "summary_markdown": summary_md,
        "daily_note": {"ok": rest_ok, "path": daily_path, "error": rest_err},
        "archive": {"ok": nas_ok, "path": nas_path, "error": nas_err},
    }


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    res = generate_daily_summary(arg)
    print(f"[date]    {res['date']}")
    print(f"[daily]   ok={res['daily_note']['ok']} path={res['daily_note']['path']}"
          + (f" err={res['daily_note']['error']}" if res['daily_note']['error'] else ""))
    print(f"[archive] ok={res['archive']['ok']} path={res['archive']['path']}"
          + (f" err={res['archive']['error']}" if res['archive']['error'] else ""))
    print("\n--- markdown ---")
    print(res["summary_markdown"])

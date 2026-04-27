from __future__ import annotations

import sqlite3
import datetime
import json
from pathlib import Path

try:
    import streamlit as st
    _HAS_ST = True
except ImportError:
    _HAS_ST = False

from config import DB_PATH


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    return c


_db_initialized = False


def init_db() -> None:
    """DB 초기화 (중복 호출 안전). Streamlit 환경에선 자동 캐시 활용."""
    global _db_initialized
    if _db_initialized:
        return
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS debates (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                topic     TEXT    NOT NULL,
                created   TEXT    NOT NULL,
                summary   TEXT,
                verdict   TEXT,
                messages  TEXT    NOT NULL DEFAULT '[]',
                thread_id INTEGER DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS token_usage (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                debate_id INTEGER REFERENCES debates(id),
                model     TEXT    NOT NULL,
                prompt_tokens   INTEGER DEFAULT 0,
                complete_tokens INTEGER DEFAULT 0,
                cost_usd        REAL    DEFAULT 0.0,
                recorded  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recommendation_log (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                debate_id        INTEGER REFERENCES debates(id),
                recorded         TEXT    NOT NULL,
                quality_profile  TEXT    DEFAULT 'economy',
                per_role_selected TEXT   NOT NULL DEFAULT '{}',
                finish_reason    TEXT    DEFAULT '',
                total_messages   INTEGER DEFAULT 0,
                consensus_reached INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS debate_feedback (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                debate_id INTEGER REFERENCES debates(id),
                recorded  TEXT    NOT NULL,
                rating    INTEGER NOT NULL,
                comment   TEXT    DEFAULT ''
            );

            -- Phase 0: 저장 결과 추적 (silent-fail 제거)
            CREATE TABLE IF NOT EXISTS save_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ref_id      INTEGER DEFAULT 0,  -- debate_id 또는 refinery run_id
                ref_type    TEXT    DEFAULT 'debate',  -- 'debate' | 'refinery'
                recorded    TEXT    NOT NULL,
                vault_path  TEXT    DEFAULT '',
                nas_ok      INTEGER DEFAULT 0,
                rest_ok     INTEGER DEFAULT 0,
                pending_ok  INTEGER DEFAULT 0,
                errors_json TEXT    DEFAULT '[]'
            );

            -- Phase 1: 정제소 실행 기록
            CREATE TABLE IF NOT EXISTS refinery_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created     TEXT    NOT NULL,
                source_ai   TEXT    DEFAULT '',
                topic       TEXT    NOT NULL,
                template_id TEXT    DEFAULT 'jangan_base',
                options_json TEXT   DEFAULT '{}',
                status      TEXT    DEFAULT 'pending'  -- pending|completed|failed
            );

            -- Phase 3: 정제소에서 사용된 RAG 근거 추적
            CREATE TABLE IF NOT EXISTS refinery_sources (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      INTEGER REFERENCES refinery_runs(id),
                source_type TEXT    DEFAULT '',  -- 'wisdom' | 'alignment' | 'budget'
                ref_id      TEXT    DEFAULT '',
                snippet     TEXT    DEFAULT ''
            );

            -- Phase 4: 검수 결과
            CREATE TABLE IF NOT EXISTS review_results (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ref_id      INTEGER DEFAULT 0,
                ref_type    TEXT    DEFAULT 'debate',
                review_type TEXT    DEFAULT '',  -- 'legal' | 'budget' | 'style' | 'full'
                passed      INTEGER DEFAULT 0,
                notes       TEXT    DEFAULT '',
                recorded    TEXT    NOT NULL
            );
        """)
        # 기존 DB 마이그레이션
        cols = [row[1] for row in c.execute("PRAGMA table_info(debates)").fetchall()]
        if "thread_id" not in cols:
            c.execute("ALTER TABLE debates ADD COLUMN thread_id INTEGER DEFAULT NULL")
        if "debate_mode" not in cols:
            c.execute("ALTER TABLE debates ADD COLUMN debate_mode TEXT DEFAULT 'debate'")
        # recommendation_log 마이그레이션 (스키마 추가 시)
        rec_cols = [row[1] for row in c.execute("PRAGMA table_info(recommendation_log)").fetchall()]
        for col_def in [
            ("quality_profile",   "TEXT    DEFAULT 'economy'"),
            ("per_role_selected",  "TEXT    DEFAULT '{}'"),
            ("finish_reason",      "TEXT    DEFAULT ''"),
            ("total_messages",     "INTEGER DEFAULT 0"),
            ("consensus_reached",  "INTEGER DEFAULT 0"),
        ]:
            if col_def[0] not in rec_cols:
                c.execute(f"ALTER TABLE recommendation_log ADD COLUMN {col_def[0]} {col_def[1]}")
    _db_initialized = True


def save_debate(topic: str, messages: list[dict], verdict: str = "", thread_id: int | None = None, debate_mode: str = "debate") -> int:
    summary = _extract_summary(messages)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO debates (topic, created, summary, verdict, messages, thread_id, debate_mode) VALUES (?,?,?,?,?,?,?)",
            (topic, now, summary, verdict, json.dumps(messages, ensure_ascii=False), thread_id, debate_mode),
        )
        new_id = cur.lastrowid
        if thread_id is None:
            c.execute("UPDATE debates SET thread_id=? WHERE id=?", (new_id, new_id))
        return new_id


def fetch_all_debates() -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute(
            "SELECT id, topic, created, summary, verdict, debate_mode, thread_id FROM debates ORDER BY id DESC"
        ).fetchall()


def fetch_debate_stats() -> dict:
    """모드별·일별 토론 통계 반환."""
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM debates").fetchone()[0]
        by_mode = c.execute(
            "SELECT COALESCE(debate_mode,'debate') as mode, COUNT(*) as cnt "
            "FROM debates GROUP BY mode ORDER BY cnt DESC"
        ).fetchall()
        daily = c.execute(
            "SELECT substr(created,1,10) as day, COUNT(*) as cnt "
            "FROM debates WHERE created >= date('now','-30 days') "
            "GROUP BY day ORDER BY day"
        ).fetchall()
        avg_msg = c.execute(
            "SELECT AVG(json_array_length(messages)) FROM debates"
        ).fetchone()[0]
    return {
        "total": total,
        "by_mode": [dict(r) for r in by_mode],
        "daily": [dict(r) for r in daily],
        "avg_messages": round(avg_msg or 0, 1),
    }


def fetch_debate_by_id(debate_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM debates WHERE id=?", (debate_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["messages"] = json.loads(d["messages"])
        return d


def fetch_thread_debates(thread_id: int) -> list[dict]:
    """같은 thread_id를 공유하는 모든 토론을 오래된 순으로 반환."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, topic, created, summary, verdict, thread_id FROM debates "
            "WHERE thread_id=? ORDER BY id ASC",
            (thread_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_thread_full(thread_id: int) -> list[dict]:
    """스레드 내 모든 토론의 전체 메시지 포함 버전."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM debates WHERE thread_id=? ORDER BY id ASC",
            (thread_id,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["messages"] = json.loads(d["messages"])
        result.append(d)
    return result


def save_recommendation_log(
    debate_id: int,
    quality_profile: str,
    per_role_selected: dict[str, str],
    finish_reason: str = "",
    total_messages: int = 0,
    consensus_reached: bool = False,
) -> None:
    """토론별 모델 배정 로그를 저장한다. update_model._tune_weights() 입력으로 사용."""
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        c.execute(
            "INSERT INTO recommendation_log "
            "(debate_id, recorded, quality_profile, per_role_selected, finish_reason, total_messages, consensus_reached) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                debate_id,
                now,
                quality_profile,
                json.dumps(per_role_selected, ensure_ascii=False),
                finish_reason,
                total_messages,
                int(consensus_reached),
            ),
        )


def save_debate_feedback(debate_id: int, rating: int, comment: str = "") -> None:
    """
    토론 품질 피드백 저장.
    rating: 1 (좋음) 또는 -1 (나쁨)
    """
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        c.execute(
            "INSERT INTO debate_feedback (debate_id, recorded, rating, comment) VALUES (?,?,?,?)",
            (debate_id, now, rating, comment),
        )


def fetch_recommendation_log(limit: int = 200) -> list[dict]:
    """최근 recommendation_log를 dict 목록으로 반환 (update_model._tune_weights() 입력용)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM recommendation_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["per_role_selected"] = json.loads(d.get("per_role_selected", "{}"))
        except Exception:
            d["per_role_selected"] = {}
        result.append(d)
    return result


def fetch_feedback_stats() -> dict:
    """피드백 집계 반환: {total, positive, negative, ratio}"""
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN rating > 0 THEN 1 ELSE 0 END) as positive, "
            "SUM(CASE WHEN rating < 0 THEN 1 ELSE 0 END) as negative "
            "FROM debate_feedback"
        ).fetchone()
    if not row or not row["total"]:
        return {"total": 0, "positive": 0, "negative": 0, "ratio": 0.0}
    total = row["total"] or 0
    pos   = row["positive"] or 0
    neg   = row["negative"] or 0
    return {
        "total":    total,
        "positive": pos,
        "negative": neg,
        "ratio":    round(pos / total, 2) if total else 0.0,
    }


def log_token_usage(
    debate_id: int, model: str, prompt_tokens: int, complete_tokens: int, cost_usd: float
) -> None:
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        c.execute(
            "INSERT INTO token_usage (debate_id, model, prompt_tokens, complete_tokens, cost_usd, recorded) "
            "VALUES (?,?,?,?,?,?)",
            (debate_id, model, prompt_tokens, complete_tokens, cost_usd, now),
        )


def fetch_token_stats() -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute("""
            SELECT model,
                   SUM(prompt_tokens)   AS total_prompt,
                   SUM(complete_tokens) AS total_complete,
                   SUM(cost_usd)        AS total_cost,
                   COUNT(*)             AS calls
            FROM token_usage
            GROUP BY model
            ORDER BY total_cost DESC
        """).fetchall()


def fetch_ops_metrics(days: int = 7) -> dict:
    """Phase 3 운영 관제용 통합 메트릭 — N일 추세, 정제소 통계, 스레드 통계.

    days: 일별 추세 윈도우 (기본 7일).
    """
    with _conn() as c:
        # ── 일별 토론 + 정제소 + 비용 (N일) ─────────────────────────
        debates_daily = c.execute(
            "SELECT substr(created,1,10) AS day, COUNT(*) AS cnt "
            "FROM debates WHERE created >= date('now', ?) "
            "GROUP BY day ORDER BY day",
            (f"-{days} days",),
        ).fetchall()
        refinery_daily = c.execute(
            "SELECT substr(created,1,10) AS day, COUNT(*) AS cnt "
            "FROM refinery_runs WHERE created >= date('now', ?) "
            "GROUP BY day ORDER BY day",
            (f"-{days} days",),
        ).fetchall()
        cost_daily = c.execute(
            "SELECT substr(recorded,1,10) AS day, "
            "       ROUND(SUM(cost_usd), 6) AS cost, "
            "       SUM(prompt_tokens) AS p_tok, "
            "       SUM(complete_tokens) AS c_tok "
            "FROM token_usage WHERE recorded >= date('now', ?) "
            "GROUP BY day ORDER BY day",
            (f"-{days} days",),
        ).fetchall()

        # ── 정제소 상태별 카운트 + 최근 7일 합계 ──────────────────
        refinery_by_status = c.execute(
            "SELECT status, COUNT(*) AS cnt FROM refinery_runs GROUP BY status"
        ).fetchall()
        refinery_total = c.execute("SELECT COUNT(*) FROM refinery_runs").fetchone()[0]

        # ── 스레드 메트릭 (resume 사용량) ────────────────────────────
        # 같은 thread_id를 공유하는 토론이 2개 이상인 클러스터 = resume 발생
        thread_groups = c.execute(
            "SELECT thread_id, COUNT(*) AS cnt FROM debates "
            "WHERE thread_id IS NOT NULL GROUP BY thread_id"
        ).fetchall()
        thread_total = len(thread_groups)
        threads_with_resume = sum(1 for r in thread_groups if r["cnt"] > 1)
        max_rounds_in_thread = max((r["cnt"] for r in thread_groups), default=0)

        # ── 비용 상위 모델 (전체 누적) ───────────────────────────────
        top_cost_models = c.execute(
            "SELECT model, ROUND(SUM(cost_usd), 6) AS cost, COUNT(*) AS calls "
            "FROM token_usage GROUP BY model ORDER BY cost DESC LIMIT 5"
        ).fetchall()

    return {
        "window_days": days,
        "debates_daily": [dict(r) for r in debates_daily],
        "refinery_daily": [dict(r) for r in refinery_daily],
        "cost_daily": [dict(r) for r in cost_daily],
        "refinery_by_status": [dict(r) for r in refinery_by_status],
        "refinery_total": refinery_total,
        "thread_total": thread_total,
        "threads_with_resume": threads_with_resume,
        "max_rounds_in_thread": max_rounds_in_thread,
        "top_cost_models": [dict(r) for r in top_cost_models],
    }


def build_thread_context(thread_debates: list[dict], max_rounds: int = 3) -> str:
    """
    스레드의 과거 토론들을 구조화된 컨텍스트 문자열로 변환.
    - 각 라운드의 판정, 찬반 핵심 주장, 팩트체크 지적, 미해결 논점 추출
    - 최대 max_rounds 개의 최근 토론을 사용
    """
    if not thread_debates:
        return ""

    recent = thread_debates[-max_rounds:]
    parts = [
        f"[토론 스레드 컨텍스트 — 이전 {len(recent)}회 토론의 흐름]\n"
        f"※ 아래 내용을 숙지하고, 이미 다뤄진 논점은 반복하지 말고 새로운 깊이로 논의를 확장하라.\n"
    ]

    for i, debate in enumerate(recent, 1):
        messages = debate.get("messages", [])
        verdict = debate.get("verdict", "")
        created = debate.get("created", "")[:10]
        round_label = f"◆ 라운드 {i} ({created})"

        # 찬반 핵심 주장 수집
        pro_args: list[str] = []
        con_args: list[str] = []
        fact_issues: list[str] = []
        audience_qs: list[str] = []
        unresolved: list[str] = []

        for m in messages:
            name = m.get("name", "")
            content = m.get("content", "").strip()
            if not content or len(content) < 10:
                continue
            # 노이즈 필터 (간단 버전)
            if content.startswith("[참고 자료") or content.startswith("[토론 주제]") or len(content) > 800:
                continue

            first_sentence = content.split("。")[0].split(". ")[0].split("\n")[0].strip()[:100]

            if name == "pro" and len(pro_args) < 3:
                pro_args.append(first_sentence)
            elif name == "con" and len(con_args) < 3:
                con_args.append(first_sentence)
            elif name == "fact" and "이상無" not in content and len(fact_issues) < 2:
                fact_issues.append(content.strip()[:120])
            elif name == "audience" and len(audience_qs) < 2:
                audience_qs.append(content.strip()[:100])

        # judge의 [계속] 판정에서 미해결 논점 추출
        for m in messages:
            if m.get("name") == "judge" and "[계속]" in m.get("content", ""):
                c = m["content"]
                idx = c.find("판정:")
                snippet = c[idx:idx + 200].strip() if idx >= 0 else c[:200].strip()
                unresolved.append(snippet)

        section = [round_label]
        if pro_args:
            section.append("  [찬성 핵심 주장]")
            section.extend(f"  · {a}" for a in pro_args)
        if con_args:
            section.append("  [반대 핵심 주장]")
            section.extend(f"  · {a}" for a in con_args)
        if fact_issues:
            section.append("  [팩트체크 지적사항]")
            section.extend(f"  ! {f}" for f in fact_issues)
        if audience_qs:
            section.append("  [청중 미해결 질문]")
            section.extend(f"  ? {q}" for q in audience_qs)
        if verdict:
            section.append(f"  [판정 요약] {verdict[:150]}")
        if unresolved:
            section.append("  [미해결 — 다음 라운드 심화 필요]")
            section.extend(f"  → {u[:120]}" for u in unresolved)

        parts.append("\n".join(section))

    # 다음 토론 지침
    parts.append(
        "\n[다음 라운드 지침]\n"
        "· 위 라운드에서 다뤄진 논점은 요약하지 말고 새 근거로 심화하라.\n"
        "· '미해결' 항목은 이번 토론의 핵심 쟁점으로 다뤄라.\n"
        "· 팩트체크 지적사항에 대해 양측 모두 응답하라."
    )

    return "\n\n".join(parts)


def fetch_related_debates(topic: str, limit: int = 3) -> list[dict]:
    """주제 키워드가 겹치는 관련 과거 토론을 반환 (유사도 점수 순)."""
    keywords = [w.strip() for w in topic.replace(",", " ").split() if len(w.strip()) > 1][:6]
    if not keywords:
        return []
    with _conn() as c:
        rows = c.execute(
            "SELECT id, topic, summary, verdict, created FROM debates ORDER BY id DESC LIMIT 100"
        ).fetchall()
    scored: list[tuple[int, dict]] = []
    for row in rows:
        row_topic_lower = row["topic"].lower()
        score = sum(1 for kw in keywords if kw.lower() in row_topic_lower)
        if score > 0:
            scored.append((score, dict(row)))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:limit]]


def cleanup_old_results(days: int = 30) -> None:
    """results/ 폴더 30일 초과 파일 자동 삭제."""
    from config import RESULTS_DIR
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    for f in RESULTS_DIR.glob("*.json"):
        if datetime.datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
            f.unlink()


def fetch_all_debates_with_mode() -> list[dict]:
    """모든 토론 + debate_mode 포함해서 반환."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, topic, created, summary, verdict, debate_mode FROM debates ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def _extract_summary(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("name") == "judge" and m.get("content"):
            content = m["content"]
            return content[:120] if len(content) > 120 else content
    return ""


# ── Phase 0: 저장 결과 로그 ─────────────────────────────────────────────────

def log_save_result(result, ref_id: int = 0, ref_type: str = "debate") -> None:
    """
    SaveResult를 DB에 기록 (save_log 테이블).
    호출 시점: save_to_obsidian / save_refinery_output 직후.
    """
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        c.execute(
            "INSERT INTO save_log (ref_id, ref_type, recorded, vault_path, "
            "nas_ok, rest_ok, pending_ok, errors_json) VALUES (?,?,?,?,?,?,?,?)",
            (
                ref_id, ref_type, now,
                result.vault_path,
                int(result.nas_ok), int(result.rest_ok), int(result.pending_ok),
                json.dumps(result.errors, ensure_ascii=False),
            ),
        )


def fetch_pending_saves() -> list[dict]:
    """NAS/REST 모두 실패하고 폴백 대기 중인 저장 건 조회."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM save_log WHERE pending_ok=1 AND nas_ok=0 ORDER BY id DESC LIMIT 50"
        ).fetchall()
    return [dict(r) for r in rows]


# ── Phase 1: 정제소 실행 기록 ────────────────────────────────────────────────

def create_refinery_run(topic: str, source_ai: str = "", template_id: str = "jangan_base", options: dict | None = None) -> int:
    """새 정제소 실행 기록 생성. run_id 반환."""
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO refinery_runs (created, source_ai, topic, template_id, options_json, status) "
            "VALUES (?,?,?,?,?,?)",
            (now, source_ai, topic, template_id,
             json.dumps(options or {}, ensure_ascii=False), "pending"),
        )
        return cur.lastrowid


def update_refinery_run_status(run_id: int, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE refinery_runs SET status=? WHERE id=?", (status, run_id))


def log_refinery_source(run_id: int, source_type: str, ref_id: str, snippet: str) -> None:
    """정제소에서 사용된 RAG 근거 개별 기록."""
    with _conn() as c:
        c.execute(
            "INSERT INTO refinery_sources (run_id, source_type, ref_id, snippet) VALUES (?,?,?,?)",
            (run_id, source_type, ref_id, snippet[:300]),
        )


def log_review_result(ref_id: int, ref_type: str, review_type: str, passed: bool, notes: str = "") -> None:
    """Phase 4: 검수 결과 기록."""
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        c.execute(
            "INSERT INTO review_results (ref_id, ref_type, review_type, passed, notes, recorded) "
            "VALUES (?,?,?,?,?,?)",
            (ref_id, ref_type, review_type, int(passed), notes[:500], now),
        )


def fetch_refinery_runs(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM refinery_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Phase 4: 일자별 조회 (Obsidian Daily Summary 용) ─────────────────────────

def fetch_debates_by_date(date_iso: str) -> list[dict]:
    """date_iso='YYYY-MM-DD' 인 토론 목록 (오래된 순)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, topic, created, summary, verdict, debate_mode, thread_id "
            "FROM debates WHERE substr(created,1,10)=? ORDER BY id ASC",
            (date_iso,),
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_refinery_runs_by_date(date_iso: str) -> list[dict]:
    """date_iso='YYYY-MM-DD' 인 정제소 실행 목록 (오래된 순)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, created, topic, status, template_id "
            "FROM refinery_runs WHERE substr(created,1,10)=? ORDER BY id ASC",
            (date_iso,),
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_token_usage_by_date(date_iso: str) -> dict:
    """date_iso='YYYY-MM-DD' 의 모델별 비용 집계."""
    with _conn() as c:
        rows = c.execute(
            "SELECT model, SUM(prompt_tokens) AS p_tok, SUM(complete_tokens) AS c_tok, "
            "       ROUND(SUM(cost_usd), 6) AS cost, COUNT(*) AS calls "
            "FROM token_usage WHERE substr(recorded,1,10)=? "
            "GROUP BY model ORDER BY cost DESC",
            (date_iso,),
        ).fetchall()
        total = c.execute(
            "SELECT ROUND(SUM(cost_usd),6) AS cost, SUM(prompt_tokens) AS p_tok, "
            "       SUM(complete_tokens) AS c_tok, COUNT(*) AS calls "
            "FROM token_usage WHERE substr(recorded,1,10)=?",
            (date_iso,),
        ).fetchone()
    return {
        "by_model": [dict(r) for r in rows],
        "total": dict(total) if total else {"cost": 0, "p_tok": 0, "c_tok": 0, "calls": 0},
    }

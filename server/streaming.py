"""Bridge debate.run_debate (sync, callback-based) to async SSE.

run_debate is blocking and uses an `on_message` callback. We run it in a
background thread and push events into an asyncio.Queue that an SSE handler
drains. Cancellation: the SSE consumer disconnecting flips a flag the
callback observes (returning False to stop).
"""
from __future__ import annotations

import asyncio
import json
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StreamSession:
    id: str
    queue: asyncio.Queue
    loop: asyncio.AbstractEventLoop
    cancelled: threading.Event = field(default_factory=threading.Event)
    done: bool = False
    result: dict[str, Any] | None = None  # filled on completion


_sessions: dict[str, StreamSession] = {}


def get_session(sid: str) -> StreamSession | None:
    return _sessions.get(sid)


def _emit(session: StreamSession, event: dict[str, Any]) -> None:
    session.loop.call_soon_threadsafe(session.queue.put_nowait, event)


def start_debate_stream(req: dict[str, Any]) -> StreamSession:
    """Kick off run_debate in a thread; return a session id for SSE polling.

    Must be called from inside the running asyncio event loop (e.g. from an
    `async def` FastAPI handler) so we can capture the loop for cross-thread
    queue puts.
    """
    loop = asyncio.get_running_loop()
    sid = uuid.uuid4().hex[:12]
    session = StreamSession(id=sid, queue=asyncio.Queue(), loop=loop)
    _sessions[sid] = session

    thread = threading.Thread(
        target=_run_in_thread, args=(session, req), daemon=True
    )
    thread.start()
    return session


def _run_in_thread(session: StreamSession, req: dict[str, Any]) -> None:
    try:
        from debate import run_debate  # imported lazily; heavy
        from db import save_debate

        _emit(session, {"type": "status", "stage": "starting"})

        # Resolve which model each role will actually use, so the UI can show
        # the picked backend even for "(auto)" selections.
        try:
            import config as cfg

            resolved: dict[str, str] = {}
            user_picks = req.get("agent_backends") or {}
            recommended = (
                cfg.get_auto_recommended_backends(req.get("quality_profile", "balanced"))
                or cfg.get_default_free_backends()
                or {}
            )
            for role in ("pro", "con", "judge", "fact", "audience"):
                pick = user_picks.get(role)
                resolved[role] = pick or recommended.get(role) or ""
            _emit(session, {"type": "status", "stage": "resolved", "backends": resolved})
        except Exception:
            pass

        round_counter = {"n": 0}
        # 누적 사용량 — 에이전트별 (prompt/completion/cost) 마지막 스냅샷
        usage_prev: dict[str, dict[str, float]] = {}
        usage_total = {"prompt": 0, "completion": 0, "cost_usd": 0.0, "by_role": {}}
        # Phase 5: 종료 시점 최종 합산용 agent 에이리어스 수집
        seen_agents: dict[str, Any] = {}

        def _read_agent_usage(agent: Any) -> dict[str, float]:
            """autogen agent의 누적 usage를 합산해 {prompt, completion, cost} 반환."""
            try:
                client = getattr(agent, "client", None)
                if client is None:
                    return {}
                summary = getattr(client, "total_usage_summary", None) or {}
                if not isinstance(summary, dict):
                    return {}
                p = c = 0
                cost = 0.0
                for k, v in summary.items():
                    if not isinstance(v, dict):
                        # autogen v0.2: 'total_cost' top-level float
                        if k == "total_cost" and isinstance(v, (int, float)):
                            cost = float(v)
                        continue
                    p += int(v.get("prompt_tokens", 0) or 0)
                    c += int(v.get("completion_tokens", 0) or 0)
                    cost += float(v.get("cost", 0.0) or 0.0)
                return {"prompt": p, "completion": c, "cost": cost}
            except Exception:
                return {}

        def on_message(msg: dict[str, Any]) -> bool:
            if session.cancelled.is_set():
                return False
            role = msg.get("role") or msg.get("name", "")
            speaker = msg.get("name") or msg.get("speaker") or role
            content = msg.get("content", "") or msg.get("message", "")
            r = msg.get("round")
            if isinstance(r, int) and r != round_counter["n"]:
                round_counter["n"] = r
                _emit(session, {"type": "status", "stage": "round", "round": r})
            _emit(
                session,
                {
                    "type": "message",
                    "role": role,
                    "speaker": speaker,
                    "content": content,
                    "round": r,
                    "model": msg.get("model"),
                },
            )
            # ── 사용량 델타 추출 ──
            agent_obj = msg.get("_agent")
            if agent_obj is not None and role and role not in ("user", "system"):
                seen_agents[role] = agent_obj
                cur = _read_agent_usage(agent_obj)
                if cur:
                    prev = usage_prev.get(role, {"prompt": 0, "completion": 0, "cost": 0.0})
                    d_p = max(0, int(cur.get("prompt", 0)) - int(prev.get("prompt", 0)))
                    d_c = max(0, int(cur.get("completion", 0)) - int(prev.get("completion", 0)))
                    d_cost = max(0.0, float(cur.get("cost", 0.0)) - float(prev.get("cost", 0.0)))
                    usage_prev[role] = cur
                    if d_p or d_c or d_cost:
                        usage_total["prompt"] += d_p
                        usage_total["completion"] += d_c
                        usage_total["cost_usd"] += d_cost
                        # 에이전트의 실제 모델명 추출 (Phase 5 연계)
                        agent_model = ""
                        try:
                            cl = getattr(agent_obj, "llm_config", None) or {}
                            cls = cl.get("config_list") if isinstance(cl, dict) else None
                            if cls:
                                agent_model = (cls[0] or {}).get("model", "") or ""
                        except Exception:
                            pass
                        bro = usage_total["by_role"].setdefault(
                            role, {"prompt": 0, "completion": 0, "cost_usd": 0.0, "model": agent_model}
                        )
                        if not bro.get("model") and agent_model:
                            bro["model"] = agent_model
                        bro["prompt"] += d_p
                        bro["completion"] += d_c
                        bro["cost_usd"] += d_cost
                        _emit(session, {
                            "type": "usage",
                            "role": role,
                            "delta": {"prompt": d_p, "completion": d_c, "cost_usd": d_cost},
                            "total": {
                                "prompt": usage_total["prompt"],
                                "completion": usage_total["completion"],
                                "cost_usd": round(usage_total["cost_usd"], 6),
                            },
                        })
            return True

        ab = req.get("agent_backends") or {}
        agent_backends = {k: v for k, v in ab.items() if v}

        messages = run_debate(
            topic=req["topic"],
            context=req.get("context", ""),
            persona=req.get("persona", "balanced"),
            use_web_search=req.get("use_web_search", False),
            use_rag=req.get("use_rag", False),
            rag_collection=req.get("rag_collection", "budget"),
            use_polymarket=req.get("use_polymarket", False),
            agent_backends=agent_backends or None,
            on_message=on_message,
            quality_profile=req.get("quality_profile", "balanced"),
            auto_model_enabled=req.get("auto_model_enabled", True),
            debate_mode=req.get("debate_mode", "debate"),
            max_round=req.get("max_rounds", 3),
        )

        verdict = ""
        for m in reversed(messages or []):
            if m.get("role") == "judge" and m.get("content"):
                verdict = m["content"]
                break

        _emit(session, {"type": "status", "stage": "saving"})
        debate_id = save_debate(
            topic=req["topic"],
            messages=messages or [],
            verdict=verdict,
            debate_mode=req.get("debate_mode", "debate"),
            thread_id=req.get("thread_id"),
        )

        # ── Phase 5: 모델별 토큰/비용 DB 적재 (token_usage 누적) ──
        try:
            from db import log_token_usage
            # 최종 합산: 계산 시점에 놓친 응답을 다시 반영 (콜백 이후 응답이 갱신됨)
            for role, agent_obj in seen_agents.items():
                cur = _read_agent_usage(agent_obj)
                if not cur:
                    continue
                prev = usage_prev.get(role, {"prompt": 0, "completion": 0, "cost": 0.0})
                d_p = max(0, int(cur.get("prompt", 0)) - int(prev.get("prompt", 0)))
                d_c = max(0, int(cur.get("completion", 0)) - int(prev.get("completion", 0)))
                d_cost = max(0.0, float(cur.get("cost", 0.0)) - float(prev.get("cost", 0.0)))
                if d_p or d_c or d_cost:
                    agent_model = ""
                    try:
                        cl = getattr(agent_obj, "llm_config", None) or {}
                        cls = cl.get("config_list") if isinstance(cl, dict) else None
                        if cls:
                            agent_model = (cls[0] or {}).get("model", "") or ""
                    except Exception:
                        pass
                    bro = usage_total["by_role"].setdefault(
                        role, {"prompt": 0, "completion": 0, "cost_usd": 0.0, "model": agent_model}
                    )
                    bro["prompt"] += d_p
                    bro["completion"] += d_c
                    bro["cost_usd"] += d_cost
                    if not bro.get("model") and agent_model:
                        bro["model"] = agent_model
                    usage_total["prompt"] += d_p
                    usage_total["completion"] += d_c
                    usage_total["cost_usd"] += d_cost

            by_model: dict[str, dict[str, float]] = {}
            for role, u in (usage_total.get("by_role") or {}).items():
                model = (u.get("model") or "unknown") if isinstance(u, dict) else "unknown"
                bm = by_model.setdefault(model, {"p": 0, "c": 0, "cost": 0.0})
                bm["p"] += int(u.get("prompt", 0) or 0)
                bm["c"] += int(u.get("completion", 0) or 0)
                bm["cost"] += float(u.get("cost_usd", 0.0) or 0.0)
            for model, agg in by_model.items():
                if agg["p"] or agg["c"] or agg["cost"]:
                    log_token_usage(
                        debate_id=debate_id,
                        model=model,
                        prompt_tokens=int(agg["p"]),
                        complete_tokens=int(agg["c"]),
                        cost_usd=float(agg["cost"]),
                    )
        except Exception as _e:
            _emit(session, {"type": "status", "stage": "warn", "detail": f"token_usage 기록 실패: {_e}"})

        saved_path = None
        saved_ok = False
        if req.get("save_obsidian", True):
            try:
                from integrations.obsidian_save import save_to_obsidian

                res = save_to_obsidian(
                    topic=req["topic"],
                    messages=messages or [],
                    verdict=verdict,
                    debate_id=debate_id,
                    debate_mode=req.get("debate_mode", "debate"),
                    usage_summary={
                        "prompt": usage_total["prompt"],
                        "completion": usage_total["completion"],
                        "cost_usd": round(usage_total["cost_usd"], 6),
                        "by_role": usage_total["by_role"],
                    },
                )
                saved_ok = bool(getattr(res, "ok", False))
                saved_path = getattr(res, "vault_path", None)
                import logging as _logging
                _log = _logging.getLogger(__name__)
                if saved_ok:
                    _log.info("obsidian saved: %s [%s]", saved_path, res.status_line())
                else:
                    _log.warning("obsidian save failed: %s", res.errors)
            except Exception as e:  # noqa: BLE001
                import logging as _logging
                _logging.getLogger(__name__).error("obsidian save failed: %s", e, exc_info=True)
                _emit(session, {"type": "status", "stage": "warn", "message": f"obsidian: {e}"})

        session.result = {
            "debate_id": debate_id,
            "verdict": verdict,
            "saved_obsidian": saved_ok,
            "saved_path": saved_path,
        }
        _emit(
            session,
            {
                "type": "done",
                "debate_id": debate_id,
                "verdict": verdict,
                "saved_obsidian": saved_ok,
                "saved_path": saved_path,
                "usage_total": {
                    "prompt": usage_total["prompt"],
                    "completion": usage_total["completion"],
                    "cost_usd": round(usage_total["cost_usd"], 6),
                    "by_role": usage_total["by_role"],
                },
            },
        )
    except Exception as e:  # noqa: BLE001
        _emit(
            session,
            {
                "type": "status",
                "stage": "error",
                "message": f"{type(e).__name__}: {e}",
            },
        )
        traceback.print_exc()
    finally:
        session.done = True
        _emit(session, {"type": "_eof"})


async def event_stream(session: StreamSession):
    """Async generator yielding SSE-formatted lines."""
    try:
        while True:
            event = await session.queue.get()
            if event.get("type") == "_eof":
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    except asyncio.CancelledError:
        session.cancelled.set()
        raise
    finally:
        # keep session for a short while so a late GET can still see result;
        # simple GC: pop if done
        if session.done:
            _sessions.pop(session.id, None)


# ── 정제소 스트리밍 (Phase 2) ──────────────────────────────────────────────

def start_refinery_stream(req: dict[str, Any]) -> StreamSession:
    """refine() 4단계 진행을 SSE로 중계."""
    loop = asyncio.get_running_loop()
    sid = uuid.uuid4().hex[:12]
    session = StreamSession(id=sid, queue=asyncio.Queue(), loop=loop)
    _sessions[sid] = session

    thread = threading.Thread(
        target=_run_refinery_in_thread, args=(session, req), daemon=True
    )
    thread.start()
    return session


# 진행 메시지 → 단계 키 매핑
_STAGE_MAP = {
    "Step 1/4": "parse",
    "Step 2/4": "align",
    "Step 3/4": "transmute",
    "Step 4/4": "critique",
    "템플릿 조립": "render",
    "정제 완료": "done",
}


def _run_refinery_in_thread(session: StreamSession, req: dict[str, Any]) -> None:
    try:
        from reporting.refiner import refine, RefineryInput

        _emit(session, {"type": "status", "stage": "starting"})

        def _on_progress(msg: str) -> None:
            stage_key = next((v for k, v in _STAGE_MAP.items() if k in msg), "progress")
            _emit(session, {"type": "status", "stage": stage_key, "message": msg})

        inp = RefineryInput(
            raw_text=req["raw_text"],
            topic=req["topic"],
            source_ai=req.get("source_ai", ""),
            template_id=req.get("template_id", "jangan_base"),
            use_wisdom_rag=req.get("use_wisdom_rag", True),
            use_alignment=req.get("use_alignment", True),
            use_critique=req.get("use_critique", True),
            quality=req.get("quality", "balanced"),
            backend_key=req.get("backend_key", ""),
        )
        out = refine(inp, on_progress=_on_progress)

        if out.error:
            _emit(session, {"type": "status", "stage": "error", "message": out.error})
        session.result = {
            "run_id": out.run_id,
            "report_md": out.report_md,
            "alignment_intro": out.alignment_intro,
            "critique_md": out.critique_md,
            "citations": out.citations,
            "replacements": out.replacements,
            "model_log": out.model_log,
            "error": out.error,
        }
        _emit(session, {
            "type": "done",
            "run_id": out.run_id,
            "report_md": out.report_md,
            "alignment_intro": out.alignment_intro,
            "critique_md": out.critique_md,
            "citations": out.citations,
            "replacements": out.replacements,
            "model_log": out.model_log,
            "error": out.error,
        })
    except Exception as e:  # noqa: BLE001
        _emit(session, {
            "type": "status", "stage": "error",
            "message": f"{type(e).__name__}: {e}",
        })
        traceback.print_exc()
    finally:
        session.done = True
        _emit(session, {"type": "_eof"})


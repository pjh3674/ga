from __future__ import annotations

import os
import sys
import time
import shutil
import unicodedata
import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── 경로 설정 ───────────────────────────────────────────────────────────────
NAS_VAULT_ROOT = Path("/mnt/nas")
VAULT_DIR      = "88.작업/GA토론결과"

# NAS 불가 시 로컬 임시 대기 큐 (재마운트 후 자동 재동기화)
_BASE_DIR    = Path(__file__).resolve().parents[1]
PENDING_DIR  = _BASE_DIR / "results" / "_obsidian_pending"
PENDING_DIR.mkdir(parents=True, exist_ok=True)

# ── REST API 폴백 ────────────────────────────────────────────────────────────
try:
    _obsidian_dir = str(Path.home() / "obsidian")
    if _obsidian_dir not in sys.path:
        sys.path.insert(0, _obsidian_dir)
    import importlib
    if "obsidian_api_helper" in sys.modules:
        del sys.modules["obsidian_api_helper"]
    from integrations.obsidian_api_helper import obsidian_put as _obsidian_put
    _REST_AVAILABLE = True
except Exception:
    _REST_AVAILABLE = False
    _obsidian_put = None


@dataclass
class SaveResult:
    """저장 결과 상세 (silent-fail 제거를 위한 명시적 반환값)."""
    vault_path: str           = ""    # Obsidian 볼트 내 상대 경로
    nas_path:   str           = ""    # NAS 절대 경로 (저장됐을 경우)
    pending_path: str         = ""    # 폴백 대기 경로 (NAS 불가일 때)
    nas_ok:     bool          = False
    rest_ok:    bool          = False
    pending_ok: bool          = False
    errors:     list[str]     = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.nas_ok or self.rest_ok or self.pending_ok

    def status_line(self) -> str:
        parts = []
        if self.nas_ok:     parts.append("NAS ✅")
        if self.rest_ok:    parts.append("REST ✅")
        if self.pending_ok: parts.append("대기큐 ⏳")
        if self.errors:     parts.append(f"오류 {len(self.errors)}건")
        return " | ".join(parts) if parts else "저장 실패"


def _sanitize_filename(name: str, max_bytes: int = 90) -> str:
    """Livesync 안전 파일명: NFC, 특수문자 제거, 바이트 제한."""
    # NFC 유니코드 정규화 (Livesync NFD 충돌 방지)
    name = unicodedata.normalize("NFC", name)
    # 파일명 금지 문자 제거
    name = re.sub(r'[\\/*?"<>|\r\n\t]', "-", name)
    name = name.strip(" .-")
    # 바이트 길이 컷 (한글 3바이트/자)
    encoded = name.encode("utf-8")
    if len(encoded) > max_bytes:
        name = encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()
    return name or "untitled"


def _nas_writable() -> bool:
    """NAS 마운트 + 쓰기 권한 실시간 확인."""
    return NAS_VAULT_ROOT.exists() and os.access(str(NAS_VAULT_ROOT), os.W_OK)


def _atomic_write(target: Path, content: str) -> None:
    """임시파일 → atomic rename (Livesync 부분파일 노출 방지)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.rename(target)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def _unique_path(path: Path) -> Path:
    """동일 경로 존재 시 _v2, _v3 자동 부여."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    parent = path.parent
    for i in range(2, 100):
        candidate = parent / f"{stem}_v{i}{suffix}"
        if not candidate.exists():
            return candidate
    return parent / f"{stem}_{int(time.time())}{suffix}"


def flush_pending_to_nas() -> list[str]:
    """
    Phase 0: 대기 큐(_obsidian_pending)에 쌓인 파일을 NAS로 재동기화.
    NAS가 복구됐을 때 수동 or ga_auto_debate.py 시작 시 호출.
    성공한 파일 목록 반환.
    """
    if not _nas_writable():
        return []
    synced = []
    for pending_file in PENDING_DIR.glob("**/*.md"):
        # 메타파일에 원래 볼트 경로 기록됨
        meta_file = pending_file.with_suffix(".meta")
        if meta_file.exists():
            vault_rel = meta_file.read_text(encoding="utf-8").strip()
        else:
            vault_rel = f"{VAULT_DIR}/pending/{pending_file.name}"
        nas_target = _unique_path(NAS_VAULT_ROOT / vault_rel)
        try:
            _atomic_write(nas_target, pending_file.read_text(encoding="utf-8"))
            pending_file.unlink(missing_ok=True)
            meta_file.unlink(missing_ok=True)
            synced.append(str(nas_target))
        except Exception:
            pass
    return synced


# ── 공개 API ─────────────────────────────────────────────────────────────────

def save_to_obsidian(
    topic: str,
    messages: list[dict],
    verdict: str = "",
    debate_id: int = 0,
    debate_mode: str = "debate",
    report_draft: str = "",
    usage_summary: dict | None = None,
) -> SaveResult:
    """
    토론/정제 결과를 Obsidian 마크다운 노트로 저장.

    저장 우선순위:
      1. NAS 직접 파일 저장 (Livesync 동기화 기반)
      2. REST API 저장 (Obsidian 앱에 즉시 반영)
      3. 로컬 폴백 큐 (_obsidian_pending/) → NAS 복구 시 flush_pending_to_nas()

    반환: SaveResult (nas_ok/rest_ok/pending_ok/errors 모두 명시)
    Raises: 이제 예외 안 던짐 — 결과를 SaveResult.errors로 반환.
    """
    result = SaveResult()

    _MODE_SUBDIR = {
        "debate":     "찬반토론",
        "strengths":  "강점분석",
        "weaknesses": "약점진단",
        "swot":       "SWOT분석",
        "refinery":   "정제결과",
    }
    subdir    = _MODE_SUBDIR.get(debate_mode, "찬반토론")
    now       = datetime.datetime.now()
    date_str  = now.strftime("%Y%m%d_%H%M")
    safe_name = _sanitize_filename(topic[:30])
    vault_path = f"{VAULT_DIR}/{subdir}/{date_str}_{safe_name}.md"
    result.vault_path = vault_path

    content = _build_markdown(
        topic, messages, verdict, debate_id, now, debate_mode,
        report_draft=report_draft,
        usage_summary=usage_summary,
    )

    # ── 1순위: NAS 직접 저장 (atomic write) ─────────────────────────────────
    if _nas_writable():
        nas_target = _unique_path(NAS_VAULT_ROOT / vault_path)
        result.nas_path = str(nas_target)
        try:
            _atomic_write(nas_target, content)
            result.nas_ok = True
        except PermissionError as e:
            result.errors.append(f"NAS 쓰기 권한 없음: {e}")
        except OSError as e:
            result.errors.append(f"NAS 파일시스템 오류: {e}")
        except Exception as e:
            result.errors.append(f"NAS 저장 실패: {e}")
    else:
        result.errors.append("NAS 미마운트 또는 쓰기 불가")

    # ── 2순위: REST API (NAS와 병행, Obsidian 앱 즉시 반영) ─────────────────
    if _REST_AVAILABLE and _obsidian_put:
        try:
            r = _obsidian_put(vault_path, content)
            if r is not None and r.status_code in (200, 201, 204):
                result.rest_ok = True
            elif r is not None:
                result.errors.append(f"REST API HTTP {r.status_code}")
            else:
                result.errors.append("REST API 응답 없음")
        except ConnectionError as e:
            result.errors.append(f"Obsidian REST 연결 실패: {e}")
        except Exception as e:
            result.errors.append(f"REST API 오류: {e}")

    # ── 3순위: 로컬 폴백 큐 (NAS/REST 모두 실패 시) ────────────────────────
    if not result.nas_ok and not result.rest_ok:
        try:
            pending_target = _unique_path(PENDING_DIR / subdir / f"{date_str}_{safe_name}.md")
            _atomic_write(pending_target, content)
            # 원래 볼트 경로를 메타파일에 기록
            pending_target.with_suffix(".meta").write_text(vault_path, encoding="utf-8")
            result.pending_path = str(pending_target)
            result.pending_ok   = True
            result.errors.append(
                f"⚠️ NAS/REST 실패로 로컬 폴백 저장: {pending_target.name} "
                "— NAS 복구 후 flush_pending_to_nas() 실행 필요"
            )
        except Exception as e:
            result.errors.append(f"폴백 저장도 실패: {e}")

    return result


def save_refinery_output(
    topic: str,
    report_md: str,
    critique_md: str = "",
    citations: list[str] | None = None,
    run_id: int = 0,
) -> SaveResult:
    """
    Phase 1: AI 정제소 결과 전용 저장.
    /88.작업/GA토론결과/정제결과/ 에 저장.
    """
    full_content = report_md
    if critique_md:
        full_content += "\n\n---\n\n" + critique_md
    if citations:
        full_content += "\n\n---\n\n### 📚 참고 출처\n" + "\n".join(f"- {c}" for c in citations)

    # save_to_obsidian을 메시지 없이 호출 (report_draft=full_content)
    return save_to_obsidian(
        topic=topic,
        messages=[],
        verdict="",
        debate_id=run_id,
        debate_mode="refinery",
        report_draft=full_content,
    )


def _build_markdown(
    topic: str,
    messages: list[dict],
    verdict: str,
    debate_id: int,
    dt: datetime.datetime,
    debate_mode: str = "debate",
    report_draft: str = "",
    usage_summary: dict | None = None,
) -> str:
    date_iso = dt.strftime("%Y-%m-%d %H:%M")

    ICONS = {
        "pro":           "🟦 추진측",
        "con":           "🟥 검토측",
        "judge":         "⚖️ 판정관",
        "fact":          "🔍 법령검토",
        "audience":      "👥 현장질의",
        "report_writer": "📝 보고서",
        "reviewer":      "🔎 검수관",
    }

    _MODE_TAG = {
        "debate":     "찬반토론",
        "strengths":  "강점분석",
        "weaknesses": "약점진단",
        "swot":       "SWOT분석",
    }
    mode_tag = _MODE_TAG.get(debate_mode, "찬반토론")

    # ── verdict 종합 판정 추출 ─────────────────────────────────────────────
    verdict_status = ""
    if verdict:
        m = re.search(r"종합\s*판정[^\n\[]*\[?([^\]\n]+?)\]?(?:\s*—|\s*$)", verdict)
        if m:
            verdict_status = m.group(1).strip().split("]")[0].strip(" *[]:—-")

    # ── 사용량 요약 ────────────────────────────────────────────────────────
    us = usage_summary or {}
    total_prompt = int(us.get("prompt", 0))
    total_completion = int(us.get("completion", 0))
    total_tokens = total_prompt + total_completion
    total_cost = float(us.get("cost_usd", 0.0))
    by_role = us.get("by_role") or {}

    roles_used = sorted({m.get("name", "") for m in messages if m.get("name") in ICONS})

    # ── 프론트매터 ─────────────────────────────────────────────────────────
    lines = [
        "---",
        f"tags: [GA검토, AI정책검토, {mode_tag}]",
        f"date: {date_iso}",
        f"debate_id: {debate_id}",
        f"mode: {debate_mode}",
        f"has_report: {'true' if report_draft else 'false'}",
        f"roles: [{', '.join(roles_used)}]" if roles_used else "roles: []",
        f'verdict_status: "{verdict_status}"',
        f"total_tokens: {total_tokens}",
        f"prompt_tokens: {total_prompt}",
        f"completion_tokens: {total_completion}",
        f"cost_usd: {total_cost:.6f}",
        "---",
        "",
        f"# {topic}",
        (
            f"> 검토일시: {date_iso} | 모드: {mode_tag} | ID: {debate_id}"
            + (f" | 종합: **{verdict_status}**" if verdict_status else "")
            + (f" | 토큰: {total_tokens:,} (${total_cost:.4f})" if total_tokens else "")
        ),
        "",
    ]

    # 역할별 사용량 표
    if by_role:
        lines += ["## 📊 역할별 사용량", "", "| 역할 | prompt | completion | cost(USD) |", "|---|---:|---:|---:|"]
        for r, v in by_role.items():
            lbl = ICONS.get(r, r)
            lines.append(
                f"| {lbl} | {int(v.get('prompt',0)):,} | {int(v.get('completion',0)):,} | {float(v.get('cost_usd',0.0)):.6f} |"
            )
        lines.append("")

    # ── Phase 2: 보고서 초안 (최우선 배치) ────────────────────────────────
    if report_draft and report_draft.strip() and not report_draft.startswith("[보고서 생성 실패"):
        lines += [
            "---",
            "",
            report_draft.strip(),
            "",
            "---",
            "",
        ]
    else:
        # 보고서 없을 때: 판정 요약이라도 상단에
        if verdict:
            # Judge 체크리스트형 판정인지 파악
            is_structured = "종합 판정" in verdict or "① **법적" in verdict or "⑥ **종합" in verdict
            if is_structured:
                lines += ["## 🏛️ 검토 판정 요약", "", verdict.strip(), ""]
            else:
                lines += ["> [!important] 최종 판정", f"> {verdict}", ""]

    # ── 핵심 쟁점 요약 테이블 ─────────────────────────────────────────────
    lines += [
        "## 핵심 쟁점 요약",
        "",
        "| 역할 | 핵심 발언 |",
        "|-----|---------|",
    ]
    seen_roles = set()
    for m in messages:
        name = m.get("name", "")
        if name in seen_roles or name not in ICONS:
            continue
        content = m.get("content", "").replace("\n", " ").strip()
        if not content or len(content) < 20:
            continue
        # 시스템 블록 제외
        if content.startswith("[참고 자료") or content.startswith("[토론 주제"):
            continue
        label = ICONS.get(name, name)
        summary = content[:100] + ("…" if len(content) > 100 else "")
        lines.append(f"| {label} | {summary} |")
        seen_roles.add(name)

    # ── 부록: 전체 토론 상세 내용 (collapsible) ───────────────────────────
    lines += ["", "---", "", "## 📋 상세 토론 내용 (부록)", ""]
    for m in messages:
        name = m.get("name", "")
        content = m.get("content", "").strip()
        if not content or len(content) < 20:
            continue
        if content.startswith("[참고 자료") or content.startswith("[토론 주제") or content.startswith("### "):
            continue
        label = ICONS.get(name, name)
        lines += [f"### {label}", "", content, ""]

    return "\n".join(lines)

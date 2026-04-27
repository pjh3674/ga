# GA Debate Arena — New UI Stack

Streamlit 기반 `app.py` 위에 얹는 신규 인터페이스 (목업 일치 3단 레이아웃).

```
apps/ga/
├── app.py              # 기존 Streamlit (계속 사용 가능, 8501 포트)
├── debate.py / db.py   # 재사용되는 코어 로직
├── server/             # ★ 신규 FastAPI 백엔드 (8600 포트)
│   ├── main.py         #   REST + SSE 엔드포인트
│   ├── streaming.py    #   run_debate → asyncio.Queue → SSE 브리지
│   ├── schemas.py
│   ├── requirements.txt
│   └── Dockerfile
└── web/                # ★ 신규 Next.js 15 프런트엔드 (3001 포트)
    ├── src/app         #   페이지 + 글로벌 CSS
    ├── src/components  #   Sidebar / Arena / RightPanel / AgentGraph / MessageList / PromptHero
    ├── src/lib         #   api.ts (fetch + SSE), store.ts (zustand)
    ├── tailwind.config.ts (기존 theme.css 토큰 그대로 이식)
    ├── package.json
    └── Dockerfile
```

## 로컬 실행 (개발)

**1) FastAPI**
```bash
cd /home/pjh/apps/ga
./venv/bin/pip install -r server/requirements.txt
./venv/bin/uvicorn server.main:app --host 0.0.0.0 --port 8600 --reload
```

**2) Next.js**
```bash
cd /home/pjh/apps/ga/web
pnpm install
pnpm dev          # http://localhost:3001
```

`web/next.config.mjs`의 `rewrites`가 `/api/*` 요청을 `NEXT_PUBLIC_API_URL`(기본 `http://127.0.0.1:8600`)로 프록시합니다.

## Docker (운영)

```bash
cd /home/pjh/apps/ga
docker compose up -d --build ga-api ga-web
```

- `ga` (8501): 기존 Streamlit — 그대로 유지
- `ga-api` (8600): FastAPI — `0.0.0.0` 바인딩 → Tailscale 노출
- `ga-web` (3001): Next.js — `0.0.0.0` 바인딩 → Tailscale 노출

## Tailscale 접근

이 호스트의 Tailscale IP는 `100.127.0.5`. 다른 디바이스에서:

- 신규 UI: `http://100.127.0.5:3001`
- API 직통: `http://100.127.0.5:8600/api/health`
- 기존 Streamlit: `http://100.127.0.5:8501`

> 외부 노출 시 Tailscale ACL로 본인 디바이스만 허용되는지 한 번 확인하세요. API에 인증이 없으므로 Tailscale 외부에서 접근하려면 nginx + basic-auth 등 별도 게이트가 필요합니다.

## API 요약

| Method | Path | 용도 |
|---|---|---|
| GET  | `/api/health` | 헬스체크 |
| GET  | `/api/config` | 모델/모드/프로필 메타 |
| GET  | `/api/debates` | 아카이브 (오늘/어제/이전) |
| GET  | `/api/debates/{id}` | 토론 1건 (메시지 포함) |
| POST | `/api/debates/run` | 토론 시작 → `{debate_id: <stream-id>}` |
| GET  | `/api/debates/run/{sid}/stream` | SSE: `message` / `status` / `done` |

SSE 이벤트 형식:
```json
{"type":"message", "role":"pro", "speaker":"...", "content":"...", "round":1, "model":"google/gemini-2.5-flash"}
{"type":"status",  "stage":"round", "round":2}
{"type":"done",    "debate_id":42, "verdict":"...", "saved_obsidian":true, "saved_path":"..."}
```

## 아키텍처 메모

- `run_debate`는 동기 함수 + `on_message` 콜백 구조이므로, `streaming.py`에서 별도 스레드로 돌리고 콜백이 `asyncio.Queue`에 이벤트를 푸시합니다 (`loop.call_soon_threadsafe`).
- SSE 클라이언트가 끊기면 `asyncio.CancelledError`가 발생하고 `session.cancelled` 플래그가 켜져, 다음 `on_message`에서 `False`를 반환해 토론을 중단시킵니다.
- DB는 SQLite (`ga.db`)를 그대로 사용 — 기존 Streamlit과 동시 사용 가능.
- Obsidian 저장은 토론 완료 후 자동 호출. 실패해도 토론 자체는 성공으로 처리(에러는 `status: warn` 이벤트로 통보).

## 다음 단계 후보

- 토론 진행 중 `Cancel` 버튼 (현재는 ESC/탭 닫기로만 중단)
- 아카이브 항목 클릭 → 상세 패널 (메시지 리플레이)
- 페르소나/모드 선택 UI (RightPanel에 섹션 추가)
- 인증 (Tailscale 외부 접근 시)

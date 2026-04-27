# GA Debate Arena: 운영 단축 명령
.PHONY: up down logs build restart backup status test-health test-alert

## 서비스 시작 (이미지 재빌드 포함)
up:
	docker compose up -d --build ga-api ga-web

## 서비스 중단
down:
	docker compose down

## 실시간 로그 (api/web)
logs:
	docker compose logs -f ga-api ga-web

## 이미지만 재빌드
build:
	docker compose build ga-api ga-web

## 재시작
restart:
	docker compose restart ga-api ga-web

## 수동 백업 즉시 실행
backup:
	@bash scripts/backup.sh

## 컨테이너 상태 확인
status:
	@docker compose ps

## 헬스체크 즉시 테스트
test-health:
	@curl -fsS http://localhost:8600/api/health && echo
	@curl -fsS -o /dev/null -w 'web=%{http_code}\n' http://localhost:3001/

## Telegram 알림 즉시 테스트
test-alert:
	python3 scripts/watchdog.py

PY=python3
PIP=pip

.PHONY: setup run test fmt up down restart ps logs killports docker-up docker-down docker-logs docker-ps docker-test

setup:
	$(PY) -m venv venv && . venv/bin/activate && $(PIP) install -r requirements.txt

run:
	$(PY) -m controller.main

test:
	pytest -q

up:
	docker-compose up --build -d

down:
	docker-compose down

restart: down up

ps:
	docker-compose ps

logs:
	docker-compose logs -f --tail=200

killports:
	bash scripts/kill_ports.sh 8000 8001 8002 8003 8084 || true

# Docker helpers

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

docker-ps:
	docker compose ps

docker-logs:
	docker compose logs -f --tail=200

docker-test:
	@echo "Health:" && curl -sS http://localhost:8084/health || true && \
	echo "\nPolicy auto-route:" && curl -sS -X POST http://localhost:8084/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"","messages":[{"role":"user","content":"Write Python code to parse JSON"}],"extra_body":{"routing_policy":"task_router"}}' | python -m json.tool || true

# Makefile — lint / test / smoke / deploy / boot / backup（对齐四口之家，端口改 5001）
.PHONY: lint test smoke deploy boot backup

PY=python3
VENV=.venv
PYBIN=$(VENV)/bin/python
PYTEST=$(VENV)/bin/pytest
RUFF=$(VENV)/bin/ruff

PORT ?= 5001
SMOKE_PORT ?= 5002
DATA_DIR ?= /tmp/aistudy_smoke

lint:
	$(RUFF) check backend/

test:
	$(PYTEST) -q --cov=backend --cov-report=term-missing --cov-fail-under=50

smoke:
	FLASK_ENV=production PORT=$(SMOKE_PORT) HOST=127.0.0.1 $(PYBIN) backend/app.py & \
	APP_PID=$$!; \
	for _ in $$(seq 1 30); do \
		curl -fsS http://127.0.0.1:$(SMOKE_PORT)/health >/dev/null 2>&1 && break; \
		sleep 1; \
	done; \
	curl -fsS http://127.0.0.1:$(SMOKE_PORT)/health; \
	kill $$APP_PID 2>/dev/null; true

# 本地启动（开发预览，前台）
boot:
	cd backend && ../$(PYBIN) -c "from waitress import serve; from app import create_app; import os; serve(create_app(os.environ.get('FLASK_ENV','development')), host='127.0.0.1', port=$(PORT), threads=4)"

# 发布入口：部署（重启服务）+ 备份
deploy:
	bash deploy/install_launchd.sh
	@echo "→ 重启: launchctl kickstart -k gui/$$(id -u)/com.aistudy.service  (或见 deploy/run.sh 手动)"

backup:
	bash scripts/backup_icloud.sh

all: lint test smoke

.PHONY: help dev dev-api dev-frontend dev-engine run-safe check check-backend check-frontend smoke agent-anomaly

PYTHON ?= .venv/bin/python
UVICORN ?= $(PYTHON) -m uvicorn
FRONTEND_DIR ?= frontend

help:
	@echo "Targets:"
	@echo "  make dev           - start API + frontend + engine together (logs in .devlogs/)"
	@echo "  make dev-api       - start FastAPI with --reload on :8000"
	@echo "  make dev-frontend  - start Vite dev server on :5173"
	@echo "  make dev-engine    - start trading engine only"
	@echo "  make run-safe      - run run.py with AUTO_RESTART_ON_BACKEND_CHANGES=false"
	@echo "  make check         - run backend + frontend checks + API smoke checks"
	@echo "  make check-backend - fast backend syntax/import checks"
	@echo "  make check-frontend- frontend type/lint checks"
	@echo "  make smoke         - hit core API endpoints (/api/portfolio/summary, /api/intent)"
	@echo "  make agent-anomaly - run autonomous anomaly triage/fix agent (log + db driven)"

dev:
	@bash scripts/dev/dev.sh

dev-api:
	@$(UVICORN) dashboard_api:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	@cd $(FRONTEND_DIR) && npm run dev

dev-engine:
	@$(PYTHON) main.py

run-safe:
	@AUTO_RESTART_ON_BACKEND_CHANGES=false $(PYTHON) run.py

check:
	@$(MAKE) check-backend
	@$(MAKE) check-frontend
	@$(MAKE) smoke

check-backend:
	@$(PYTHON) -m py_compile config.py dashboard_api.py engine.py main.py run.py

check-frontend:
	@cd $(FRONTEND_DIR) && npm run -s typecheck && npm run -s lint

smoke:
	@bash scripts/dev/smoke.sh

agent-anomaly:
	@bash scripts/agents/anomaly_fix_agent.sh

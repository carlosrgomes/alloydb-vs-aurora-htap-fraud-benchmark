.PHONY: help up-local down-local seed-local benchmark-local worker-local report lint test tf-apply-gcp tf-apply-aws destroy-cloud

PYTHON ?= python3
PG_DSN ?= postgresql://postgres:postgres@localhost:5432/postgres

help:
	@echo "================================================================================"
	@echo "  AlloyDB vs. AWS Aurora HTAP + Filtered Vector Benchmark Automation"
	@echo "================================================================================"
	@echo "  make up-local         Start local AlloyDB Omni 16 container (Docker Compose)"
	@echo "  make down-local       Stop local AlloyDB Omni 16 container"
	@echo "  make seed-local       Seed local database with synthetic ledger & 64-D vectors"
	@echo "  make benchmark-local  Run 4-mode ablation suite against local AlloyDB Omni"
	@echo "  make worker-local     Start lock-free asynchronous Gemini 4 Hydrogen worker"
	@echo "  make report           Generate results/benchmark_summary.md & raw_telemetry.csv"
	@echo "  make test             Execute unit and integration test suites (pytest)"
	@echo "  make lint             Run ruff linter and formatting verification"
	@echo "  make tf-apply-gcp     Provision 4 vCPU / 32 GB GCP AlloyDB parity cluster"
	@echo "  make tf-apply-aws     Provision 4 vCPU / 32 GB AWS Aurora I/O-Optimized cluster"
	@echo "  make destroy-cloud    Tear down both GCP AlloyDB and AWS Aurora cloud resources"
	@echo "================================================================================"

up-local:
	docker compose up -d
	@echo "Waiting for AlloyDB Omni 16 healthcheck..."
	@until docker compose exec -T alloydb-omni pg_isready -U postgres -d postgres >/dev/null 2>&1; do sleep 2; done
	@echo "AlloyDB Omni is ready on $(PG_DSN)"

down-local:
	docker compose down -v

seed-local:
	$(PYTHON) -m src.benchmark.seeder --dsn "$(PG_DSN)" --engine-mode alloydb --ledger-rows 200000 --signature-rows 25000

benchmark-local:
	$(PYTHON) -m src.benchmark.runner --dsn "$(PG_DSN)" --mode all --tps 500 --duration 30 --output-dir ./results

worker-local:
	$(PYTHON) -m src.agent.triage_worker --dsn "$(PG_DSN)" --agent-mode deterministic_local --once

report:
	$(PYTHON) -m src.benchmark.reporter --inputs "./results/run_*.json" --output-dir ./results

lint:
	$(PYTHON) -m ruff check src/ tests/

test:
	$(PYTHON) -m pytest -v

tf-apply-gcp:
	cd terraform/gcp_alloydb && terraform init && terraform apply -auto-approve

tf-apply-aws:
	cd terraform/aws_aurora && terraform init && terraform apply -auto-approve

destroy-cloud:
	-cd terraform/gcp_alloydb && terraform destroy -auto-approve
	-cd terraform/aws_aurora && terraform destroy -auto-approve

# DNA-website — common workflows
#
# Usage: `make <target>`. Run `make` with no args to see the menu.

.PHONY: help install install-py install-node install-browsers smoke test test-unit test-integration \
        test-cov lint format clean run-fixture serve doctor freeze precommit ci

help:
	@echo "DNA-website — make targets"
	@echo ""
	@echo "  install          Install all dependencies (Python + Node + Playwright)"
	@echo "  install-py       Python deps only"
	@echo "  install-node     Node deps only"
	@echo "  install-browsers Playwright browsers"
	@echo ""
	@echo "  smoke            Run the smoke tests (fast)"
	@echo "  test             Run the full test suite"
	@echo "  test-unit        Unit tests only"
	@echo "  test-integration Integration tests only"
	@echo "  test-cov         Tests with coverage report"
	@echo ""
	@echo "  lint             Run ruff + check format"
	@echo "  format           Auto-format with ruff"
	@echo "  precommit        Run all pre-commit hooks"
	@echo ""
	@echo "  doctor           Validate the local environment"
	@echo "  run-fixture      Run against tests/fixtures/tiny_site/"
	@echo "  serve DIR=<path> Launch the inspector against a captured run"
	@echo ""
	@echo "  clean            Remove venv, node_modules, dna-output, __pycache__"
	@echo "  freeze           Print pinned versions of all deps"

# -----------------------------------------------------------------------------
# Install
# -----------------------------------------------------------------------------

install: install-py install-node install-browsers
	@echo "✓ All dependencies installed"

install-py:
	pip install -e ".[dev]"

install-node:
	npm install

install-browsers:
	python -m playwright install chromium

# -----------------------------------------------------------------------------
# Test
# -----------------------------------------------------------------------------

smoke:
	pytest tests/test_smoke.py -v

test:
	pytest -v

test-unit:
	pytest tests/ -v -m "not integration"

test-integration:
	pytest tests/ -v -m integration

test-cov:
	pytest --cov=scripts --cov-report=term-missing --cov-report=html

# -----------------------------------------------------------------------------
# Lint / format
# -----------------------------------------------------------------------------

lint:
	ruff check scripts tests
	ruff format --check scripts tests

format:
	ruff format scripts tests
	ruff check --fix scripts tests

precommit:
	pre-commit run --all-files

# -----------------------------------------------------------------------------
# Run / inspect
# -----------------------------------------------------------------------------

doctor:
	python -m scripts.doctor

run-fixture:
	@echo "Spawning local server for tiny_site fixture..."
	@cd tests/fixtures/tiny_site && python3 -m http.server 8765 &
	@sleep 1
	@python -m scripts.run http://localhost:8765 --output dna-output/tiny-site-run --max-pages 2 --skip-assets || true
	@pkill -f "http.server 8765" || true

# Usage: make serve DIR=dna-output/tiny-site-run
serve:
	@if [ -z "$(DIR)" ]; then echo "Usage: make serve DIR=<output-dir>"; exit 1; fi
	python -m scripts.serve $(DIR)

# -----------------------------------------------------------------------------
# Housekeeping
# -----------------------------------------------------------------------------

clean:
	rm -rf .venv node_modules dna-output dist build htmlcov .pytest_cache .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name '*.egg-info' -exec rm -rf {} +

freeze:
	@echo "─── Python ───"
	@pip freeze | grep -E "playwright|beautifulsoup|scikit-learn|pydantic|typer|aiohttp" || true
	@echo ""
	@echo "─── Node ───"
	@npm list --depth=0 || true

# CI target — fail fast
ci: lint smoke test-cov

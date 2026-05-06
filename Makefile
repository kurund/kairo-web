.PHONY: help install dev migrate init test lint format clean

help:
	@echo "Targets:"
	@echo "  install   - uv sync --all-extras"
	@echo "  dev       - run FastAPI with --reload on :8001"
	@echo "  migrate   - alembic upgrade head"
	@echo "  init      - seed workspaces + owner"
	@echo "  test      - run pytest"
	@echo "  lint      - ruff check"
	@echo "  format    - ruff format"
	@echo "  clean     - remove dev DB and caches"

install:
	uv sync --all-extras

dev:
	uv run uvicorn kairo_web.main:app --reload --port 8001

migrate:
	uv run alembic upgrade head

init:
	uv run kairo-web init

test:
	uv run pytest

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

clean:
	rm -f dev.db dev.db-*
	rm -rf .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

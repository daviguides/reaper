.PHONY: test check format install

install:
	uv sync

test:
	uv run pytest

check:
	uv run ruff check src tests
	uv run mypy src

format:
	uv run ruff format src tests
	uv run ruff check --fix src tests

.PHONY: dev format lint check

dev:
	uvicorn app.main:app --reload --port 3002

format:
	ruff format .

lint:
	ruff check .

check:
	ruff format . --check
	ruff check .
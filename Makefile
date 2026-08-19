.PHONY: setup dev build start test lint benchmark

setup:
	./scripts/setup.sh

dev:
	./scripts/dev.sh

build:
	npm run build

start:
	./scripts/start.sh

test:
	cd backend && uv run pytest
	npm test

lint:
	cd backend && uv run ruff check app tests
	npm run lint
	npm run typecheck

benchmark:
	cd backend && uv run python -m app.benchmark --model realesrgan-x2plus

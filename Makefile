lint:
	uv run black src/

test:
	uv run pytest tests/

html:
	uv run sphinx-build -M html docs _html
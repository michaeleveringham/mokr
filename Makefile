lint:
	poetry run flake8 src/

test:
	poetry run pytest tests/

html:
	poetry run sphinx-build -M html docs _html
PYTHON ?= $(CURDIR)/.venv/bin/python
RUFF ?= $(CURDIR)/.venv/bin/ruff

.PHONY: check lint test test-db compose data

check: lint test compose

lint:
	cd backend && "$(RUFF)" check .

# Target individual tests with: make test TESTS='tests/test_search.py -k responsiveness'
test:
	cd backend && env -u DART_API_KEY -u TEST_DATABASE_URL EMBEDDING_WARMUP_ENABLED=false "$(PYTHON)" -m pytest -q --ignore=tests/test_smoke.py $(TESTS)

test-db:
	cd backend && "$(PYTHON)" -m tests.run_postgres

compose:
	docker compose --profile container config -q

# Bundled SQLite file and report in dist/ (git-ignored). Release build by default; add
# DATA_FLAGS=--allow-unapproved for a development build. PINNED is the directory of pinned
# regulator responses; DATABASE_URL picks the build database.
data:
	$(if $(AS_OF),,$(error set AS_OF=YYYY-MM-DD))
	$(if $(PINNED),,$(error set PINNED=<directory of pinned regulator responses>))
	cd backend && "$(PYTHON)" -m app.build.export --as-of "$(AS_OF)" \
		--out "$(CURDIR)/dist/footnote.sqlite" --pinned "$(abspath $(PINNED))" $(DATA_FLAGS)

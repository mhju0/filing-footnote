PYTHON ?= $(CURDIR)/.venv/bin/python
RUFF ?= $(CURDIR)/.venv/bin/ruff

.PHONY: check lint test test-db compose data data-preview

check: lint test compose

lint:
	cd backend && "$(RUFF)" check .

# Target individual tests with: make test TESTS='tests/test_comparison_cases.py -k margin'
test:
	cd backend && env -u DART_API_KEY -u TEST_DATABASE_URL "$(PYTHON)" -m pytest -q $(TESTS)

test-db:
	cd backend && "$(PYTHON)" -m tests.run_postgres

compose:
	docker compose config -q

# Bundled SQLite file and report in dist/ (git-ignored). Release build by default; add
# DATA_FLAGS=--allow-unapproved for a development build. PINNED is the directory of pinned
# regulator responses; DATABASE_URL picks the build database.
data:
	$(if $(AS_OF),,$(error set AS_OF=YYYY-MM-DD))
	$(if $(PINNED),,$(error set PINNED=<directory of pinned regulator responses>))
	cd backend && "$(PYTHON)" -m app.build.export --as-of "$(AS_OF)" \
		--out "$(CURDIR)/dist/footnote.sqlite" --pinned "$(abspath $(PINNED))" $(DATA_FLAGS)

# The same bundle as a preview for internal TestFlight (D90): filings without approved
# summaries are left out and listed in the report; every other release check stays on.
data-preview:
	$(if $(AS_OF),,$(error set AS_OF=YYYY-MM-DD))
	$(if $(PINNED),,$(error set PINNED=<directory of pinned regulator responses>))
	cd backend && "$(PYTHON)" -m app.build.export --as-of "$(AS_OF)" --preview \
		--out "$(CURDIR)/dist/footnote.sqlite" --pinned "$(abspath $(PINNED))"
	cd backend && "$(PYTHON)" -m app.build.verify "$(CURDIR)/dist/footnote.sqlite" --preview \
		--pinned "$(abspath $(PINNED))"

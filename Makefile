.PHONY: test lint build release bump-version clean

# Run all tests
test:
	uv run pytest --tb=short -q

# Lint
lint:
	uv run ruff check .

# Build all distributable packages into dist/
build:
	rm -rf dist/
	mkdir -p dist/
	@for pkg in \
		context-router-cli \
		context-router-contracts \
		context-router-core \
		context-router-storage-sqlite \
		context-router-graph-index \
		context-router-ranking \
		context-router-memory \
		context-router-runtime \
		context-router-workspace \
		context-router-benchmark \
		context-router-language-python \
		context-router-language-typescript \
		context-router-language-yaml \
		context-router-adapters-claude \
		context-router-adapters-copilot \
		context-router-adapters-codex; do \
		echo "Building $$pkg..."; \
		uv build --package "$$pkg" --out-dir dist/; \
	done
	@echo "Built $$(ls dist/ | wc -l | tr -d ' ') artifacts in dist/"

# Bump version across all packages. Usage: make bump-version VERSION=0.3.0
bump-version:
	@if [ -z "$(VERSION)" ]; then echo "Usage: make bump-version VERSION=0.3.0"; exit 1; fi
	@find . -name "pyproject.toml" -not -path "*/\.*" -not -path "*/node_modules/*" | while read f; do \
		sed -i '' 's/^version = "0\.[0-9]*\.[0-9]*"/version = "$(VERSION)"/' "$$f"; \
	done
	@echo "Bumped all packages to $(VERSION)"
	@grep -h '^version' apps/cli/pyproject.toml packages/contracts/pyproject.toml

# Full release: test → build → publish to PyPI. Usage: make release VERSION=0.2.0
release: bump-version test build
	@echo ""
	@echo "Ready to publish $(VERSION). Artifacts in dist/:"
	@ls dist/
	@echo ""
	@echo "To publish: UV_PUBLISH_TOKEN=<your-token> uv publish --directory dist/ --index-url https://upload.pypi.org/legacy/"
	@echo "Or set PYPI_TOKEN env var and run: make publish"

# Publish to PyPI (requires PYPI_TOKEN env var)
publish:
	@if [ -z "$(PYPI_TOKEN)" ]; then \
		echo "Set PYPI_TOKEN env var first. See RELEASE.md for token setup."; exit 1; \
	fi
	UV_PUBLISH_TOKEN=$(PYPI_TOKEN) uv publish --directory dist/

clean:
	rm -rf dist/ .pytest_cache/ **/__pycache__/

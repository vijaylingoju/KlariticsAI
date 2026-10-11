FROM python:3.14-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.30 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# uv.lock is committed (make setup writes it); the glob keeps a first build
# working before it exists, at the cost of an unpinned resolution.
COPY pyproject.toml uv.lock* ./
RUN if [ -f uv.lock ]; then uv sync --locked --no-dev --no-install-project; \
    else echo "lockfile: no uv.lock committed, resolving unpinned (run uv lock and commit uv.lock)"; uv sync --no-dev --no-install-project; fi
COPY app ./app
# The event store is synthetic and deterministic (seed 42), so the image builds
# its own copy: same seed, same rows, no data volume to manage.
RUN .venv/bin/python -m app.seed --path data/klaritics.duckdb && mkdir -p data/state

FROM python:3.14-slim-bookworm
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=build --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080 WEB_CONCURRENCY=2 \
    STORE_PATH=/app/data/klaritics.duckdb
USER app
EXPOSE 8080 8090
# gunicorn supervises uvicorn workers (uvicorn-worker is the maintained home
# of UvicornWorker; uvicorn.workers is deprecated). WEB_CONCURRENCY sets the
# worker count; two per CPU is the usual ceiling. `make dev` runs uvicorn
# directly with --reload.
CMD ["gunicorn", "app.main:create_app()", "-k", "uvicorn_worker.UvicornWorker", "--bind", "0.0.0.0:8080", "--access-logfile", "-", "--graceful-timeout", "30", "--timeout", "60"]

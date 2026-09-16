# The engine, for the on-premises VM.
#
# Two stages so the runtime image carries the resolved environment and the source, and
# none of the machinery that produced it. Built on Windows, run on Linux — see
# .gitattributes, without which this image would carry CRLF line endings.
#
#   docker build -t askai-api:local .
#   docker save askai-api:local | gzip > askai-api.tar.gz     # to carry to the VM
#   docker load < askai-api.tar.gz                             # on the VM
#
# Nothing here bakes in the published export or the databases. Both are mounted:
# FR-108 requires republished content to reach readers with no code change and no
# deployment, and a database inside the container layer vanishes on restart.

# ---------------------------------------------------------------------------- build
FROM python:3.13-slim AS build

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# The lockfile alone first, so a source edit does not re-resolve the environment.
# --locked fails rather than silently re-resolving: the image gets exactly what CI and
# the developer machine got, or it does not build.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

# The package, including the rule and message YAML that ships inside it.
COPY src ./src
COPY README.md ./
RUN uv sync --locked --no-dev

# -------------------------------------------------------------------------- runtime
FROM python:3.13-slim AS runtime

# sqlite3 for the preflight's own checks and for operator inspection of the read model.
RUN apt-get update \
    && apt-get install -y --no-install-recommends sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# A service account, and a database directory it owns. Running as root would mean the
# mounted volume ends up root-owned on the host too.
RUN useradd --create-home --uid 10001 askai \
    && mkdir -p /var/lib/askai \
    && chown askai:askai /var/lib/askai

WORKDIR /app
COPY --from=build --chown=askai:askai /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ASKAI_DATABASE_DIR=/var/lib/askai

USER askai

# The read model, record store and index. Mount a host directory here — on local disk,
# never a network mount: WAL does not work over NFS or SMB, and the concurrency design
# depends on it. The preflight below is what proves that on the target filesystem.
VOLUME ["/var/lib/askai"]

EXPOSE 8000

# Story 1.7 as a liveness signal: the store is reachable and the read model's freshness
# is reported. A degraded store shows here rather than as a failed answer.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

# Serving is the default. The other entry points are available by overriding the command:
#
#   ... python -m askai.adapters.store.preflight      the durability check (Story 1.7)
#   ... python -m askai.refresh /data                 ingest the mounted export
#   ... python -m askai.rules                         enumerate the rule catalogue
#
CMD ["uvicorn", "askai.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

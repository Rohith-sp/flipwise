# DT2 (PRD §13.5): one image for the three datacentre services and the coordinator.
# Build:  docker build --build-arg GIT_COMMIT=$(git rev-parse HEAD) -t flipwise:$(git rev-parse --short HEAD) .
FROM python:3.12-slim

# Pinned to the uv version in use when uv.lock was written.
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

# Dependencies first so code edits do not invalidate this layer. README.md is needed because
# pyproject.toml names it as the package readme.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

COPY configs ./configs
COPY tests/fixtures/toy ./tests/fixtures/toy
# The live dashboard's Test results page reads this (PRD §13.6).
COPY docs/test_results/summary.csv ./docs/test_results/summary.csv

# The image has no .git, so the manifest takes the commit from here (experiment._git_commit).
ARG GIT_COMMIT=unknown
ENV FLIPWISE_GIT_COMMIT=$GIT_COMMIT
LABEL org.opencontainers.image.revision=$GIT_COMMIT

# Non-root; /app/results must be writable for the coordinator's bind mount.
RUN useradd --uid 1000 --create-home flipwise && mkdir -p /app/results && chown flipwise /app/results
USER flipwise

ENTRYPOINT ["flipwise"]
CMD ["--help"]

# PersonaLab LangGraph service (crest-graph). Build from the repo root:
#   docker build -f deploy/graph.Dockerfile -t personalab-graph .
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HOSTED=1 \
    PORT=8080 \
    CREST_GRAPH_HOST=0.0.0.0 \
    DATA_DIR=/data \
    FFMPEG_PATH=/usr/bin/ffmpeg \
    VIDEO_FONT_FILE=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf

# config.PROJECT_DIR is two levels above crest_graph/, so the code lives at /app/crest-graph.
WORKDIR /app/crest-graph
COPY crest-graph/pyproject.toml crest-graph/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY crest-graph/crest_graph ./crest_graph

# Runs as root: Railway volumes mount root-owned at /data.
RUN mkdir -p /data
ENV PATH="/app/crest-graph/.venv/bin:$PATH"
EXPOSE 8080
CMD ["python", "-m", "crest_graph.server"]

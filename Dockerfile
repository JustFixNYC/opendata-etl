# SPDX-License-Identifier: AGPL-3.0-only
FROM python:3.12-slim-bookworm

WORKDIR /workspace
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace

RUN apt-get update \
  && apt-get install -y --no-install-recommends curl git \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY pipeline ./pipeline
COPY api ./api
COPY schemas ./schemas
COPY examples ./examples
COPY scripts ./scripts

RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir ".[compose]"

RUN mkdir -p /workspace/data/definitions_work

EXPOSE 3000 8000

# Default is a no-op; compose overrides with dagster dev / uvicorn.
CMD ["python", "-c", "print(\"opendata-etl image; use docker compose up (dagster, api).\")"]

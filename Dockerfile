# SPDX-License-Identifier: AGPL-3.0-only
FROM python:3.12-slim-bookworm

WORKDIR /workspace
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace

COPY . .

# `pip install .` and a production entrypoint will be added in later steps.
CMD ["python", "-c", "print(\"opendata-etl Docker image scaffold; see README.\")"]

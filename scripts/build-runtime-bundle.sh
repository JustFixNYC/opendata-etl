#!/usr/bin/env bash
# Build orchestrator runtime tarball (compose + env template only; no manifests).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${RUNTIME_DIR:-$ROOT/examples/deployment-repo/runtime}"
OUTPUT="${1:-orchestrator-runtime.tar.gz}"

if [[ ! -f "$RUNTIME_DIR/orchestrator-compose.yml" ]]; then
  echo "ERROR: missing $RUNTIME_DIR/orchestrator-compose.yml" >&2
  exit 1
fi

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

cp "$RUNTIME_DIR/orchestrator-compose.yml" "$STAGING/"
cp "$RUNTIME_DIR/env.orchestrator.example" "$STAGING/"

if find "$STAGING" -name 'definitions*.yml' -print -quit | grep -q .; then
  echo "ERROR: definitions manifests must not be packaged in the runtime bundle" >&2
  exit 1
fi

tar -czf "$OUTPUT" -C "$STAGING" .
echo "Wrote $OUTPUT ($(du -h "$OUTPUT" | cut -f1))"

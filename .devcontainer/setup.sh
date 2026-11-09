#!/usr/bin/env bash
# Runs once when the Codespace is created: prepares .env. Everything else runs in containers.
set -euo pipefail

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

# EMBED_MODEL is not stored in the repository (no model ids in the repo). If it was added as a
# Codespaces secret it is filled in automatically; otherwise set it in .env by hand.
if [ -n "${EMBED_MODEL:-}" ] && grep -q '^EMBED_MODEL=$' .env; then
  sed -i "s|^EMBED_MODEL=$|EMBED_MODEL=${EMBED_MODEL}|" .env
  echo "Filled EMBED_MODEL from the Codespaces secret"
fi

if grep -q '^EMBED_MODEL=$' .env; then
  echo
  echo "NEXT: open .env and set EMBED_MODEL (see README section 1), then run: docker compose up --build"
else
  echo
  echo "NEXT: run: docker compose up --build"
fi

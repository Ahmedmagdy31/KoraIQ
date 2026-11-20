#!/usr/bin/env bash
# Zero-drama update: pull, rebuild, migrate (the migrate service runs first), restart.
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d --build
docker image prune -f
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env ps

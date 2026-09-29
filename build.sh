#!/usr/bin/env bash
set -euo pipefail
if [[ ! -f requirements.lock ]]; then
  echo 'Missing requirements.lock. Resolve, audit, test, and commit dependencies before deployment.' >&2
  exit 1
fi
python -m pip install --require-hashes -r requirements.lock
python manage.py collectstatic --noinput
python manage.py check --deploy --fail-level WARNING

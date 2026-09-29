#!/usr/bin/env bash
set -euo pipefail
python manage.py prepare_deploy
# Render's default Gunicorn arguments enable access logs, which can contain
# password-reset URLs. Use the project's own server/logging configuration.
unset GUNICORN_CMD_ARGS
unset INITIAL_OWNER_PASSWORD
exec gunicorn config.wsgi:application --config gunicorn.conf.py

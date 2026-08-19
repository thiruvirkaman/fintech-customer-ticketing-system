#!/bin/sh
set -eu

alembic upgrade head
python -m app.seed_database
exec "$@"

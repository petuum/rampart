#! /usr/bin/env sh

# Copyright 2023 Petuum, Inc. All Rights Reserved.
set -e

MODULE_NAME=${MODULE_NAME:-$DEFAULT_MODULE_NAME}
VARIABLE_NAME=${VARIABLE_NAME:-app}
export APP_MODULE=${APP_MODULE:-"$MODULE_NAME:$VARIABLE_NAME"}

export WORKER_CLASS=${WORKER_CLASS:-"uvicorn.workers.UvicornWorker"}

python run_app.py &

# Start Gunicorn
exec gunicorn -p /tmp/app.pid -k "$WORKER_CLASS" -c "$GUNICORN_CONF" "$APP_MODULE"

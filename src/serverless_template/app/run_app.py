# Copyright 2023 Petuum, Inc. All Rights Reserved.

from flask import Flask
import subprocess
import logging

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)

app = Flask(__name__)


# TODO: Document the implementation in README
@app.route('/restart')
def restart_app():
    # LOG.info('Restarting Gunicorn Master Process')
    with open("/tmp/app.pid", "r") as f:
        app_pid = str(f.read()).split('\n')[0]
    run_args_gunicorn = ["kill", "-HUP", app_pid]
    subprocess.Popen(run_args_gunicorn)
    return "Succesfully Reloaded Server"


@app.route('/install')
def install_dep():
    """
    Install additional dependencies from requirements.txt
    """
    run_args_pip = ["pip", "install", "-r", "requirements.txt"]
    subprocess.Popen(run_args_pip)
    return "Successfully Installed Dependencies"


if __name__ == "__main__":
    app.run(port=80, host="0.0.0.0")

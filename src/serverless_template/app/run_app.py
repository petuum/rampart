# Copyright 2023 Petuum, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License."

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

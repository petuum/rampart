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

import kubernetes_asyncio.client as client
import pathlib

from ..constants import RAMPART_REGISTRY


def init_repo_job_template(pvc_name: str, flow_config: dict, mount_path: str, init_git: bool,
                           init_artifact: bool, init_dvc: bool, link_storage: bool,
                           image_pull_secrets: list = None):
    with pathlib.Path(__file__).parent.joinpath("init_repo.sh").open("rt") as f:
        command = ["sh", "-c", f.read()]
    default_remote_name = "rampart-local" if init_artifact else "rampart-external"
    env = [{"name": "INIT_GIT", "value": "1" if init_git else "0"},
           {"name": "MOUNT_PATH", "value": mount_path},
           {"name": "INIT_ARTIFACT", "value": "1" if init_artifact else "0"},
           {"name": "LINK_STORAGE", "value": "1" if link_storage else "0"},
           {"name": "INIT_DVC", "value": "1" if init_dvc else "0"},
           {"name": "DEFAULT_BRANCH", "value": flow_config.get("defaultBranch", "main")},
           {"name": "STORAGE_REMOTE_NAME", "value": flow_config.get("storageRemoteName",
                                                                    default_remote_name)},
           {"name": "STORAGE_REMOTE", "value": flow_config.get("storageRemote", "")},
           {"name": "USER_NAME", "value": flow_config.get("username", "Rampart")},
           {"name": "USER_EMAIL", "value": flow_config.get("useremail", "rampart@petuum.com")}]
    return client.V1Job(
        metadata=client.V1ObjectMeta(
            generate_name="init-repo-",
        ),
        spec=client.V1JobSpec(
            backoff_limit=3,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(
                    labels={"rampart-disable-edges": "true"}
                ),
                spec=client.V1PodSpec(
                    image_pull_secrets=image_pull_secrets,
                    restart_policy="OnFailure",
                    containers=[client.V1Container(
                        name="main",
                        image=f"{RAMPART_REGISTRY}/dev/dvc:2.9.3",
                        command=command,
                        env=env,
                        volume_mounts=[client.V1VolumeMount(
                            mount_path=mount_path,
                            name="repo-volume"
                        )]
                    )],
                    volumes=[client.V1Volume(
                        name="repo-volume",
                        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                            claim_name=pvc_name, read_only=False
                        )
                    )]
                )
            )
        )
    )

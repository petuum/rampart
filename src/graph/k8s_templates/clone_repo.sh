# Copyright 2023 Petuum, Inc. All Rights Reserved.

set -xe
if [ ! -z "${SSH_PRIVATE_KEY}" ]; then
    git config --global core.sshCommand "ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -i "${SSH_PRIVATE_KEY}""
elif [ ! -z "${CRED_PASSWORD}" ] || [ ! -z "${CRED_USERNAME}" ]; then
    git config --global credential.helper "!f(){ echo username=$(cat "${CRED_USERNAME}"); echo password=$(cat "${CRED_PASSWORD}"); };f"
fi
if [ -z "$(ls -A ${DIR})" ]; then
    git clone ${BRANCH:+-b "${BRANCH}"} "${REPO}" "${DIR}"
fi
cd ${DIR}
if [ ! -z "${USER_NAME}" ]; then
    git config --local user.name "${USER_NAME}"
fi
if [ ! -z "${USER_EMAIL}" ]; then
    git config --local user.email "${USER_EMAIL}"
fi
if [ ! -z "${SSH_PRIVATE_KEY}" ]; then
    git config --local core.sshCommand "ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -i "${SSH_PRIVATE_KEY}""
elif [ ! -z "${CRED_PASSWORD}" ] || [ ! -z "${CRED_USERNAME}" ]; then
    git config --local credential.helper "!f(){ echo username=$(cat "${CRED_USERNAME}"); echo password=$(cat "${CRED_PASSWORD}"); };f"
fi
if [ ! -z "${EXTRA_REMOTE_NAME}" ] && [ ! -z "${EXTRA_REMOTE}" ]; then
    dvc remote add --local "${EXTRA_REMOTE_NAME}" "${EXTRA_REMOTE}"
fi
if [ ! -z "${ACCESS_KEY_ID}" ] && [ ! -z "${SECRET_ACCESS_KEY}" ]; then
    # STORAGE_REMOTE_NAME and EXTRA_REMOTE_NAME may be the same, which is fine because we are just setting the
    # same secret to same remote twice.
    STORAGE_REMOTE_NAME="${STORAGE_REMOTE_NAME:-$(dvc config core.remote)}"
    if [ ! -z "${STORAGE_REMOTE_NAME}" ]; then
        dvc remote modify --local "${STORAGE_REMOTE_NAME}" access_key_id $(cat "${ACCESS_KEY_ID}")
        dvc remote modify --local "${STORAGE_REMOTE_NAME}" secret_access_key $(cat "${SECRET_ACCESS_KEY}")
    fi
    if [ ! -z "${EXTRA_REMOTE_NAME}" ] && [ ! -z "${EXTRA_REMOTE}" ]; then
        dvc remote modify --local "${EXTRA_REMOTE_NAME}" access_key_id $(cat "${ACCESS_KEY_ID}")
        dvc remote modify --local "${EXTRA_REMOTE_NAME}" secret_access_key $(cat "${SECRET_ACCESS_KEY}")
    fi
fi
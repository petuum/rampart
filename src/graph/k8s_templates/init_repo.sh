# Copyright 2023 Petuum, Inc. All Rights Reserved.

set -xe
cd ${MOUNT_PATH}
# DVC uses artifact folder as local storage.
if [ ! -d artifact ] && [ ${INIT_ARTIFACT} = "1" ]; then
    mkdir artifact
fi
# Re-initialize existing volume with same config yields the same results.
# Re-initialize existing volume with different config yields results consistent
# with the latest config, with the following two exceptions:
# 1. "DEFAULT_BRANCH" is defined as "the branch to checkout by default"
# not "the default branch of this repo". `git init` sets it as the repo's default branch
# for convenience only. I.e., repo's default branch is not always determined by
# the "defaultBranch" config, thus will not be updated after the first init.
# 2. DVC meta files will not be removed when changing repo from dvc to git.
if [ ${INIT_GIT} = "1" ]; then
    git config --global user.email ${USER_NAME}
    git config --global user.name ${USER_EMAIL}
    if [ ! -d bare.git ]; then
        git init --bare --shared=all -b ${DEFAULT_BRANCH} bare.git
    fi
    rm -rf bare_clone
    git clone bare.git bare_clone
    cd bare_clone
    # For some unknown reasons remote ref may not be set correctly on an empty clone.
    # Have to create the default branch and set upstream manually when pushing.
    # This behavior seems to be caused by the git version installed.
    git checkout -B ${DEFAULT_BRANCH}
    if [ $(git rev-list --all --count) = "0" ]; then
        git commit --allow-empty -m "initial commit"
    fi
    if [ ${INIT_DVC} = "1" ]; then
        if [ ! -d .dvc ]; then
            dvc init
            git commit -m "initialize dvc"
        fi
        if [ ${LINK_STORAGE} = "1" ]; then
            dvc remote add -f -d "${STORAGE_REMOTE_NAME}" "${STORAGE_REMOTE:-${MOUNT_PATH}/artifact}"
            git add .
            git commit -m "update dvc remote" || true
        fi
    fi
    git push -u origin ${DEFAULT_BRANCH}
fi

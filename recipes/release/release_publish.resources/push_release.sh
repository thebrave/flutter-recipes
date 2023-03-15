#!/bin/bash

# Helper script to run auth and git authenticated commands from the same
# terminal context.

set -ex
gh --version
gh auth login --hostname github.com --git-protocol https --with-token < $TOKEN_PATH
gh auth setup-git
git tag $TAG $RELEASE_GIT_HASH || true
git rev-list -n 1 origin/$GIT_BRANCH
$DRY_RUN_CMD git push origin $TAG || true
$DRY_RUN_CMD git push origin HEAD:$RELEASE_CHANNEL

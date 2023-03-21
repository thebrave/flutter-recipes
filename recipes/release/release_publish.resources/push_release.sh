#!/bin/bash

# Helper script to run auth and git authenticated commands from the same
# terminal context.

set -e
TOKEN=$(cat $TOKEN_PATH)
git checkout $GIT_BRANCH
git branch
git tag $TAG $RELEASE_GIT_HASH || true
git rev-list -n 1 origin/$GIT_BRANCH
git remote set-url origin https://$GITHUB_USER:$TOKEN@github.com/flutter/flutter.git
$DRY_RUN_CMD git push origin $TAG || true
$DRY_RUN_CMD git push origin HEAD:$RELEASE_CHANNEL

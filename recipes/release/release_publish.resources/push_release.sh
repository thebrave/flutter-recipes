#!/bin/bash

# Helper script to run auth and git authenticated commands from the same
# terminal context. Used to tag and push both flutter/flutter & flutter/engine
# in that order.

set -e
TOKEN=$(cat $TOKEN_PATH)
git checkout $GIT_BRANCH
git branch
if [ $REPO == 'flutter' ]
then
  echo 'using tag' $REL_HASH
  git tag $TAG $REL_HASH || true
elif [ $REPO == 'engine' ]
then
  echo 'using tag' $(<../flutter/bin/internal/engine.version)
  git tag $TAG $(<../flutter/bin/internal/engine.version) || true
fi
git remote set-url origin https://$GITHUB_USER:$TOKEN@github.com/flutter/$REPO.git
$DRY_RUN_CMD git push origin $TAG || true
$DRY_RUN_CMD git push origin HEAD:$RELEASE_CHANNEL

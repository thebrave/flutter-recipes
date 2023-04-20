#!/bin/bash

# Helper script to run auth and git authenticated commands from the same
# terminal context. Used to tag and push both flutter/flutter & flutter/engine
# in that order.

set -e
TOKEN=$(cat $TOKEN_PATH)
git checkout $GIT_BRANCH
git branch
echo "##### TAGGING #####"
git tag $TAG $REL_HASH || true
git remote set-url origin https://$GITHUB_USER:$TOKEN@github.com/flutter/$REPO.git
git push origin $TAG || true
if [ $REPO == 'flutter' ]
then
  echo "##### PUSHING TO $RELEASE_CHANNEL #####"
  git push origin HEAD:$RELEASE_CHANNEL $FORCE_FLAG
fi

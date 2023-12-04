#!/bin/bash

# Helper script to run auth and git authenticated commands from the same
# terminal context. Used to tag and push both flutter/flutter & flutter/engine
# in that order.

set -e
TOKEN=$(cat $TOKEN_PATH)
git checkout $GIT_BRANCH
git branch
echo "##### TAGGING #####"
if [ -z $FORCE_FLAG ]; then
  git tag $TAG $REL_HASH
else
  # Ignore exit code if this is being forced
  git tag $TAG $REL_HASH || true
fi
git remote set-url origin https://$GITHUB_USER:$TOKEN@github.com/flutter/$REPO.git
git push origin $TAG || true
if [ $REPO == 'flutter' ]
then
  echo "##### PUSHING TO $RELEASE_CHANNEL #####"
  git push origin $REL_HASH:$RELEASE_CHANNEL $FORCE_FLAG
fi

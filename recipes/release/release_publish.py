# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re

DEPS = [
    'flutter/repo_util',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/runtime',
    'recipe_engine/step',
]

stableTagRegex = r'^(\d+)\.(\d+)\.(\d+)$'
betaTagRegex = r'^(\d+)\.(\d+)\.(\d+)-(\d+)\.(\d+)\.pre$'

def isValidTag(tag):
  stable = re.search(stableTagRegex, tag)
  development = re.search(betaTagRegex, tag)
  return stable or development

"""
This recipe executes the tag and publishing stages of a flutter release.
To trigger this recipe, tool proxy must be invoked with multi-party approval.
Tool proxy information can be found at go/tool-proxy.
Because of this configuration, the recipe is triggered manually during the
release process.

It is expected that a valid release branch, tag, and release_channel are passed
to the recipe.
"""
def RunSteps(api):
  branch = api.properties.get('branch')
  tag = api.properties.get("tag")
  release_channel = api.properties.get("release_channel")
  assert branch and tag and release_channel

  checkout_path = api.path['start_dir'].join('flutter')
  git_url = api.properties.get('git_url') or 'https://flutter.googlesource.com/mirrors/flutter'

  # Validate the given tag is correctly formatted for either stable or latest
  assert isValidTag(tag)

  # This recipe should only be executed on linux or mac machines to
  # guard against Windows git issues
  assert api.platform.is_linux or api.platform.is_mac

  with api.step.nest('checkout release branch'):
    release_git_hash = api.repo_util.checkout(
        'flutter',
        checkout_path=checkout_path,
        url=git_url,
        ref="refs/heads/%s" % branch,
    )

  with api.step.nest('tag release'):
    step_args = ['git tag', tag, release_git_hash]
    api.step('Add tag to release hash', step_args)

  # Guard tag from being pushed on experimental runs
  if not api.runtime.is_experimental:
    with api.step.nest('push tags to upstream'):
      step_args = ['git push origin', tag]
      api.step('Push tag to origin', step_args)

    with api.step.nest('publish version'):
      api.step('Push release to refs/heads/%s' % release_channel, step_args)


def GenTests(api):
    for tag in ('1.2.3-4.5.pre', '1.2.3'):
      for release_channel in ('stable', 'beta'):
        test = api.test(
            '%s%s%s' % (
                'flutter-1.2-candidate.3',
                tag,
                release_channel
            ), api.platform('mac', 64),
            api.properties(
                branch='flutter-1.2-candidate.3',
                tag=tag,
                release_channel=release_channel
            ), api.repo_util.flutter_environment_data()
        )
        yield test

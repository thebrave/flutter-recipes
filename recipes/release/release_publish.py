# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re

DEPS = [
    'flutter/flutter_deps',
    'flutter/kms',
    'flutter/repo_util',
    'fuchsia/git',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
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

The recipe will tag and push to github unless triggered 
from an experimental run.
"""
def RunSteps(api):
  branch = api.properties.get('branch')
  tag = api.properties.get("tag")
  release_channel = api.properties.get("release_channel")
  assert branch and tag and release_channel

  checkout_path = api.path['start_dir'].join('flutter')
  git_url = 'https://github.com/flutter/flutter'

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

  env, env_prefixes = api.repo_util.flutter_environment(checkout_path)
  api.flutter_deps.required_deps(
      env,
      env_prefixes,
      api.properties.get('dependencies', []),
  )

  # install gh cli
  api.flutter_deps.gh_cli(env, env_prefixes, 'latest')

  with api.context(env=env, env_prefixes=env_prefixes, cwd=checkout_path):
    token_decrypted = api.path['cleanup'].join('token.txt')
    api.kms.get_secret('flutter-release-github-token.encrypted', token_decrypted)

    token_txt = api.file.read_text('Read token', token_decrypted, include_log=False)
    api.step(
        'authenticating using gh cli',
        ['gh', 'auth', 'login', '--hostname', 'github.com', '--git-protocol',
         'https','--with-token'],
        stdin=api.raw_io.input_text(data=token_txt))

    api.git('tag release', 'tag', tag, release_git_hash)

    # Guard tag from being pushed on experimental runs
    if not api.runtime.is_experimental:
      api.git('push release to refs/heads/%s' % release_channel, 'push', 'origin', tag)


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

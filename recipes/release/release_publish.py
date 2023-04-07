# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re
from recipe_engine import post_process

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

It is expected that a valid release git branch, tag, and release_channel are passed
to the recipe.

The recipe will tag and push to github unless triggered
from an experimental run.
"""
def RunSteps(api):
  git_branch = api.properties.get('git_branch')
  tag = api.properties.get('tag')
  release_channel = api.properties.get('release_channel')
  # default to True dry run
  dry_run = api.runtime.is_experimental or api.properties.get('dry_run')=='True'
  assert git_branch and tag and release_channel

  checkout_path = api.path['start_dir'].join('flutter')
  flutter_git_url = 'https://github.com/flutter/flutter'
  engine_git_url = 'https://github.com/flutter/engine'

  # Validate the given tag is correctly formatted for either stable or latest
  assert isValidTag(tag)

  # This recipe should only be executed on linux or mac machines to
  # guard against Windows git issues
  assert api.platform.is_linux or api.platform.is_mac

  with api.step.nest('checkout flutter release branch'):
    rel_hash = api.repo_util.checkout(
      'flutter',
      api.path['start_dir'].join('flutter'),
      url=flutter_git_url,
      ref="refs/heads/%s" % git_branch,
    )
  with api.step.nest('checkout engine release branch'):
    api.repo_util.checkout(
      'engine',
      api.path['start_dir'].join('engine'),
      url=engine_git_url,
      ref='refs/heads/%s' % git_branch,
    )

  env_flutter, env_flutter_prefixes = api.repo_util.flutter_environment(checkout_path)
  env_engine, env_engine_prefixes = api.repo_util.engine_environment(checkout_path)
  api.flutter_deps.required_deps(
      env_flutter,
      env_flutter_prefixes,
      api.properties.get('dependencies', []),
  )
  api.flutter_deps.required_deps(
      env_engine,
      env_engine_prefixes,
      api.properties.get('dependencies', []),
  )

  resource_name = api.resource('push_release.sh')
  api.step(
      'Set execute permission',
      ['chmod', '755', resource_name],
      infra_step=True,
  )

  for repo in ('flutter', 'engine'):
    if repo=='flutter':
        env = env_flutter
        env_prefixes=env_flutter_prefixes
    else:
        env = env_engine
        env_prefixes=env_engine_prefixes
    with api.context(env=env, env_prefixes=env_prefixes, cwd=checkout_path):
      token_decrypted = api.path['cleanup'].join('token.txt')
      api.kms.get_secret('flutter-release-github-token.encrypted', token_decrypted)

      env['DRY_RUN_CMD'] = 'echo' if dry_run else ''
      env['TOKEN_PATH'] = token_decrypted
      env['TAG'] = tag
      env['REL_HASH'] = rel_hash
      env['RELEASE_CHANNEL'] = release_channel
      env['GIT_BRANCH'] = git_branch
      env['GITHUB_USER'] = 'fluttergithubbot'
      env['REPO'] = 'flutter' if repo=='flutter' else 'engine'

      # Run script within a new context to use the new env variables.
      # Tag and push flutter/flutter first, then use hash found in
      # bin/internal/engine.version to tag and push engine next
      with api.context(env=env, env_prefixes=env_prefixes):
        api.step('Tag and push release on flutter/%s' % repo, [resource_name])


def GenTests(api):
    checkout_path = api.path['start_dir'].join('flutter')
    for tag in ('1.2.3-4.5.pre', '1.2.3'):
      for release_channel in ('stable', 'beta'):
        for dry_run in ('True', 'False'):
          test = api.test(
              '%s_%s_%s%s' % (
                  'flutter-2.8-candidate.9',
                  tag,
                  release_channel,
                  '_dry_run' if dry_run=='True' else ''
              ), api.platform('mac', 64),
              api.properties(
                  git_branch='flutter-2.8-candidate.9',
                  tag=tag,
                  release_channel=release_channel,
                  dry_run=dry_run
              ),
              api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
              api.post_process(post_process.MustRun,
                'Tag and push release on flutter/flutter'),
              api.post_process(post_process.MustRun,
                'Tag and push release on flutter/engine'),
              api.post_process(post_process.StatusSuccess),
          )
          yield test

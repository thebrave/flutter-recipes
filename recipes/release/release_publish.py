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


def isValidTag(tag, release_channel):
  stable = re.search(stableTagRegex, tag)
  beta = re.search(betaTagRegex, tag)
  if release_channel == 'stable':
    return stable
  return beta


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
  # default to False force push
  force = False if api.runtime.is_experimental else api.properties.get(
      'force', False
  )
  assert git_branch and tag and release_channel in ('stable', 'beta')

  checkout = api.path.start_dir / 'flutter'

  # Validate the given tag is correctly formatted for either stable or latest
  assert isValidTag(tag, release_channel)

  # This recipe is only able to be triggered on linux, and the other platforms
  # are not necessary
  assert api.platform.is_linux

  with api.step.nest('checkout flutter release branch'):
    rel_hash = api.repo_util.checkout(
        'flutter',
        checkout,
        url='https://github.com/flutter/flutter',
        ref="refs/heads/%s" % git_branch,
    )

  env, env_prefixes = api.repo_util.flutter_environment(
      checkout
  )

  api.flutter_deps.required_deps(
      env,
      env_prefixes,
      api.properties.get('dependencies', []),
  )

  resource_name = api.resource('push_release.sh')
  api.step(
      'Set execute permission',
      ['chmod', '755', resource_name],
      infra_step=True,
  )

  repos = ('flutter',)

  for repo in repos:
    with api.context(env=env, env_prefixes=env_prefixes, cwd=checkout):
      token_decrypted = api.path.cleanup_dir / 'token.txt'
      api.kms.get_secret(
          # TODO(fujino): restore this to 'flutter-release-github-token.encrypted'
          # once https://github.com/flutter/flutter/issues/162544 is resolved
          'pub-roller-github-token.encrypted', token_decrypted
      )

      env['FORCE_FLAG'] = '--force' if force else ''
      env['TOKEN_PATH'] = token_decrypted
      env['TAG'] = tag
      env['REL_HASH'] = rel_hash
      env['RELEASE_CHANNEL'] = release_channel
      env['GIT_BRANCH'] = git_branch
      # TODO(fujino) restore this to 'fluttergithubbot' once
      # https://github.com/flutter/flutter/issues/162544 is resolved
      env['GITHUB_USER'] = 'flutter-pub-roller-bot'
      env['REPO'] = 'flutter' if repo == 'flutter' else 'engine'

      # Run script within a new context to use the new env variables.
      # Tag and push flutter/flutter first, then use hash found in
      # bin/internal/engine.version to tag and push engine next
      with api.context(env=env, env_prefixes=env_prefixes):
        api.step('Tag and push release on flutter/%s' % repo, [resource_name])


def GenTests(api):
  checkout_path = api.path.start_dir / 'flutter'

  for tag in ('1.2.3-4.5.pre', '1.2.3'):
    for release_channel in ('stable', 'beta'):
      for force in ('True', 'False'):
        if ((tag == '1.2.3-4.5.pre' and release_channel == 'stable') or
            (tag == '1.2.3' and release_channel == 'beta')):
          # These are invalid combinations of tag and release_channel.
          # Expect assertion errors for these combinations
          post_processing = [
              api.expect_exception('AssertionError'),
              # Different versions of Python have different assertion tracebacks
              # See https://flutter-review.googlesource.com/c/recipes/+/59721.
              api.post_process(post_process.DropExpectation),
          ]
        else:
          # Remaining tag combinations of tag and release channel are valid.
          post_processing = [
              api.post_process(
                  post_process.MustRun,
                  'Tag and push release on flutter/flutter'
              ),
              api.post_process(post_process.StatusSuccess)
          ]
        yield api.test(
            'monorepo_%s_%s%s' %
            (tag, release_channel, '_force' if force == 'True' else ''),
            api.platform('linux', 64),
            api.properties(
                git_branch='flutter-2.8-candidate.9',
                tag=tag,
                release_channel=release_channel,
                force=force,
            ),
            api.path.dirs_exist(api.path.start_dir / 'flutter' / 'engine',),
            api.repo_util.flutter_environment_data(
                checkout_dir=checkout_path
            ),
            *post_processing,
        )

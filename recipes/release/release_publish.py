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

ENGINE_VERSION_FILE = '/bin/internal/engine.version'


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
  # TODO(fujino): delete this once monorepo reaches stable
  is_monorepo = False
  git_branch = api.properties.get('git_branch')
  tag = api.properties.get('tag')
  release_channel = api.properties.get('release_channel')
  # default to False force push
  force = False if api.runtime.is_experimental else api.properties.get(
      'force', False
  )
  assert git_branch and tag and release_channel in ('stable', 'beta')

  flutter_checkout = api.path.start_dir / 'flutter'
  engine_checkout = api.path.start_dir / 'engine'
  flutter_git_url = 'https://github.com/flutter/flutter'
  engine_git_url = 'https://github.com/flutter/engine'

  # Validate the given tag is correctly formatted for either stable or latest
  assert isValidTag(tag, release_channel)

  # This recipe is only able to be triggered on linux, and the other platforms
  # are not necessary
  assert api.platform.is_linux

  with api.step.nest('checkout flutter release branch'):
    flutter_rel_hash = api.repo_util.checkout(
        'flutter',
        flutter_checkout,
        url=flutter_git_url,
        ref="refs/heads/%s" % git_branch,
    )

  env_flutter, env_flutter_prefixes = api.repo_util.flutter_environment(
      flutter_checkout
  )
  if api.path.exists(flutter_checkout / 'engine'):
    is_monorepo = True
    env_engine = {}
    env_engine_prefixes = {}
  else:
    with api.step.nest('checkout engine release branch'):
      engine_tot = api.repo_util.checkout(
          'engine',
          api.path.start_dir / 'engine',
          url=engine_git_url,
          ref='refs/heads/%s' % git_branch,
      )
      env_engine, env_engine_prefixes = api.repo_util.engine_environment(
          engine_checkout
      )

  api.flutter_deps.required_deps(
      env_flutter,
      env_flutter_prefixes,
      api.properties.get('dependencies', []),
  )

  if not is_monorepo:
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

  engine_version = GetEngineVersion(api, flutter_checkout)
  if not is_monorepo:
    engine_tot = '' if api.repo_util._test_data.enabled else engine_tot
    if engine_tot != engine_version:  # pragma: no cover
      api.step(
          '(Warning) engine.version in flutter sdk does not match engine ToT',
          []
      )

  if is_monorepo:
    repos = ('flutter',)
  else:
    repos = ('flutter', 'engine')

  for repo in repos:
    env = env_flutter if repo == 'flutter' else env_engine
    env_prefixes = env_flutter_prefixes if repo == 'flutter' else env_engine_prefixes
    checkout = flutter_checkout if repo == 'flutter' else engine_checkout
    rel_hash = flutter_rel_hash if repo == 'flutter' else engine_version

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


def GetEngineVersion(api, flutter_checkout):
  return api.file.read_text(
      'read engine hash',
      str(flutter_checkout) + ENGINE_VERSION_FILE
  ).strip()


def GenTests(api):
  checkout_path = api.path.start_dir / 'flutter'

  for tag in ('1.2.3-4.5.pre', '1.2.3'):
    for release_channel in ('stable', 'beta'):
      for force in ('True', 'False'):
        for is_monorepo in (True, False):
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
            if not is_monorepo:
              post_processing.append(
                  api.post_process(
                      post_process.MustRun,
                      'Tag and push release on flutter/engine'
                  )
              )
          if is_monorepo:
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
          else:
            yield api.test(
                'non-monorepo_%s_%s%s' %
                (tag, release_channel, '_force' if force == 'True' else ''),
                api.platform('linux', 64),
                api.properties(
                    git_branch='flutter-2.8-candidate.9',
                    tag=tag,
                    release_channel=release_channel,
                    force=force
                ),
                api.repo_util.flutter_environment_data(
                    checkout_dir=checkout_path
                ),
                *post_processing,
            )

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
  with api.step.nest('validate platform and properties'):
    if not api.platform.is_linux:
      raise api.step.StepFailure('Must be run on a Linux platform')

    git_branch = api.properties.get('git_branch')
    if not git_branch:
      raise api.step.StepFailure('Missing property "git_branch"')

    tag = api.properties.get('tag')
    if not tag:
      raise api.step.StepFailure('Missing property "tag"')

    release_channel = api.properties.get('release_channel')
    if not release_channel:
      raise api.step.StepFailure('Missing property "release_channel"')
    if release_channel not in ('stable', 'beta'):
      raise api.step.StepFailure(
          'Unexpected "release_channel" value: {release_channel}'.format(
              release_channel=release_channel,
          )
      )
    if not isValidTag(tag, release_channel):
      raise api.step.StepFailure(
          'Cannot use tag {tag} on channel {release_channel}'.format(
              tag=tag,
              release_channel=release_channel,
          )
      )

    force = False if api.runtime.is_experimental else api.properties.get(
        'force', False
    )

  checkout = api.path.start_dir / 'flutter'
  with api.step.nest('checkout flutter release branch'):
    rel_hash = api.repo_util.checkout(
        'flutter',
        checkout,
        url='https://github.com/flutter/flutter',
        ref="refs/heads/%s" % git_branch,
    )

  # LINT: The `bin/internal/engine.version` file:
  # 1. Must exist
  # 2. Should match the SHA emitted by `bin/internal/last_engine_commit.sh
  with api.step.nest('validate engine.version'):
    engine_version = checkout / 'bin' / 'internal' / 'engine.version'
    if not api.path.exists(engine_version):
      raise api.step.StepFailure(
          'Missing expected file: {engine_version}'.format(
              engine_version=engine_version,
          )
      )

    last_engine_script = checkout / 'bin' / 'internal' / 'last_engine_commit.sh'
    if not api.path.exists(last_engine_script):
      raise api.step.StepFailure(
          'Missing expected file: {last_engine_script}'.format(
              last_engine_script=last_engine_script,
          )
      )

    last_commit_step = api.step(
        'compute last engine commit',
        cmd=[
            'bash',
            last_engine_script,
        ],
        stdout=api.raw_io.output_text(),
    )
    last_commit_sha = last_commit_step.stdout.strip()

    engine_version_step = api.step(
        'read engine.version file',
        cmd=[
            'cat',
            engine_version,
        ],
        stdout=api.raw_io.output_text()
    )
    engine_version_content = engine_version_step.stdout.strip()
    if last_commit_sha != engine_version_content:
      raise api.step.StepFailure(
          'Contents of {engine_version}: "{engine_version_content}" do not match expected last engine commit "{last_commit_sha}"'
          .format(
              engine_version=engine_version,
              engine_version_content=engine_version_content,
              last_commit_sha=last_commit_sha,
          )
      )

  env, env_prefixes = api.repo_util.flutter_environment(checkout)

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

  with api.context(env=env, env_prefixes=env_prefixes, cwd=checkout):
    token_decrypted = api.path.cleanup_dir / 'token.txt'
    api.kms.get_secret(
        # TODO(fujino): restore this to 'flutter-release-github-token.encrypted'
        # once https://github.com/flutter/flutter/issues/162544 is resolved
        'pub-roller-github-token.encrypted',
        token_decrypted
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
    env['REPO'] = 'flutter'

    # Run script within a new context to use the new env variables.
    # Tag and push flutter/flutter first, then use hash found in
    # bin/internal/engine.version to tag and push engine next
    with api.context(env=env, env_prefixes=env_prefixes):
      api.step('Tag and push release on flutter/flutter', [resource_name])


def GenTests(api):
  checkout_path = api.path.start_dir / 'flutter'

  # TEST: Must be a linux platform
  yield api.test(
      'unsupported_platform',
      api.platform('mac', 64),
      api.properties(
          git_branch='flutter-1.2.3-candidate.0',
          tag='3.32.0-0.3',
          release_channel='gamma',
      ),
      status="FAILURE",
  )

  # TEST: Cannot use an unexpected channel name
  yield api.test(
      'unexpected_release_channel',
      api.platform('linux', 64),
      api.properties(
          git_branch='flutter-1.2.3-candidate.0',
          tag='3.32.0-0.3',
          release_channel='gamma',
      ),
      status="FAILURE",
  )

  # TEST: Cannot have a missing git_branch
  yield api.test(
      'missing_git_branch',
      api.platform('linux', 64),
      api.properties(
          tag='3.32.0-0.3',
          release_channel='stable',
      ),
      status="FAILURE",
  )

  # TEST: Cannot have a missing tag
  yield api.test(
      'missing_tag',
      api.platform('linux', 64),
      api.properties(
          git_branch='flutter-1.2.3-candidate.0',
          release_channel='stable',
      ),
      status="FAILURE",
  )

  # TEST: Cannot have a missing tag
  yield api.test(
      'missing_channel',
      api.platform('linux', 64),
      api.properties(
          git_branch='flutter-1.2.3-candidate.0',
          tag='3.32.0-0.3',
      ),
      status="FAILURE",
  )

  # TEST: Cannot use a .pre tag on the stable channel
  yield api.test(
      'unexpected_pre_tag_on_stable_channel',
      api.platform('linux', 64),
      api.properties(
          git_branch='flutter-1.2.3-candidate.0',
          tag='3.32.0-0.3',
          release_channel='stable',
          force=False,
      ),
      status="FAILURE",
  )

  # TEST: Must be using a .pre tag on the beta channel
  yield api.test(
      'unexpected_non_pre_tag_on_beta_channel',
      api.platform('linux', 64),
      api.properties(
          git_branch='flutter-1.2.3-candidate.0',
          tag='3.29.3',
          release_channel='beta',
          force=False,
      ),
      status="FAILURE",
  )

  # TEST: Must have an engine.version file.
  yield api.test(
      'missing_engine.version',
      api.platform('linux', 64),
      api.properties(
          git_branch='flutter-1.2.3-candidate.0',
          tag='3.32.0-0.3.pre',
          release_channel='beta',
          force=False,
      ),
      status='FAILURE',
  )

  # TEST: Must have bin/internal/last_engine_commit.sh
  yield api.test(
      'missing_last_engine_commit.sh',
      api.platform('linux', 64),
      api.properties(
          git_branch='flutter-1.2.3-candidate.0',
          tag='3.32.0-0.3.pre',
          release_channel='beta',
          force=False,
      ),
      api.path.exists(checkout_path / 'bin' / 'internal' / 'engine.version',),
      status='FAILURE',
  )

  # TEST: The commit in engine.version is of out date compared to the source tree.
  yield api.test(
      'out_of_date_engine.version',
      api.platform('linux', 64),
      api.properties(
          git_branch='flutter-1.2.3-candidate.0',
          tag='3.32.0-0.3.pre',
          release_channel='beta',
          force=False,
      ),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.path.exists(
          checkout_path / 'bin' / 'internal' / 'engine.version',
          checkout_path / 'bin' / 'internal' / 'last_engine_commit.sh',
      ),
      api.step_data(
          'validate engine.version.compute last engine commit',
          stdout=api.raw_io.output_text('\tdef456\t'),
      ),
      api.step_data(
          'validate engine.version.read engine.version file',
          stdout=api.raw_io.output_text('\tabc123\t'),
      ),
      status='FAILURE',
  )

  # TEST: "Successful" run.
  yield api.test(
      'success',
      api.platform('linux', 64),
      api.properties(
          git_branch='flutter-1.2.3-candidate.0',
          tag='3.32.0-0.3.pre',
          release_channel='beta',
          force=False,
      ),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.path.exists(
          checkout_path / 'bin' / 'internal' / 'engine.version',
          checkout_path / 'bin' / 'internal' / 'last_engine_commit.sh',
      ),
      api.step_data(
          'validate engine.version.compute last engine commit',
          stdout=api.raw_io.output_text('\tabc123\t'),
      ),
      api.step_data(
          'validate engine.version.read engine.version file',
          stdout=api.raw_io.output_text('\tabc123\t'),
      ),
  )

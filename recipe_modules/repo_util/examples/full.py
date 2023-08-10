# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/monorepo',
    'flutter/repo_util',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
]


def RunSteps(api):
  flutter_checkout_path = api.path['start_dir'].join('flutter')
  api.repo_util.get_branch(flutter_checkout_path)
  api.repo_util.is_release_candidate_branch(flutter_checkout_path)
  api.repo_util.release_candidate_branch(flutter_checkout_path)
  api.repo_util.checkout(
      'flutter', flutter_checkout_path, ref='refs/heads/master'
  )
  api.repo_util.checkout(
      'engine', api.path['start_dir'].join('engine'), ref='refs/heads/main'
  )
  api.repo_util.checkout(
      'cocoon', api.path['start_dir'].join('cocoon'), ref='refs/heads/main'
  )
  api.repo_util.checkout(
      'packages', api.path['start_dir'].join('packages'), ref='refs/heads/main'
  )
  # we need an override because all of the previous step calls on checkout directly overrides the ref variable
  api.repo_util.checkout(
      'flutter', flutter_checkout_path, ref='refs/heads/beta'
  )
  api.repo_util.get_env_ref()

  env, env_paths = api.repo_util.engine_environment(flutter_checkout_path)
  env, env_paths = api.repo_util.monorepo_environment(flutter_checkout_path)
  env, env_paths = api.repo_util.flutter_environment(flutter_checkout_path)
  api.repo_util.in_release_and_main(flutter_checkout_path)
  checkout_path = api.path['start_dir']
  if api.monorepo.is_monorepo_ci_build or api.monorepo.is_monorepo_try_build:
    api.file.ensure_directory('ensure directory', checkout_path)
    api.repo_util.monorepo_checkout(checkout_path, {}, {})
  else:
    api.file.ensure_directory('ensure directory', checkout_path.join('engine'))
    api.repo_util.engine_checkout(checkout_path.join('engine'), {}, {})
  with api.context(env=env, env_prefixes=env_paths):
    api.repo_util.sdk_checkout_path()


def GenTests(api):
  yield (
      api.test(
          'basic',
          api.properties(
              git_branch='beta',
              gn_artifacts='true',
              git_url='https://github.com/flutter/engine',
              git_ref='refs/pull/1/head',
              clobber=True,
              package_sharding='shard1',
              channel='stable',
          ), api.repo_util.flutter_environment_data(),
          api.step_data(
              'Identify branches.git rev-parse',
              stdout=api.raw_io.output_text('abchash')
          ),
          api.step_data(
              'Identify branches.git branch',
              stdout=api.raw_io.output_text(
                  'branch1\nbranch2\nremotes/origin/flutter-3.2-candidate.5'
              )
          ),
          api.step_data(
              'Identify branches (2).git branch',
              stdout=api.raw_io.output_text(
                  'branch1\nbranch2\nremotes/origin/flutter-3.2-candidate.5'
              )
          ),
          api.step_data(
              'Identify branches (3).git branch',
              stdout=api.raw_io.output_text(
                  'branch1\nbranch2\nremotes/origin/flutter-3.2-candidate.5'
              )
          ),
          api.platform('mac', 64)
      )
  )
  yield api.test(
      'failed_flutter_environment',
      api.properties(
          git_url='https://github.com/flutter/engine',
          git_ref='refs/pull/1/head'
      ),
      status='FAILURE'
  )
  yield api.test(
      'monorepo_release', api.repo_util.flutter_environment_data(),
      api.properties(git_branch='beta', clobber=True),
      api.monorepo.ci_build(git_ref='refs/heads/beta'),
      api.platform('mac', 64)
  )
  yield api.test(
      'monorepo', api.repo_util.flutter_environment_data(),
      api.monorepo.ci_build()
  )
  yield api.test(
      'monorepo_tryjob', api.repo_util.flutter_environment_data(),
      api.properties(clobber=True), api.monorepo.try_build()
  )
  yield api.test(
      'monorepo_wrong_host', api.repo_util.flutter_environment_data(),
      api.buildbucket.ci_build(
          git_repo='https://not-dart.googlesource.com/monorepo',
          git_ref='refs/heads/main'
      ), api.expect_exception('ValueError')
  )
  yield api.test(
      'monorepo_first_bot_update_failed',
      api.repo_util.flutter_environment_data(),
      api.properties(clobber=True),
      api.monorepo.ci_build(),
      # Next line force a fail condition for the bot update
      # first execution.
      api.step_data("Checkout source code.bot_update", retcode=1)
  )
  yield (
      api.test(
          'bot_update',
          api.properties(
              git_url='https://github.com/flutter/engine',
              git_ref='refs/pull/1/head'
          )
      ) + api.repo_util.flutter_environment_data()
  )
  yield api.test(
      'first_bot_update_failed',
      api.properties(
          git_url='https://github.com/flutter/engine',
          git_ref='refs/pull/1/head'
      ),
      # Next line force a fail condition for the bot update
      # first execution.
      api.step_data("Checkout source code.bot_update", retcode=1),
      api.repo_util.flutter_environment_data()
  )
  yield api.test(
      'first_bot_update_revision_not_found',
      api.properties(
          git_url='https://github.com/flutter/engine',
          git_ref='refs/pull/1/head'
      ),
      # Next line force a fail condition for the bot update
      # first execution.
      api.path.exists(
          api.path['cache'].join('git'), api.path['start_dir'].join('engine')
      ),
      api.override_step_data(
          "Checkout source code.bot_update",
          api.json.output({
              'properties': {'got_revision': 'BOT_UPDATE_NO_REV_FOUND'}
          }),
          retcode=0
      ),
      api.repo_util.flutter_environment_data()
  )

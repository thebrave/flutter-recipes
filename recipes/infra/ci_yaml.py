# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for updating flutter/infra with ci.yaml changes."""

from PB.go.chromium.org.luci.common.proto.gerrit import gerrit as gerrit_pb2

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'flutter/repo_util',
    'fuchsia/auto_roller',
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

def _is_postsubmit(api):
  """Returns True if the current build is not in try, otherwise False."""
  return api.buildbucket.build.builder.bucket != 'try'


def _is_default_branch(branch):
  """Returns True if branch is master or main."""
  return branch in ("main", "master")

def RunSteps(api):
  """Steps to checkout infra, dependencies, and generate new config."""
  start_path = api.path['start_dir']
  cocoon_path = start_path.join('cocoon')
  flutter_path = start_path.join('flutter')
  infra_path = start_path.join('infra')

  # Checkout the stable version of Flutter.
  flutter_git_ref = 'refs/heads/master'
  api.repo_util.checkout('flutter', flutter_path, ref=flutter_git_ref)

  # Checkout latest version of flutter/cocoon.
  api.repo_util.checkout(
      'cocoon',
      cocoon_path,
      ref='refs/heads/main'
  )

  # Checkout latest version of flutter/infra
  api.repo_util.checkout(
      'infra',
      infra_path,
      ref='refs/heads/main'
  )

  # Install protoc to compile latest scheduler.proto
  protoc_path = start_path.join('protoc')
  api.cipd.ensure(
      protoc_path,
      api.cipd.EnsureFile().add_package(
          'infra/3pp/tools/protoc/${platform}', 'version:2@3.17.3'
      )
  )

  git_branch = api.properties.get('git_branch')
  repo = api.properties.get('git_repo')
  if _is_postsubmit(api):
    # gitiles commit info
    git_ref = api.buildbucket.gitiles_commit.id
  else:
    # github pull request info
    git_ref = 'main' # Default to master for LED runs
    for tag in api.buildbucket.build.tags:
      if 'sha/git/' in tag.value:
          git_ref = tag.value.replace('sha/git/', '')

  # The context adds dart-sdk tools to PATH and sets PUB_CACHE.
  env, env_prefixes = api.repo_util.flutter_environment(flutter_path)
  with api.context(env=env, env_prefixes=env_prefixes, cwd=cocoon_path.join('app_dart')):
    api.step('flutter doctor', cmd=['flutter', 'doctor'])
    api.step('dart pub get', cmd=['dart', 'pub', 'get'])
    generate_jspb_path = cocoon_path.join('app_dart', 'bin', 'generate_jspb.dart')
    config_name = '%s_config.json' % repo
    if git_branch and not _is_default_branch(git_branch):
      config_name = '%s_%s_config.json' % (repo, git_branch)
    infra_config_path = infra_path.join('config', 'generated', 'ci_yaml', config_name)
    # Generate_jspb
    jspb_step = api.step('generate jspb',
        cmd=['dart', generate_jspb_path, repo, git_ref],
        stdout=api.raw_io.output_text(), stderr=api.raw_io.output_text())
    api.file.write_raw('write jspb', infra_config_path, jspb_step.stdout)

  # Roll scheduler.proto
  with api.context(env_prefixes={'PATH': [protoc_path.join('bin')]}):
    scheduler_proto_src = cocoon_path.join('app_dart', 'lib', 'src', 'model',
        'proto', 'internal', 'scheduler.proto')
    scheduler_proto_dst = infra_path.join('config', 'lib', 'ci_yaml')
    api.step('Roll scheduler.proto', ['cp', scheduler_proto_src, scheduler_proto_dst])
    api.step('Compile scheduler.proto', ['bash', scheduler_proto_dst.join('compile_proto.sh')])

  with api.context(cwd=infra_path):
    # Generate luci configs
    api.step('luci generate', cmd=['lucicfg', 'generate', 'config/main.star'])
    # Validate luci configs
    api.step('luci validate', cmd=['lucicfg', 'validate', 'config/main.star'])
    # Only send rolls on postsubmit
    if _is_postsubmit(api):
        api.auto_roller.attempt_roll(
            api.auto_roller.Options(
                remote = 'https://flutter.googlesource.com/infra',
                cc_on_failure_emails = ['flutter-infra@grotations.appspotmail.com'],
                labels_to_set = {'Commit-Queue': 2},
                bot_commit = True,
            ),
            repo_dir = infra_path,
            commit_message = 'Roll %s to %s' % (repo, git_ref),
        )


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.ci_build(
          bucket='prod',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          revision = 'abc123'
      ),
      api.properties(
          git_branch='main',
          git_repo='engine'
      ),
      api.repo_util.flutter_environment_data(
          api.path['start_dir'].join('flutter')
      ),
      api.step_data('generate jspb', stdout=api.raw_io.output_text('{"hello": "world"}')),
      api.auto_roller.success()
  )
  yield api.test(
      'release',
      api.buildbucket.ci_build(
          bucket='prod',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          revision = 'abc123'
      ),
      api.properties(
          git_branch='dev',
          git_repo='engine'
      ),
      api.repo_util.flutter_environment_data(
          api.path['start_dir'].join('flutter')
      ),
      api.step_data('generate jspb', stdout=api.raw_io.output_text('{"hello": "world"}')),
      api.auto_roller.success()
  )
  yield api.test(
      'staging',
      api.buildbucket.ci_build(
          bucket='staging',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          revision = 'abc123'
      ),
      api.properties(
          git_branch='main',
          git_repo='engine'
      ),
      api.repo_util.flutter_environment_data(
          api.path['start_dir'].join('flutter')
      ),
      api.step_data('generate jspb', stdout=api.raw_io.output_text('{"hello": "world"}')),
      api.auto_roller.success()
  )
  yield api.test(
      'presubmit',
      api.buildbucket.try_build(
          bucket='try',
          tags=api.buildbucket.tags(
              buildset=['sha/git/def123', 'sha/pr/1']
          )
      ),
      api.properties(
          git_repo='engine'
      ),
      api.repo_util.flutter_environment_data(
          api.path['start_dir'].join('flutter')
      ),
  )

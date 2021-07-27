# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for updating flutter/infra with ci.yaml changes."""

from PB.go.chromium.org.luci.common.proto.gerrit import gerrit as gerrit_pb2

DEPS = [
    'fuchsia/auto_roller',
    'fuchsia/cl_util',
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/runtime',
    'recipe_engine/step',
    'repo_util',
]


def RunSteps(api):
  """Steps to checkout infra, dependencies, and generate new config."""
  start_path = api.path['start_dir']
  cocoon_path = start_path.join('cocoon')
  flutter_path = start_path.join('flutter')
  infra_path = start_path.join('infra')

  # Checkout the stable version of Flutter.
  flutter_git_ref = 'refs/heads/stable'
  api.repo_util.checkout('flutter', flutter_path, ref=flutter_git_ref)

  # Checkout latest version of flutter/cocoon.
  api.repo_util.checkout(
      'cocoon',
      cocoon_path,
      ref='refs/heads/master'
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

  # gitiles commit info
  commit_sha = api.buildbucket.gitiles_commit.id
  gitiles_repo = api.buildbucket.gitiles_commit.project
  repo = gitiles_repo.split("/")[-1]

  # The context adds dart-sdk tools to PATH and sets PUB_CACHE.
  env, env_prefixes = api.repo_util.flutter_environment(flutter_path)
  with api.context(env=env, env_prefixes=env_prefixes, cwd=cocoon_path.join('app_dart')):
    api.step('flutter doctor', cmd=['flutter', 'doctor'])
    api.step('pub get', cmd=['pub', 'get'])
    generate_jspb_path = cocoon_path.join('app_dart', 'bin', 'generate_jspb.dart')
    infra_config_path = infra_path.join('config', '%s_config.json' % repo)
    # Generate_jspb
    jspb_step = api.step('generate jspb', cmd=['dart', generate_jspb_path, repo, commit_sha], stdout=api.raw_io.output_text(), stderr=api.raw_io.output_text())
    api.file.write_raw('write jspb', infra_config_path, jspb_step.stdout)

# Roll scheduler.proto
  with api.context(env_prefixes={'PATH': [protoc_path.join('bin')]}):
    scheduler_proto_src = cocoon_path.join('app_dart', 'lib', 'src', 'model', 'proto', 'internal', 'scheduler.proto')
    scheduler_proto_dst = infra_path.join('config', 'lib', 'ci_yaml')
    api.step('Roll scheduler.proto', ['cp', scheduler_proto_src, scheduler_proto_dst])
    api.step('Compile scheduler.proto', ['bash', scheduler_proto_dst.join('compile_proto.sh')])

  with api.context(cwd=infra_path):
    # Generate luci configs
    api.step('luci generate', cmd=['lucicfg', 'generate', 'config/main.star'])
    change = api.auto_roller.attempt_roll(
        gerrit_host = 'flutter-review.googlesource.com',
        gerrit_project = 'infra',
        repo_dir = infra_path,
        commit_message = 'Roll %s to %s' % (repo, commit_sha),
        # TODO(chillers): Change to oncall group. https://github.com/flutter/flutter/issues/86945
        cc_on_failure = 'chillers@google.com',
    )
    return api.auto_roller.raw_result(change)


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.ci_build(
          git_repo='https://chromium.googlesource.com/external/github.com/flutter/engine',
          revision = 'abc123'
      ),
      api.repo_util.flutter_environment_data(
          api.path['start_dir'].join('flutter')
      ),
      api.step_data('generate jspb', stdout=api.raw_io.output_text('{"hello": "world"}')),
      api.auto_roller.success()
  )

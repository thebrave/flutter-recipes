# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for updating flutter/infra with ci.yaml changes."""

DEPS = [
    'recipe_engine/buildbucket',
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

  # CHeckout latest version of flutter/cocoon.
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

  # The context adds dart-sdk tools to PATH and sets PUB_CACHE.
  env, env_prefixes = api.repo_util.flutter_environment(flutter_path)
  with api.context(env=env, env_prefixes=env_prefixes, cwd=start_path):
    api.step('flutter doctor', cmd=['flutter', 'doctor'])
    generate_jspb_path = cocoon_path.join('app_dart', 'bin', 'generate_jspb.dart')
    # gitiles commit info
    ref = api.buildbucket.gitiles_commit.id
    gitiles_repo = api.buildbucket.gitiles_commit.project
    repo = gitiles_repo.split("/")[-1]
    infra_config_path = infra_path.join('config', '%s_config.json' % repo)
    # Generate_jspb
    jspb_step = api.step('generate jspb', cmd=['dart', generate_jspb_path, repo, ref], stdout=api.raw_io.output_text(), stderr=api.raw_io.output_text())
    api.file.write_raw('write jspb', infra_config_path, jspb_step.stdout)
  with api.context(cwd=infra_path):
    # Generate luci configs
    api.step('luci generate', cmd=['lucicfg', 'generate', 'config/main.star'])
    api.step('git diff', cmd=['git', 'diff'])


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.ci_build(
          git_repo='https://chromium.googlesource.com/external/github.com/flutter/engine'
      ),
      api.repo_util.flutter_environment_data(
          api.path['start_dir'].join('flutter')
      ),
      api.step_data('generate jspb', stdout=api.raw_io.output_text('{"hello": "world"}'))
  )

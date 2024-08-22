# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.post_process import DoesNotRun, Filter, StatusFailure

from RECIPE_MODULES.flutter.archives.api import ArchivePaths

DEPS = [
    'flutter/archives',
    'flutter/monorepo',
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
]


def RunSteps(api):
  checkout = api.path['start_dir']
  if api.monorepo.is_monorepo:
    checkout = checkout / 'monorepo'
  checkout = checkout / 'src'
  archives = [{
      "source": "out/debug/artifacts.zip",
      "destination": "ios/artifacts.zip",
      "realm": "production"
  }, {
      "source": "out/release-nobitcode/Flutter.dSYM.zip",
      "destination": "ios-release-nobitcode/Flutter.dSYM.zip",
      "realm": "production"
  }, {
      "source": "out/release/Flutter.dSYM.zip",
      "destination": "ios-release/Flutter.dSYM.zip"
  }]
  expected_results = [
      ArchivePaths(
          local=str(api.path['start_dir'].join('src/out/debug/artifacts.zip')),
          remote='gs://flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/ios/artifacts.zip'
      ),
      ArchivePaths(
          local=str(
              api.path['start_dir']
              .join('src/out/release-nobitcode/Flutter.dSYM.zip')
          ),
          remote='gs://flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/ios-release-nobitcode/Flutter.dSYM.zip'
      ),
      ArchivePaths(
          local=str(
              api.path['start_dir'].join('src/out/release/Flutter.dSYM.zip')
          ),
          remote='gs://flutter_archives_v2/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/ios-release/Flutter.dSYM.zip'
      )
  ]
  expected_results_flutter = [
      ArchivePaths(
          local=str(api.path['start_dir'].join('src/out/debug/artifacts.zip')),
          remote='gs://flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/ios/artifacts.zip'
      ),
      ArchivePaths(
          local=str(
              api.path['start_dir']
              .join('src/out/release-nobitcode/Flutter.dSYM.zip')
          ),
          remote='gs://flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/ios-release-nobitcode/Flutter.dSYM.zip'
      ),
      ArchivePaths(
          local=str(
              api.path['start_dir'].join('src/out/release/Flutter.dSYM.zip')
          ),
          remote='gs://flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/ios-release/Flutter.dSYM.zip'
      )
  ]
  expected_monorepo_results = [
      ArchivePaths(
          local=str(api.path['start_dir'].join('monorepo/src/out/debug/artifacts.zip')),
          remote='gs://flutter_archives_v2/monorepo/123/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/ios/artifacts.zip'
      ),
      ArchivePaths(
          local=str(
              api.path['start_dir']
              .join('monorepo/src/out/release-nobitcode/Flutter.dSYM.zip')
          ),
          remote='gs://flutter_archives_v2/monorepo/123/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/ios-release-nobitcode/Flutter.dSYM.zip'
      ),
      ArchivePaths(
          local=str(
              api.path['start_dir'].join('monorepo/src/out/release/Flutter.dSYM.zip')
          ),
          remote='gs://flutter_archives_v2/monorepo/123/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/ios-release/Flutter.dSYM.zip'
      )
  ]
  expected_monorepo_try_results = [
      ArchivePaths(
          local=str(api.path['start_dir'].join('monorepo/src/out/debug/artifacts.zip')),
          remote='gs://flutter_archives_v2/monorepo_try/123/flutter_infra_release/flutter/123/ios/artifacts.zip'
      ),
      ArchivePaths(
          local=str(
              api.path['start_dir']
              .join('monorepo/src/out/release-nobitcode/Flutter.dSYM.zip')
          ),
          remote='gs://flutter_archives_v2/monorepo_try/123/flutter_infra_release/flutter/123/ios-release-nobitcode/Flutter.dSYM.zip'
      ),
      ArchivePaths(
          local=str(
              api.path['start_dir'].join('monorepo/src/out/release/Flutter.dSYM.zip')
          ),
          remote='gs://flutter_archives_v2/monorepo_try/123/flutter_infra_release/flutter/123/ios-release/Flutter.dSYM.zip'
      )
  ]
  expected_try_results = [
      ArchivePaths(
          local=str(api.path['start_dir'].join('src/out/debug/artifacts.zip')),
          remote='gs://flutter_archives_v2/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/ios/artifacts.zip'
      ),
      ArchivePaths(
          local=str(
              api.path['start_dir']
              .join('src/out/release-nobitcode/Flutter.dSYM.zip')
          ),
          remote='gs://flutter_archives_v2/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/ios-release-nobitcode/Flutter.dSYM.zip'
      ),
      ArchivePaths(
          local=str(
              api.path['start_dir'].join('src/out/release/Flutter.dSYM.zip')
          ),
          remote='gs://flutter_archives_v2/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/ios-release/Flutter.dSYM.zip'
      )
  ]
  env_to_results = {
      'production': expected_results,
      'monorepo': expected_monorepo_results,
      'monorepo_try': expected_monorepo_try_results,
      'try': expected_try_results,
      'flutter': expected_results_flutter
  }
  config = api.properties.get('config')
  results = api.archives.global_generator_paths(checkout, archives)
  api.assertions.assertListEqual(env_to_results.get(config), results)


def GenTests(api):
  yield api.test(
      'prod', api.properties(config='production'),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='prod',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main',
          build_id=98765
      ),
      api.step_data(
          'git rev-parse',
          stdout=api.raw_io
          .output_text('12345abcde12345abcde12345abcde12345abcde\n')
      )
  )
  yield api.test(
      'flutter', api.properties(config='flutter'),
      api.buildbucket.ci_build(
          project='dart-internal',
          bucket='flutter',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main',
          build_id=98765
      ),
      api.step_data(
          'git rev-parse',
          stdout=api.raw_io
          .output_text('12345abcde12345abcde12345abcde12345abcde\n')
      )
  )
  yield api.test(
      'monorepo_ci',
      api.properties(config='monorepo'),
      api.monorepo.ci_build(),
  )
  yield api.test(
      'monorepo_try',
      api.properties(config='monorepo_try'),
      api.monorepo.try_build(build_id=123),
  )
  yield api.test(
      'try', api.properties(config='try'),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='try',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main',
          build_id=98765
      ),
      api.step_data(
          'git rev-parse',
          stdout=api.raw_io
          .output_text('12345abcde12345abcde12345abcde12345abcde\n')
      )
  )

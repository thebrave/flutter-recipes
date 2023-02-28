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
    'recipe_engine/raw_io',
]


def RunSteps(api):
  checkout = api.path['start_dir']
  config = {
      "name": "android_profile",
      "type": "gcs",
      "base_path": "out/android_profile/zip_archives/",
      "realm": "production",
      "include_paths": [
          "out/android_profile/zip_archives/artifact1.zip",
          "out/android_profile/zip_archives/android-arm-profile/artifacts.zip",
          "out/android_profile/zip_archives/android-arm-profile/linux-x64.zip",
          "out/android_profile/zip_archives/android-arm-profile/symbols.zip",
          "out/android_profile/zip_archives/download.flutter.io"
      ]
  }
  results = api.archives.engine_v2_gcs_paths(checkout, config)
  expected_results = [
      ArchivePaths(
          local=str(api.path['start_dir'].join('out/android_profile/zip_archives/artifact1.zip')),
          remote='gs://flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/artifact1.zip'
      ),
      ArchivePaths(
          local=str(api.path['start_dir'].join('out/android_profile/zip_archives/android-arm-profile/artifacts.zip')),
          remote='gs://flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/android-arm-profile/artifacts.zip'),
      ArchivePaths(
          local=str(api.path['start_dir'].join('out/android_profile/zip_archives/android-arm-profile/linux-x64.zip')),
          remote='gs://flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/android-arm-profile/linux-x64.zip'),
      ArchivePaths(
          local=str(api.path['start_dir'].join('out/android_profile/zip_archives/android-arm-profile/symbols.zip')),
          remote='gs://flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/android-arm-profile/symbols.zip'),
      ArchivePaths(
          local=str(api.path['start_dir'].join('out/android_profile/zip_archives/download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.jar')),
          remote='gs://download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.jar'),
      ArchivePaths(
          local=str(api.path['start_dir'].join('out/android_profile/zip_archives/download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.pom')),
          remote='gs://download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.pom')
  ]
  api.assertions.assertListEqual(expected_results, results)


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.ci_build(
          project='flutter',
          bucket='prod',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main'
      ),
      api.step_data(
          'git rev-parse',
          stdout=api.raw_io
          .output_text('12345abcde12345abcde12345abcde12345abcde\n')
      )
  )

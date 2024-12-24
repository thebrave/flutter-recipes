# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy
from recipe_engine.post_process import DoesNotRun, Filter, StatusException

DEPS = [
    'flutter/archives',
    'flutter/monorepo',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
]


def RunSteps(api):
  if api.monorepo.is_monorepo:
    checkout = api.path.start_dir / "flutter" / "engine" / "src"
  else:
    checkout = api.path.start_dir
  config = api.properties.get('config')
  expected_destinations = api.properties.get('expected_destinations')
  results = api.archives.engine_v2_gcs_paths(checkout, config)
  for result in results:
    found = result.remote in expected_destinations
    assert found, 'Unexpected file generated %s' % result.remote
  if results:
    api.archives.upload_artifact(results[0].local, results[0].remote)
    api.archives.download(results[0].remote, results[0].local)


def GenTests(api):
  archive_config = {
      "name":
          "android_profile",
      "type":
          "gcs",
      "realm":
          "production",
      "base_path":
          "out/android_profile/zip_archives/",
      "include_paths": [
          "out/android_profile/zip_archives/android-arm-profile/artifacts.zip",
          "out/android_profile/zip_archives/android-arm-profile/linux-x64.zip",
          "out/android_profile/zip_archives/android-arm-profile/symbols.zip",
          "out/android_profile/zip_archives/download.flutter.io"
      ]
  }

  archive_monorepo_config = {
      "name":
          "android_profile",
      "type":
          "gcs",
      "realm":
          "production",
      "base_path":
          "flutter/engine/src/out/android_profile/zip_archives/",
      "include_paths": [
          "flutter/engine/src/out/android_profile/zip_archives/android-arm-profile/artifacts.zip",
          "flutter/engine/src/out/android_profile/zip_archives/android-arm-profile/linux-x64.zip",
          "flutter/engine/src/out/android_profile/zip_archives/android-arm-profile/symbols.zip",
      ]
  }

  # Try LUCI pool with "production" realm in build configuration file.
  try_pool_production_realm = [
      'gs://flutter_archives_v2/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/android-arm-profile/artifacts.zip',
      'gs://flutter_archives_v2/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/android-arm-profile/linux-x64.zip',
      'gs://flutter_archives_v2/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/android-arm-profile/symbols.zip',
      'gs://flutter_archives_v2/download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.jar',
      'gs://flutter_archives_v2/download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.pom'
  ]
  yield api.test(
      'try_pool_production_realm',
      api.properties(
          config=archive_config,
          expected_destinations=try_pool_production_realm
      ),
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

  # Try LUCI pool with "experimental" realm in build configuration file.
  try_pool_experimental_realm = try_pool_production_realm
  try_pool_experimental_realm_config = copy.deepcopy(archive_config)
  try_pool_experimental_realm_config['realm'] = 'experimental'
  yield api.test(
      'try_pool_experimental_realm',
      api.properties(
          config=try_pool_experimental_realm_config,
          expected_destinations=try_pool_experimental_realm
      ),
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

  # Try shadow LUCI pool with "production" realm in build configuration file.
  try_pool_shadow_bucket_production_realm = try_pool_production_realm
  yield api.test(
      'try_pool_shadow_bucket_production_realm',
      api.properties(
          config=archive_config,
          expected_destinations=try_pool_shadow_bucket_production_realm
      ),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='try.shadow',
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

  # Try shadow LUCI pool with "experimental" realm in build configuration file.
  try_pool_shadow_bucket_experimental_realm = try_pool_production_realm
  try_pool_shadow_bucket_experimental_realm_config = copy.deepcopy(
      archive_config
  )
  try_pool_shadow_bucket_experimental_realm_config['realm'] = 'experimental'
  yield api.test(
      'try_pool_shadow_bucket_experimental_realm',
      api.properties(
          config=try_pool_shadow_bucket_experimental_realm_config,
          expected_destinations=try_pool_shadow_bucket_experimental_realm
      ),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='try.shadow',
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

  # Prod LUCI pool with "production" realm in build configuration file.
  prod_pool_production_realm = [
      'gs://flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/android-arm-profile/artifacts.zip',
      'gs://flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/android-arm-profile/linux-x64.zip',
      'gs://flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/android-arm-profile/symbols.zip',
      'gs://download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.jar',
      'gs://download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.pom'
  ]
  yield api.test(
      'prod_pool_production_realm',
      api.properties(
          config=archive_config,
          expected_destinations=prod_pool_production_realm
      ),
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

  # Prod LUCI pool with "experimental" realm in build configuration file.
  prod_pool_experimental_realm = try_pool_production_realm
  prod_pool_experimental_realm_config = copy.deepcopy(archive_config)
  prod_pool_experimental_realm_config['realm'] = 'experimental'
  yield api.test(
      'prod_pool_experimental_realm',
      api.properties(
          config=prod_pool_experimental_realm_config,
          expected_destinations=prod_pool_experimental_realm
      ),
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

  # Prod shadow LUCI pool with "production" realm in build configuration file.
  prod_pool_shadow_bucket_production_realm = try_pool_production_realm
  yield api.test(
      'prod_pool_shadow_bucket_production_realm',
      api.properties(
          config=archive_config,
          expected_destinations=prod_pool_shadow_bucket_production_realm
      ),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='try.shadow',
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

  # Prod shadow LUCI pool with "experimental" realm in build configuration file.
  prod_pool_shadow_bucket_experimental_realm = try_pool_production_realm
  prod_pool_shadow_bucket_experimental_realm_config = copy.deepcopy(
      archive_config
  )
  prod_pool_shadow_bucket_experimental_realm_config['realm'] = 'experimental'
  yield api.test(
      'prod_pool_shadow_bucket_experimental_realm',
      api.properties(
          config=prod_pool_shadow_bucket_experimental_realm_config,
          expected_destinations=prod_pool_shadow_bucket_experimental_realm
      ),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='try.shadow',
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

  # Flutter LUCI pool with "production" realm in build configuration file.
  flutter_pool_production_realm = prod_pool_production_realm
  yield api.test(
      'flutter_pool_production_realm',
      api.properties(
          config=archive_config,
          expected_destinations=flutter_pool_production_realm
      ),
      api.buildbucket.ci_build(
          project='dart-internal',
          bucket='flutter',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main'
      ),
      api.step_data(
          'git rev-parse',
          stdout=api.raw_io
          .output_text('12345abcde12345abcde12345abcde12345abcde\n')
      )
  )

  # Flutter LUCI pool with "experimental" realm in build configuration file.
  flutter_pool_production_realm = prod_pool_production_realm
  flutter_pool_experimental_realm_config = copy.deepcopy(archive_config)
  flutter_pool_experimental_realm_config['realm'] = 'experimental'
  yield api.test(
      'flutter_pool_experimental_realm',
      api.properties(
          config=flutter_pool_experimental_realm_config,
          expected_destinations=flutter_pool_production_realm
      ),
      api.buildbucket.ci_build(
          project='dart-internal',
          bucket='flutter',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main'
      ),
      api.step_data(
          'git rev-parse',
          stdout=api.raw_io
          .output_text('12345abcde12345abcde12345abcde12345abcde\n')
      )
  )

  # Staging LUCI pool with "production" realm in build configuration file.
  staging_pool_production_realm = try_pool_production_realm
  yield api.test(
      'staging_pool_production_realm',
      api.properties(
          config=archive_config,
          expected_destinations=staging_pool_production_realm
      ),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='staging',
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

  # Staging LUCI pool with "production" realm in build configuration file.
  staging_pool_production_realm = try_pool_production_realm
  staging_pool_experimental_realm_config = copy.deepcopy(archive_config)
  staging_pool_experimental_realm_config['realm'] = 'experimental'
  yield api.test(
      'staging_pool_experimental_realm',
      api.properties(
          config=staging_pool_experimental_realm_config,
          expected_destinations=staging_pool_production_realm
      ),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='staging',
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

  # Staging shadow LUCI pool with "production" realm in build configuration file.
  staging_pool_shadow_bucket_production_realm = try_pool_production_realm
  yield api.test(
      'staging_pool_shadow_bucket_production_realm',
      api.properties(
          config=archive_config,
          expected_destinations=staging_pool_shadow_bucket_production_realm
      ),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='staging.shadow',
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

  # Staging shadow LUCI pool with "experimental" realm in build configuration file.
  staging_pool_shadow_bucket_experimental_realm = try_pool_production_realm
  staging_pool_shadow_bucket_experimental_realm_config = copy.deepcopy(
      archive_config
  )
  staging_pool_shadow_bucket_experimental_realm_config['realm'] = 'experimental'
  yield api.test(
      'staging_pool_shadow_bucket_experimental_realm',
      api.properties(
          config=staging_pool_shadow_bucket_experimental_realm_config,
          expected_destinations=staging_pool_shadow_bucket_experimental_realm
      ),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='staging.shadow',
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

  # Monorepo ci  with "production" realm in build configuration file.
  monorepo_production_realm = [
      'gs://flutter_archives_v2/monorepo/123/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/android-arm-profile/artifacts.zip',
      'gs://flutter_archives_v2/monorepo/123/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/android-arm-profile/linux-x64.zip',
      'gs://flutter_archives_v2/monorepo/123/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/android-arm-profile/symbols.zip',
      'gs://flutter_archives_v2/monorepo/123/download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.jar',
      'gs://flutter_archives_v2/monorepo/123/download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.pom'
  ]
  yield api.test(
      'monorepo_ci', api.monorepo.ci_build(),
      api.properties(
          config=archive_monorepo_config,
          expected_destinations=monorepo_production_realm
      ),
      api.step_data(
          'git rev-parse',
          stdout=api.raw_io
          .output_text('12345abcde12345abcde12345abcde12345abcde\n')
      )
  )

  # Monorepo ci  with "experimental" realm in build configuration file.
  monorepo_experimental_realm_config = copy.deepcopy(archive_monorepo_config)
  monorepo_experimental_realm_config['realm'] = 'experimental'
  monorepo_experimental_realm = [
      'gs://flutter_archives_v2/monorepo/123/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/android-arm-profile/artifacts.zip',
      'gs://flutter_archives_v2/monorepo/123/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/android-arm-profile/linux-x64.zip',
      'gs://flutter_archives_v2/monorepo/123/flutter_infra_release/flutter/12345abcde12345abcde12345abcde12345abcde/android-arm-profile/symbols.zip',
      'gs://flutter_archives_v2/monorepo/123/download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.jar',
      'gs://flutter_archives_v2/monorepo/123/download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.pom'
  ]
  yield api.test(
      'monorepo_ci_experimental_realm', api.monorepo.ci_build(),
      api.properties(
          config=monorepo_experimental_realm_config,
          expected_destinations=monorepo_experimental_realm
      ),
      api.step_data(
          'git rev-parse',
          stdout=api.raw_io
          .output_text('12345abcde12345abcde12345abcde12345abcde\n')
      )
  )

  # Monorepo try with "production" realm in build configuration file.
  monorepo_try_production_realm = [
      'gs://flutter_archives_v2/monorepo_try/123/flutter_infra_release/flutter/123/android-arm-profile/artifacts.zip',
      'gs://flutter_archives_v2/monorepo_try/123/flutter_infra_release/flutter/123/android-arm-profile/linux-x64.zip',
      'gs://flutter_archives_v2/monorepo_try/123/flutter_infra_release/flutter/123/android-arm-profile/symbols.zip',
      'gs://flutter_archives_v2/monorepo_try/123/download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.jar',
      'gs://flutter_archives_v2/monorepo_try/123/download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.pom'
  ]
  yield api.test(
      'monorepo_try_production_realm',
      api.properties(
          config=archive_monorepo_config,
          expected_destinations=monorepo_try_production_realm,
      ),
      api.monorepo.try_build(build_id=123),
  )

  # Monorepo try with "experimental" realm in build configuration file.
  monorepo_try_experimental_realm = [
      'gs://flutter_archives_v2/monorepo_try/123/flutter_infra_release/flutter/123/android-arm-profile/artifacts.zip',
      'gs://flutter_archives_v2/monorepo_try/123/flutter_infra_release/flutter/123/android-arm-profile/linux-x64.zip',
      'gs://flutter_archives_v2/monorepo_try/123/flutter_infra_release/flutter/123/android-arm-profile/symbols.zip',
      'gs://flutter_archives_v2/monorepo_try/123/download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.jar',
      'gs://flutter_archives_v2/monorepo_try/123/download.flutter.io/io/flutter/x86_debug/1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.pom'
  ]
  monorepo_experimental_realm_config = copy.deepcopy(archive_monorepo_config)
  monorepo_experimental_realm_config['realm'] = 'experimental'
  yield api.test(
      'monorepo_try_experimental_realm',
      api.properties(
          config=monorepo_experimental_realm_config,
          expected_destinations=monorepo_try_experimental_realm,
      ),
      api.monorepo.try_build(build_id=123),
  )

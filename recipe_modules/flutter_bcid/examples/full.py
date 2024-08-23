# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/flutter_bcid',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/raw_io',
]


def RunSteps(api):
  api.flutter_bcid.report_stage('one')
  api.flutter_bcid.upload_provenance(
      api.path.cache_dir / 'file.zip', 'gs://bucket/final_path/file.txt'
  )
  api.flutter_bcid.is_official_build()
  api.flutter_bcid.is_prod_build()
  api.flutter_bcid.is_try_build()
  api.flutter_bcid.download_and_verify_provenance(
      "artifact.zip", "flutter_infra", "release_artifacts/artifacts.zip"
  )


def GenTests(api):
  fake_bcid_response_success = '{"allowed": true, "verificationSummary": "This artifact is definitely legitimate!"}'
  artifacts_location = 'artifact.zip'
  yield api.test(
      'basic',
      api.buildbucket.ci_build(
          project='dart-internal',
          bucket='flutter',
          git_repo='https://dart.googlesource.com/monorepo',
          git_ref='refs/heads/main'
      ),
      api.step_data(
          'Verify artifact.zip provenance.verify artifact.zip provenance',
          stdout=api.raw_io.output_text(fake_bcid_response_success)
      ),
  )

  yield api.test(
      'prod_build',
      api.buildbucket.ci_build(
          project='dart-internal',
          bucket='flutter',
          git_repo='https://dart.googlesource.com/monorepo',
          git_ref='refs/heads/main'
      ),
      api.step_data(
          'Verify artifact.zip provenance.verify artifact.zip provenance',
          stdout=api.raw_io.output_text(fake_bcid_response_success)
      ),
  )

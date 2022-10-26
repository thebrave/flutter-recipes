# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/flutter_bcid',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
]


def RunSteps(api):
  api.flutter_bcid.report_stage('one')
  api.flutter_bcid.upload_provenance(
      api.path['cache'].join('file.zip'),
      'gs://bucket/final_path/file.txt'
  )


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.ci_build(
          project='dart-internal',
          bucket='flutter',
          git_repo='https://dart.googlesource.com/monorepo',
          git_ref='refs/heads/main'
      ),
  )

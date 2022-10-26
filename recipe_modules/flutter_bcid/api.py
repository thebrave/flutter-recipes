# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re
from recipe_engine import recipe_api


class FlutterBcidApi(recipe_api.RecipeApi):

  def _is_official_build(self):
    bucket = self.m.buildbucket.build.builder.bucket
    # No-op for builders running outside of dart-internal.
    return bucket == 'flutter'

  def report_stage(self, stage):
    if self._is_official_build():
      self.m.bcid_reporter.report_stage(stage)

  def upload_provenance(self, local_artifact_path, remote_artifact_path):
    if self._is_official_build():
      sha256 = self.m.file.file_hash(local_artifact_path)
      self.m.bcid_reporter.report_gcs(
          sha256,
          remote_artifact_path
      )


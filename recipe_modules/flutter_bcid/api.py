# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re
from enum import Enum

from recipe_engine import recipe_api


class BcidStage(Enum):
  """Enum representing valid bcis stages."""
  START='start'
  FETCH='fetch'
  COMPILE='compile'
  UPLOAD='upload'
  UPLOAD_COMPLETE='upload-complete'
  TEST='test'


class FlutterBcidApi(recipe_api.RecipeApi):

  def _is_official_build(self):
    bucket = self.m.buildbucket.build.builder.bucket
    # No-op for builders running outside of dart-internal.
    return bucket == 'flutter'

  def report_stage(self, stage):
    if self._is_official_build():
      self.m.bcid_reporter.report_stage(stage)

  def upload_provenance(self, local_artifact_path, remote_artifact_path):
    """Generate provenance for given artifact.

    This function acts on one specific local file and one specific
    remote file location. It does not accept glob patterns or
    directories.

    parmeters:
      local_artifact_path: (str) path and filename of a specific file.
      remote_artifact_path: (str) path and filename of a specific file.
    """
    if (self._is_official_build() and 
      # TODO(jseales): Uncomment next line after windows
      # can generate provenance succesfully
      # https://github.com/flutter/flutter/issues/116749
      not self.m.platform.is_win):
      sha256 = self.m.file.file_hash(local_artifact_path)
      self.m.bcid_reporter.report_gcs(
          sha256,
          remote_artifact_path
      )


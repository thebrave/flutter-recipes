# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re
from enum import Enum

from recipe_engine import recipe_api


class BcidStage(Enum):
  """Enum representing valid bcis stages."""
  START = 'start'
  FETCH = 'fetch'
  COMPILE = 'compile'
  UPLOAD = 'upload'
  UPLOAD_COMPLETE = 'upload-complete'
  TEST = 'test'


VSA_EXTENSION = ".vsa.intoto.jsonl"


class FlutterBcidApi(recipe_api.RecipeApi):

  def is_official_build(self):
    bucket = self.m.buildbucket.build.builder.bucket
    # No-op for builders running outside of dart-internal.
    return bucket == 'flutter'

  def is_prod_build(self):
    bucket = self.m.buildbucket.build.builder.bucket
    return bucket in ('prod', 'prod.shadow')

  def is_try_build(self):
    bucket = self.m.buildbucket.build.builder.bucket
    return bucket in ('try', 'try.shadow')

  def report_stage(self, stage):
    if self.is_official_build():
      self.m.bcid_reporter.report_stage(stage)

  def upload_provenance(self, local_artifact_path, remote_artifact_path):
    """Generate provenance for given artifact.

    This function acts on one specific local file and one specific remote file
    location. It does not accept glob patterns or directories. This method is a
    noop if it is not an official build, as only official builds generate
    provenance.

    parmeters:
      local_artifact_path: (str) path and filename of a specific file.
      remote_artifact_path: (str) path and filename of a specific file.
    """
    if self.is_official_build():
      sha256 = self.m.file.file_hash(local_artifact_path)
      self.m.bcid_reporter.report_gcs(sha256, remote_artifact_path)

  def download_and_verify_provenance(
      self, filename, bucket, gcs_path_without_bucket
  ):
    """Downloads and verifies provenance for a specified artifact.

    This method downloads an artifact and associated provenance from GCS,
    verifies it. If verification fails, an error is raised. This method is a
    noop if it is not an official build, as only official builds generate
    provenance.

    parameters:
      filename: (str) the name of the file, eg: "flutter_artifact.zip"
      bucket: (str) the GCS bucket, eg: "flutter_infra_release"
      gcs_path_without_bucket: (str) the GCS path, excluding gs://{bucket}/
        eg: "flutter/004d0bdf6721bc65cdb9a558908b2de4cfac97c5/sky_engine.zip"
    """
    if self.is_official_build():
      with self.m.step.nest("Verify %s provenance" % filename):
        verify_temp_path = self.m.path.mkdtemp("verify")
        download_path = download_path = verify_temp_path.join(filename)
        bcid_response = self.m.dart.download_and_verify(
            filename, bucket, gcs_path_without_bucket, download_path,
            'misc_software://flutter/engine'
        )

        artifact_vsa = bcid_response['verificationSummary']
        vsa_local_path = f'{download_path}{VSA_EXTENSION}'
        self.m.file.write_text(
            f'write {filename}{VSA_EXTENSION}', vsa_local_path, artifact_vsa
        )
        vsa_path_without_bucket = gcs_path_without_bucket + VSA_EXTENSION
        self.m.gsutil.upload(
            vsa_local_path,
            bucket,
            vsa_path_without_bucket,
            name=f'upload "{vsa_path_without_bucket}"',
        )

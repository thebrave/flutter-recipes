# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    "fuchsia/buildbucket_util",
    "flutter/gsutil",
    "recipe_engine/path",
    "recipe_engine/platform",
]

BUCKET = "example"


def RunSteps(api):
  api.gsutil.upload_namespaced_file(
      BUCKET,
      api.path.cleanup_dir.join("file"),
      api.gsutil.join("path", "to", "file"),
      metadata={
          "Test-Field": "value",
          "Remove-Me": None,
          "x-custom-field": "custom-value",
          "Cache-Control": "no-cache",
      },
      unauthenticated_url=True,
      options={"parallel_composite_upload_threshold": "50M"},
  )

  api.gsutil.upload_namespaced_directory(
      api.path.cleanup_dir.join("dir"),
      BUCKET,
      "rsync_subpath",
      gzip_exts=["html"],
  )
  api.gsutil.upload_namespaced_directory(
      api.path.cleanup_dir.join("dir"),
      BUCKET,
      "cp_subpath",
      rsync=False,
      gzip_exts=["html"],
  )
  api.gsutil.upload(
      BUCKET, api.path.cleanup_dir.join("dir"), "dir", recursive=True
  )

  api.gsutil.copy(BUCKET, "foo", BUCKET, "bar", recursive=True)
  api.gsutil.download(BUCKET, "foo", "tmp/", recursive=True)

  api.gsutil.unauthenticated_url("https://storage.cloud.google.com/foo/bar")

  dir_url = api.gsutil.namespaced_directory_url("bucket", "foo")
  assert dir_url.endswith("builds/8945511751514863184/foo"), dir_url


def GenTests(api):
  yield api.buildbucket_util.test("basic")
  yield (
      api.buildbucket_util.test("retry_on_failure")
      # Cover the windows-specific codepath.
      + api.platform.name("win") +
      api.step_data(f"upload cp_subpath to {BUCKET}", retcode=1)
  )

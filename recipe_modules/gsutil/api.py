# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class GSUtilApi(recipe_api.RecipeApi):
  """GSUtilApi provides support for GSUtil."""

  @recipe_api.non_step
  def join(self, *parts):
    """Constructs a GS path from composite parts."""
    return "/".join(p.strip("/") for p in parts)

  def upload_namespaced_file(
      self,
      source,
      bucket,
      subpath,
      namespace=None,
      metadata=None,
      no_clobber=True,
      unauthenticated_url=False,
      **kwargs,
  ):
    """Uploads a file to GCS under a subpath specific to the given build.

        Will upload the file to:
        gs://<bucket>/<build id>/<subpath or basename of file>

        Args:
            source (Path): A path to the file to upload.
            bucket (str): The name of the GCS bucket to upload to.
            subpath (str): The end of the destination path within the
                build-specific subdirectory.
            namespace (str or None): A unique ID for this build. Defaults to the
                current build ID or led run ID.
            metadata (dict): A dictionary of metadata values to upload along
                with the file.
            no_clobber (bool): Skip upload if destination path already exists in
                GCS.
            unauthenticated_url (bool): Whether to present a URL that requires
                no authentication in the GCP web UI.
        """
    kwargs.setdefault("link_name", subpath)
    return self.upload(
        bucket=bucket,
        src=source,
        dst=self.namespaced_gcs_path(subpath, namespace),
        metadata=metadata,
        no_clobber=no_clobber,
        unauthenticated_url=unauthenticated_url,
        name=f"upload {subpath} to {bucket}",
        **kwargs,
    )

  def upload_namespaced_directory(
      self, source, bucket, subpath, namespace=None, rsync=True, **kwargs
  ):
    """Uploads a directory to GCS under a subpath specific to the given build.

        Will upload the directory to:
        gs://<bucket>/<build id>/<subpath>

        Args:
            source (Path): A path to the file to upload.
            bucket (str): The name of the GCS bucket to upload to.
            subpath (str): The end of the destination path within the
                build-specific subdirectory.
            namespace (str or None): A unique ID for this build. Defaults to the
                current build ID or led run ID.
            rsync (bool): Whether to use rsync, which is idempotent but
                sometimes less reliable.
        """
    kwargs.setdefault("link_name", subpath)
    func = self.upload
    if rsync:
      func = self.rsync
    return func(
        bucket=bucket,
        src=source,
        dst=self.namespaced_gcs_path(subpath, namespace),
        recursive=True,
        multithreaded=True,
        no_clobber=True,
        name=f"upload {subpath} to {bucket}",
        **kwargs,
    )

  def namespaced_gcs_path(self, relative_path, namespace=None):
    if not namespace:
      namespace = self.m.buildbucket_util.id
    return f"builds/{namespace}/{relative_path}"

  def http_url(self, bucket, dest, unauthenticated_url=False):
    base = (
        "https://storage.googleapis.com"
        if unauthenticated_url else "https://storage.cloud.google.com"
    )
    return f"{base}/{bucket}/{self.m.url.quote(dest)}"

  def _directory_listing_url(self, bucket, dest):
    """Returns the URL for a GCS bucket subdirectory listing in the GCP console."""
    return (
        f"https://console.cloud.google.com/storage/browser/{bucket}/"
        f"{self.m.url.quote(dest)}"
    )

  def namespaced_directory_url(self, bucket, subpath="", namespace=None):
    return self._directory_listing_url(
        bucket,
        self.namespaced_gcs_path(subpath, namespace),
    )

  @staticmethod
  def _get_metadata_field(name, provider_prefix=None):
    """Returns: (str) the metadata field to use with Google Storage

        The Google Storage specification for metadata can be found at:
        https://developers.google.com/storage/docs/gsutil/addlhelp/WorkingWithObjectMetadata
        """
    # Already contains custom provider prefix
    if name.lower().startswith("x-"):
      return name

    # See if it's innately supported by Google Storage
    if name in (
        "Cache-Control",
        "Content-Disposition",
        "Content-Encoding",
        "Content-Language",
        "Content-MD5",
        "Content-Type",
        "Custom-Time",
    ):
      return name

    # Add provider prefix
    if not provider_prefix:
      provider_prefix = "x-goog-meta"
    return f"{provider_prefix}-{name}"

  @staticmethod
  def unauthenticated_url(url):
    """Transform an authenticated URL to an unauthenticated URL."""
    return url.replace(
        "https://storage.cloud.google.com/", "https://storage.googleapis.com/"
    )

  def _add_custom_time(self, metadata):
    if not metadata:
      metadata = {}
    metadata["Custom-Time"] = self.m.time.utcnow(
    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return metadata

  def upload(
      self,
      bucket,
      src,
      dst,
      link_name="gsutil.upload",
      unauthenticated_url=False,
      recursive=False,
      no_clobber=False,
      gzip_exts=(),
      **kwargs,
  ):
    kwargs["metadata"] = self._add_custom_time(kwargs.pop("metadata", {}))
    args = ["cp"]
    if recursive:
      args.append("-r")
    if no_clobber:
      args.append("-n")
    if gzip_exts:
      args.extend(["-j"] + gzip_exts)
    args.extend([src, f"gs://{bucket}/{dst}"])
    if not recursive or no_clobber:
      # gsutil supports resumable uploads if we run the same command
      # again, but it's only safe to resume uploading if we're only
      # uploading a single file, or if we're operating in no_clobber mode.
      step = self.m.utils.retry(
          lambda: self._run(*args, **kwargs),
          max_attempts=3,
      )
    else:
      step = self._run(*args, **kwargs)
    if link_name:
      link_url = self.http_url(
          bucket, dst, unauthenticated_url=unauthenticated_url
      )
      step.presentation.links[link_name] = link_url
    return step

  def rsync(
      self,
      bucket,
      src,
      dst,
      link_name="gsutil.rsync",
      recursive=True,
      no_clobber=False,
      gzip_exts=(),
      **kwargs,
  ):
    kwargs["metadata"] = self._add_custom_time(kwargs.pop("metadata", {}))
    args = ["rsync"]
    if recursive:
      args.append("-r")
    if no_clobber:
      # This will skip files already existing in dst with a later
      # timestamp.
      args.append("-u")
    if gzip_exts:
      args.extend(["-j"] + gzip_exts)
    args.extend([src, f"gs://{bucket}/{dst}"])
    step = self.m.utils.retry(
        lambda: self._run(*args, **kwargs), max_attempts=3
    )
    if link_name:
      link_url = self._directory_listing_url(bucket, dst)
      step.presentation.links[link_name] = link_url
    return step

  def copy(
      self,
      src_bucket,
      src,
      dst_bucket,
      dst,
      link_name="gsutil.copy",
      unauthenticated_url=False,
      recursive=False,
      **kwargs,
  ):
    args = ["cp"]
    if recursive:
      args.append("-r")
    args.extend([f"gs://{src_bucket}/{src}", f"gs://{dst_bucket}/{dst}"])
    step = self._run(*args, **kwargs)
    if link_name:
      step.presentation.links[link_name] = self.http_url(
          dst_bucket, dst, unauthenticated_url=unauthenticated_url
      )
    return step

  def download(self, src_bucket, src, dest, recursive=False, **kwargs):
    """Downloads gcs bucket file to local disk.

        Args:
            src_bucket (str): gcs bucket name.
            src (str): gcs file or path name.
            recursive (bool): bool to indicate to copy recursively.
            dest (str): local file path root to copy to.
        """
    args = ["cp"]
    if recursive:
      args.append("-r")
    args.extend([f"gs://{src_bucket}/{src}", dest])
    return self._run(*args, **kwargs)

  @property
  def _gsutil_tool(self):
    return self.m.ensure_tool("gsutil", self.resource("tool_manifest.json"))

  def _run(self, *args, **kwargs):
    """Return a step to run arbitrary gsutil command."""
    assert self._gsutil_tool
    name = kwargs.pop("name", "gsutil " + args[0])
    infra_step = kwargs.pop("infra_step", True)
    cmd_prefix = [self._gsutil_tool]
    # Note that metadata arguments have to be passed before the command.
    metadata = kwargs.pop("metadata", [])
    if metadata:
      for k, v in sorted(metadata.items()):
        field = self._get_metadata_field(k)
        param = (field) if v is None else (f"{field}:{v}")
        cmd_prefix.extend(["-h", param])
    options = kwargs.pop("options", {})
    options["software_update_check_period"] = 0
    if options:
      for k, v in sorted(options.items()):
        cmd_prefix.extend(["-o", f"GSUtil:{k}={v}"])
    if kwargs.pop("multithreaded", False):
      cmd_prefix.extend(["-m"])

    # The `gsutil` executable is a Python script with a shebang, and Windows
    # doesn't support shebangs so we have to run it via Python.
    step_func = self.m.python3 if self.m.platform.is_win else self.m.step
    return step_func(
        name, cmd_prefix + list(args), infra_step=infra_step, **kwargs
    )

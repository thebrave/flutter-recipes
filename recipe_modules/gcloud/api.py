# Copyright 2019 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class GCloudApi(recipe_api.RecipeApi):
  """GCloudApi provides support for common gcloud operations."""

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.gcloud_patched = False

  @property
  def _gcloud_executable(self):
    with self.m.step.nest('ensure gcloud'):
      gcloud_dir = self.m.path['start_dir'].join('gcloud')
      gcloud_package = 'infra/3pp/tools/gcloud/${platform}'
      gcloud = self.m.cipd.EnsureFile().add_package(
          gcloud_package, "version:2@428.0.0.chromium.3"
      )
      self.m.cipd.ensure(gcloud_dir, gcloud)
      tool_name = 'gcloud.cmd' if self.m.platform.is_win else 'gcloud'
      return gcloud_dir.join('bin', tool_name)

  def __call__(self, *args, **kwargs):
    """Executes specified gcloud command."""
    step_name = kwargs.pop("step_name", f"gcloud {args[0]}")
    cmd = [self._gcloud_executable] + list(args)
    return self.m.step(step_name, cmd, **kwargs)

  def container_image_exists(self, image):
    step_result = self(
        "container",
        "images",
        "describe",
        image,
        ok_ret="any",
        step_name=f"check existence of {image}",
    )
    return step_result.retcode == 0

  def patch_gcloud_invoker(self):
    """GCloud invoker has issues when running on bots, this API
        patches the invoker to make it compatible with bots' python binary.
        """
    if self.gcloud_patched or not self._gcloud_executable:
      return
    gcloud_path = self.m.path.join(
        self.m.path.dirname(self.m.path.dirname(self._gcloud_executable)),
        "bin",
        "gcloud",
    )
    self.m.file.remove("remove gcloud wrapper", gcloud_path)
    self.m.file.copy(
        "copy patched gcloud",
        self.resource("gcloud"),
        gcloud_path,
    )
    self.gcloud_patched = True

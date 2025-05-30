# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    "flutter/tar",
    "recipe_engine/context",
    "recipe_engine/file",
    "recipe_engine/path",
    "recipe_engine/platform",
    "recipe_engine/step",
]


def RunSteps(api):
  # Prepare files.
  temp = api.path.mkdtemp("tar-example")
  api.step("touch a", ["touch", temp / "a"])
  api.step("touch b", ["touch", temp / "b"])
  api.file.ensure_directory("mkdirs", temp / "sub/dir")
  api.step("touch c", ["touch", temp / "sub/dir/c"])

  # Build a tar file.
  archive = api.tar.create(temp / "more.tar.gz", compression="gzip")
  archive.add(temp / "a", temp)
  with api.context(cwd=temp):
    archive.add(temp / "b")
  archive.add(temp / "sub/dir/c", temp / "sub")
  archive.tar("taring more")

  # Coverage for 'output' property.
  api.step("report", ["echo", archive.path])

  # Extract the archive into a directory stripping one path component.
  api.tar.extract(
      "untaring",
      temp / "output.tar",
      directory=temp / "output",
      strip_components=1,
  )
  # List untarped content.
  with api.context(cwd=temp / "output"):
    api.step("listing", ["find"])
  # Clean up.
  api.file.rmtree("rmtree %s" % temp, temp)


def GenTests(api):
  for platform in ("linux", "mac"):
    yield api.test(platform) + api.platform.name(platform)

# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    "flutter/gcloud",
    "recipe_engine/json",
]


def RunSteps(api):
    api.gcloud(
        "alpha",
        "remote-build-execution",
        "worker-pools",
        "list",
        "--project=goma-fuchsia",
        "--instance=default_instance",
    )
    api.gcloud("help")
    api.gcloud.container_image_exists("gcr.io/goma_fuchsia/fuchsia_linux/base")
    api.gcloud.patch_gcloud_invoker()
    api.gcloud.patch_gcloud_invoker()
    api.gcloud.publish_message('step', 'a/b/c', api.json.input(data='abc'))


def GenTests(api):
    yield api.test("example")

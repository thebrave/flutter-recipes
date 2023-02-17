# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/gerrit_util',
    'recipe_engine/json'
]


def RunSteps(api):
    api.gerrit_util.get_gerrit_cl_details(
        'flutter.googlesource.com', '12345'
    )


def GenTests(api):
    yield api.test(
        'basic',
        api.step_data(
            'gerrit get cl info 12345',
            api.json.output([('branch', 'main')])
        )
    )

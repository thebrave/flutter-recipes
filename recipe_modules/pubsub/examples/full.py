# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['flutter/pubsub']


def RunSteps(api):
  api.pubsub.publish_message('custom/pubsub/url', 'message', 'Test step')


def GenTests(api):
  yield api.test('basic')

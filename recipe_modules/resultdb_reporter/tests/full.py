# Copyright 2022 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.lucictx import sections as sections_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1.test_result import TestStatus

DEPS = [
    "flutter/resultdb_reporter",
    "recipe_engine/context",
    "recipe_engine/step",
]


def RunSteps(api):
  api.resultdb_reporter.report_result(
      test_id='//test_suite/test_class/test_method',
      summary='summary',
      status=TestStatus.FAIL)


def GenTests(api):
    luci_context = api.context.luci_context(
        realm=sections_pb2.Realm(name="proj:realm"),
        resultdb=sections_pb2.ResultDB(
            current_invocation=sections_pb2.ResultDBInvocation(
                name="invocations/inv",
                update_token="token",
            ),
            hostname="rdbhost",
        ),
    )

    yield api.test("basic") + luci_context

    yield api.test("resultdb_not_enabled")

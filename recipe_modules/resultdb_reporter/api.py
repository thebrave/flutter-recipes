# Copyright 2024 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
from recipe_engine import recipe_api
from PB.go.chromium.org.luci.resultdb.proto.v1.test_result import TestStatus


class PreparedResult:
  """Represents a test result that will be uploaded to resultdb."""

  def __init__(self, api, test_id, summary, status, resultdb_resource):
    self._api = api
    self._test_id = test_id
    self._summary = summary
    self._status = status
    self._resultdb_resource = resultdb_resource

  def upload(self):
    """
        Uploads the preparedResult to resultdb.

        This operation creates a step at the current nesting level.
        Logs set in the prepared step are linked as part of the summary.
        """
    step_name = "upload to resultdb"

    if not self._api.resultdb.enabled:
      self._api.step.empty(
          step_name,
          status=self._api.step.INFRA_FAILURE,
          step_text="ResultDB integration was not enabled for this build",
          raise_on_failure=False,
      )
      return

    expected = self._status == TestStatus.PASS

    test_result = {
        "testId": self._test_id,
        "expected": expected,
        "summaryHtml": self._summary,
        "status": self._status,
    }

    cmd = [
        "vpython3",
        self._resultdb_resource,
        json.dumps(test_result),
    ]

    self._api.step(
        step_name,
        self._api.resultdb.wrap(cmd),
        infra_step=True,
    )


class ResultdbReporterApi(recipe_api.RecipeApi):
  """ResultdbReporterApi provides functionality to upload test results
    to resultsdb.
    """

  def report_result(self, test_id, summary, status):
    """
        Uploads a single test result to resultsdb.
        Args:
            test_id (str): test id to be used by resultdb.
            summary (string): The summary of the test result.
            status (TestStatus): The pass/failed/skipped status of the test result.
        """
    prepared_result = PreparedResult(
        self.m, test_id, summary, status, self.resource("resultdb.py")
    )
    prepared_result.upload()

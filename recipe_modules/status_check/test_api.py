# Copyright 2019 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Allow tests to assert recipe success or failure.

TODO(crbug/1010715) Remove this and use functionality in core recipe
engine.
"""

from recipe_engine import recipe_test_api
from recipe_engine import post_process


class StatusCheckTestApi(recipe_test_api.RecipeTestApi):

  def test(self, name, status="success"):
    if " " in name:  # pragma: no cover
      raise Exception(
          f"Invalid recipe test name {name!r}. Test names should use underscores, not spaces. See http://go/fuchsia-recipe-docs#test-case-naming"
      )
    return super(StatusCheckTestApi, self).test(name) + self.status(status)

  def status(self, status="success"):
    """Returns step data to check status of recipe at end of test.

        Args:
          status: One of 'success' (default), 'failure', 'infra_failure', or
              'exception'. The result of the test case will be required to
              match this.
        """

    assertion_type = {
        "exception": post_process.StatusException,
        "failure": post_process.StatusFailure,
        "infra_failure": post_process.StatusException,
        "success": post_process.StatusSuccess,
    }[status]
    return self.post_process(assertion_type)

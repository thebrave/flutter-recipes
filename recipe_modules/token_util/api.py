# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class TokenUtilApi(recipe_api.RecipeApi):
  """Utilities to generate tokens for communicating data."""

  def metric_center_token(self):
    """Generate a token to interact with GCS.

    Returns the path to the written token.
    """
    service_account = self.m.service_account.default()
    metrics_center_access_token = service_account.get_access_token(
        scopes=[
            'https://www.googleapis.com/auth/cloud-platform',
            'https://www.googleapis.com/auth/datastore'
        ]
    )
    metrics_center_token_path = self.m.path.mkstemp()
    self.m.file.write_text(
        "write metric center token",
        metrics_center_token_path,
        metrics_center_access_token,
        include_log=False
    )
    return metrics_center_token_path

  def cocoon_token(self):
    """Generate a token to interact with Cocoon backend APIs.

    Returns the path to the written token.
    """
    service_account = self.m.service_account.default()
    cocoon_access_token = service_account.get_access_token()

    cocoon_access_token_path = self.m.path.mkstemp()
    self.m.file.write_text(
        "write cocoon token",
        cocoon_access_token_path,
        cocoon_access_token,
        include_log=False
    )
    return cocoon_access_token_path


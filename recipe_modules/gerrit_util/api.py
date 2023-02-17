# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class GerritUtilApi(recipe_api.RecipeApi):
  """Provides utilities to work with gerrit."""

  def get_gerrit_cl_details(self, host, cl_number):
    """Collects and returns details about a gerrit CL

    Args:
      host: The host url of the CL ('eg: flutter-review.googlesource.com')
      cl_number: The CL number of the requested CL
    """
    cl_information = self.m.gerrit.call_raw_api(
          'https://%s' % host,
          '/changes/%s' % cl_number,
          accept_statuses=[200],
          name='get cl info %s' % cl_number)

    return cl_information

# Copyright 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/common',
    'recipe_engine/properties',
]


def RunSteps(api):
  method = api.properties['method']
  if method == 'is_release_candidate_branch':
    assert api.common.is_release_candidate_branch(
        api.properties['branch']
    ) == api.properties['expectation']
  elif method == 'branch_ref_to_branch_name':
    ref = api.properties['branch_name']
    expectation = api.properties['expectation']
    assert api.common.branch_ref_to_branch_name(ref) == expectation
  else:
    raise AssertionError(
        f'Malformed test property: key "method" was "{method}". ' +
        'You probably need to add this method to the RunSteps function.'
    )


def GenTests(api):
  yield api.test(
      'is_release_candidate_branch detects non-release branch',
      api.properties(
          **{
              'method': 'is_release_candidate_branch',
              'branch': 'main',
              'expectation': False,
          }
      )
  )
  yield api.test(
      'is_release_candidate_branch detects release branch',
      api.properties(
          **{
              'method': 'is_release_candidate_branch',
              'branch': 'flutter-10.37-candidate.1001',
              'expectation': True,
          }
      )
  )
  yield api.test(
      'branch_ref_to_branch_name_works',
      api.properties(
          method='branch_ref_to_branch_name',
          branch_name='refs/heads/foo_bar',
          expectation='foo_bar',
      )
  )
  yield api.test(
      'catches_invalid_method_property',
      api.properties(method=None),
      api.expect_exception('AssertionError'),
  )

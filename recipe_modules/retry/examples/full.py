# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

DEPS = [
    'flutter/retry',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = {
    "max_attempts":
        Property(
            kind=int,
            help="How many times to try before giving up.",
            default=1,
        ),
}


def RunSteps(api, max_attempts):
  api.retry.step(
      'Run FEMU Test Suite', [
          'echo', 'hello', '>',
          api.raw_io.output_text(name='syslog'), ';', 'echo', 'hello', '>',
          api.raw_io.output_text(name='emulator_log')
      ],
      max_attempts=max_attempts,
      step_test_data=(
          lambda: api.raw_io.test_api.output_text('failure', name='syslog')
      )
  )
  api.retry.step('mytest', ['ls', '-la'], max_attempts=max_attempts)

  def func():
    api.step('mytest_func', ['ls', '-a'])

  api.retry.wrap(func, max_attempts=max_attempts)


def GenTests(api):
  yield api.test('failing') + api.properties(max_attempts=1) + api.step_data(
      'mytest', retcode=1
  ) + api.step_data(
      'Run FEMU Test Suite', retcode=0
  )
  yield api.test('failing_wrap') + api.properties(max_attempts=1
                                                 ) + api.step_data(
                                                     'mytest_func', retcode=1
                                                 )
  yield api.test('pass_with_retries') + api.properties(max_attempts=2
                                                      ) + api.step_data(
                                                          'mytest', retcode=1
                                                      ) + api.step_data(
                                                          'mytest_func',
                                                          retcode=1
                                                      )

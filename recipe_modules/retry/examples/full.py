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
      'test: Run FEMU Test Suite', [
          'echo', 'hello', '>',
          api.raw_io.output_text(name='syslog'), ';', 'echo', 'hello', '>',
          api.raw_io.output_text(name='emulator_log')
      ],
      max_attempts=max_attempts,
      step_test_data=(
          lambda: api.raw_io.test_api.output_text('failure', name='syslog')
      )
  )
  api.retry.step('test: mytest', ['ls', '-la'], max_attempts=max_attempts)

  def func1():
    api.step('test: mytest_func', ['ls', '-a'])

  def func2():
    api.step('test: mytest_func_basic', ['ls', '-a'])

  api.retry.wrap(func1, step_name='test: mytest_func', max_attempts=max_attempts)
  api.retry.basic_wrap(func2, max_attempts=max_attempts)
  api.retry.run_flutter_doctor()


def GenTests(api):
  yield api.test('passing') + api.properties(max_attempts=1)
  yield api.test('failing_step') + api.properties(max_attempts=1
                                                 ) + api.step_data(
                                                     'test: mytest', retcode=1
                                                 )
  yield api.test('failing_wrap') + api.properties(max_attempts=1
                                                 ) + api.step_data(
                                                     'test: mytest_func',
                                                     retcode=1
                                                 )
  yield api.test('failing_basic_wrap') + api.properties(max_attempts=1
                                                 ) + api.step_data(
                                                     'test: mytest_func_basic',
                                                     retcode=1
                                                 )
  yield api.test('pass_with_retries') + api.properties(
      max_attempts=2
  ) + api.step_data(
      'test: mytest', retcode=1
  ) + api.step_data(
      'test: mytest_func', retcode=1
  ) + api.step_data(
      'test: mytest_func_basic', retcode=1
  )

# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

DEPS = [
    'flutter/retry',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/context',
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
    with api.step.nest('nested'):
      api.step('test: mytest_func', ['ls', '-a'])

  # pylint: disable=unused-argument
  def func2(timeout=None):
    api.step('test: mytest_func_basic', ['ls', '-a'])

  def func3():
    api.step('test: mytest_func_3', ['ls', '-a'])

  api.retry.wrap(
      func1, step_name='nested.test: mytest_func', max_attempts=max_attempts
  )
  api.retry.basic_wrap(func2, max_attempts=max_attempts)
  api.retry.run_flutter_doctor()
  api.retry.wrap(func3, max_attempts=max_attempts, retriable_codes=(1,))


def GenTests(api):
  yield api.test('passing', api.properties(max_attempts=1))
  yield api.test(
      'failing_step',
      api.properties(max_attempts=1),
      api.step_data('test: mytest', retcode=1),
      status='FAILURE'
  )
  yield api.test(
      'failing_wrap',
      api.properties(max_attempts=1),
      api.step_data('nested.test: mytest_func', retcode=1),
      status='FAILURE'
  )
  yield api.test(
      'failing_wrap_with_nested',
      api.properties(max_attempts=1),
      api.step_data('test: mytest_func_3', retcode=1),
      status='FAILURE'
  )
  yield api.test(
      'failing_basic_wrap',
      api.properties(max_attempts=1),
      api.step_data('test: mytest_func_basic', retcode=1),
      status='FAILURE'
  )
  yield api.test(
      'pass_with_retries', api.properties(max_attempts=2),
      api.step_data('test: mytest', retcode=1),
      api.step_data('nested.test: mytest_func', retcode=1),
      api.step_data('test: mytest_func_basic', retcode=1)
  )

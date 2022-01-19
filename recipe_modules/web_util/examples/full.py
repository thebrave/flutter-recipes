# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.post_process import DoesNotRun, Filter, StatusFailure

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'flutter/web_util',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/runtime',
]


def RunSteps(api):
  engine_checkout_path = api.path['cache'].join('builder', 'src')
  api.web_util.prepare_web_dependencies(engine_checkout_path)

def GenTests(api):
  browser_yaml_file = {
      'required_driver_version': {
          'chrome': 84
      },
      'chrome': {
          'Linux': '768968',
          'Mac': '768985',
          'Win': '768975'
      }
  }
  yield api.test(
      'fail case',
      api.expect_exception('ValueError'),
      api.properties(
          web_dependencies=['invalid_dependency'],), api.platform(
              'linux', 64)) + api.platform.name('linux')
  yield api.test(
      'chrome driver',
      api.step_data('read browser lock yaml.parse',
                    api.json.output(browser_yaml_file)),
      api.properties(
          web_dependencies=['chrome_driver'],), api.platform(
              'linux', 64)) + api.platform.name('linux')
  yield api.test(
      'firefox driver',
      api.properties(
          web_dependencies=['firefox_driver'],), api.platform(
              'linux', 64)) + api.platform.name('linux')
  yield api.test(
      'chrome',
      api.step_data('read browser lock yaml.parse',
                    api.json.output(browser_yaml_file)),
      api.properties(
          web_dependencies=['chrome'],), api.platform(
              'linux', 64)) + api.platform.name('linux')
  yield api.test(
      'mac-post-submit',
      api.properties(
          goma_jobs='200',
          web_dependencies=[],
          command_args=['test', '--browser=ios-safari'],
          command_name='ios-safari-unit-tests'), api.platform(
              'mac', 64)) + api.runtime(is_experimental=False)

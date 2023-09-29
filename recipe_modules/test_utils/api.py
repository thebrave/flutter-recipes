# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import html
import re

from recipe_engine import recipe_api

# The maximum number of characters to be included in the summary markdown.
# Even though the max size for the markdown is 4000 bytes we are saving 500
# bytes for addittional prefixes added automatically by LUCI like the number
# of failed steps out of the total.
MAX_CHARS = 3500

# Default timeout for tests seconds
TIMEOUT_SECS = 3600

# Map between iphone identifier and generation name.
IDENTIFIER_NAME_MAP = {
    'iPhone1,1': 'iPhone',
    'iPhone1,2': 'iPhone 3G',
    'iPhone2,1': 'iPhone 3GS',
    'iPhone3,1': 'iPhone 4',
    'iPhone3,2': 'iPhone 4',
    'iPhone3,3': 'iPhone 4',
    'iPhone4,1': 'iPhone 4S',
    'iPhone5,1': 'iPhone 5',
    'iPhone5,2': 'iPhone 5',
    'iPhone5,3': 'iPhone 5c',
    'iPhone5,4': 'iPhone 5c',
    'iPhone6,1': 'iPhone 5s',
    'iPhone6,2': 'iPhone 5s',
    'iPhone7,2': 'iPhone 6',
    'iPhone7,1': 'iPhone 6 Plus',
    'iPhone8,1': 'iPhone 6s',
    'iPhone8,2': 'iPhone 6s Plus',
    'iPhone8,4': 'iPhone SE (1st generation)',
    'iPhone9,1': 'iPhone 7',
    'iPhone9,3': 'iPhone 7',
    'iPhone9,2': 'iPhone 7 Plus',
    'iPhone9,4': 'iPhone 7 Plus',
    'iPhone10,1': 'iPhone 8',
    'iPhone10,4': 'iPhone 8',
    'iPhone10,2': 'iPhone 8 Plus',
    'iPhone10,5': 'iPhone 8 Plus',
    'iPhone10,3': 'iPhone X',
    'iPhone10,6': 'iPhone X',
    'iPhone11,8': 'iPhone XR',
    'iPhone11,2': 'iPhone XS',
    'iPhone11,6': 'iPhone XS Max',
    'iPhone12,1': 'iPhone 11',
    'iPhone12,3': 'iPhone 11 Pro',
    'iPhone12,5': 'iPhone 11 Pro Max',
    'iPhone12,8': 'iPhone SE (2nd generation)',
    'iPhone13,1': 'iPhone 12 mini',
    'iPhone13,2': 'iPhone 12',
    'iPhone13,3': 'iPhone 12 Pro',
    'iPhone13,4': 'iPhone 12 Pro Max',
    'iPhone14,4': 'iPhone 13 mini',
    'iPhone14,5': 'iPhone 13',
    'iPhone14,2': 'iPhone 13 Pro',
    'iPhone14,3': 'iPhone 13 Pro Max',
}

# Regexp for windows os version number
_WINDOWS_OS_RE = r'\[version (\d+\.\d+)\.(\d+(?:\.\d+|))\]'


# Same as StepFailure except that the message is assumed to be
# already formatted. (StepFailure assumes that the message needs
# to be further escaped.)
# See https://chromium.googlesource.com/infra/luci/recipes-py/+/HEAD/recipe_engine/recipe_api.py#399
class PrettyFailure(recipe_api.StepFailure):
  """Wrapper class to avoid the ! formatter in StepFailure"""

  def reason_message(self):
    return '{}\nStep failed'.format(self.name)


class TestUtilsApi(recipe_api.RecipeApi):
  """Utilities to run flutter tests."""

  def _truncateString(self, string):
    """Truncate the string by lines from the end so that the output has
    less than MAX_CHARS bytes."""
    byte_count = 0
    lines = string.splitlines()
    output = []
    for line in reversed(lines):
      # +1 to account for the \n separators.
      byte_count += len(line.encode('utf-8')) + 1
      if byte_count >= MAX_CHARS:
        break
      output.insert(0, line)
    return '\n'.join(output)

  def _is_flaky(self, output):
    """Check if test step is flaky"""
    lines = output.splitlines()
    lines.reverse()
    # The flakiness status message `flaky: true` is expected to be located at the
    # end of the stdout file. Check last 10 lines to make sure it is covered if existing.
    for line in lines[:10]:
      if 'flaky: true' in line:
        return True
    return False

  def is_devicelab_bot(self):
    """Whether the current bot is a devicelab bot or not."""
    return (
        str(self.m.swarming.bot_id).startswith('flutter-devicelab') or
        str(self.m.swarming.bot_id).startswith('flutter-win')
    )

  def run_test(
      self,
      step_name,
      command_list,
      timeout_secs=TIMEOUT_SECS,
      infra_step=False,
      suppress_log=False
  ):
    """Recipe's step wrapper to collect stdout and add it to step_summary.

    Args:
      step_name(str): The name of the step.
      command_list(list(str)): A list of strings with the command and
        parameters to execute.
      timeout_secs(int): The timeout in seconds for this step.
      infra_step: mark step as an infra step
      suppress_log: flag whether test logs are suppressed.

    Returns(str): The status of the test step. A str `flaky` or `success` will
      be returned when step succeeds, and an exception will be thrown out when
      step fails.
    """
    try:
      step = self.m.step(
          step_name,
          command_list,
          infra_step=infra_step,
          stdout=self.m.raw_io.output_text(),
          stderr=self.m.raw_io.output_text(),
          timeout=timeout_secs
      )
    except self.m.step.StepFailure as f:
      result = f.result
      # Truncate stdout
      stdout = self._truncateString(result.stdout)
      # Truncate stderr
      stderr = self._truncateString(result.stderr)
      raise PrettyFailure(
          '\n\n```\n%s\n```\n' % (stdout or stderr),
          result=result,
      )
    finally:
      if not suppress_log:
        self.m.step.active_result.presentation.logs[
            'test_stdout'] = self.m.step.active_result.stdout
        self.m.step.active_result.presentation.logs[
            'test_stderr'] = self.m.step.active_result.stderr
    if self._is_flaky(step.stdout):
      test_run_status = 'flaky'
      step.presentation.status = self.m.step.FAILURE
    else:
      test_run_status = 'success'
    return test_run_status

  def test_step_name(self, step_name):
    """Append keyword test to test step name to be consistent.
    Args:
      step_name(str): The name of the step.

    Returns(str): The test step name prefixed with "test".
    """
    return 'test: %s' % step_name

  def flaky_step(self, step_name):
    """Add a flaky step when test is flaky.
    Args:
      step_name(str): The name of the step.
    """
    if self.m.platform.is_win:
      self.m.step(
          'step is flaky: %s' % step_name,
          ['powershell.exe', 'echo "test run is flaky"'],
          infra_step=True,
      )
    else:
      self.m.step(
          'step is flaky: %s' % step_name,
          ['echo', 'test run is flaky'],
          infra_step=True,
      )

  def collect_benchmark_tags(self, env, env_prefixes, target_tags):
    """Collect host and device tags for devicelab benchmarks.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      target_tags(list(str)): Builder tags defined in .ci.yaml targets.

    Returns:
      A dictionary representation of the tag names and values.

    Examples:
      Linux/android:
        {
          'arch': 'intel',
          'host_type': 'linux',
          'device_type': 'Moto G Play'
        }
      Mac/ios:
        {
          'arch': 'm1',
          'host_type': 'mac',
          'device_type': 'iPhone 6s'
        }
      Windows/android:
        {
          'arch': 'intel',
          'host_type': 'win',
          'device_type': 'Moto G Play'
        }
    """
    device_tags = {}

    def _get_tag(step_name, commands):
      return self.m.step(
          step_name,
          commands,
          stdout=self.m.raw_io.output_text(),
          infra_step=True,
      ).stdout.rstrip()

    # Collect device tags.
    #
    # Mac/iOS testbeds always have builder_name starting with `Mac_ios`.
    # The android tests always have builder_name like `%_android %`.
    #
    # We may need to support other platforms like desktop, and
    # https://github.com/flutter/flutter/issues/92296 to track a more
    # generic way to collect device tags.
    if 'ios' in target_tags:
      with self.m.context(env=env, env_prefixes=env_prefixes):
        iphone_identifier = _get_tag(
            'Find device type', ['ideviceinfo', '--key', 'ProductType']
        )
        device_tags['device_type'] = IDENTIFIER_NAME_MAP[iphone_identifier]
    elif 'android' in target_tags:
      with self.m.context(env=env, env_prefixes=env_prefixes):
        device_tags['device_type'] = _get_tag(
            'Find device type', ['adb', 'shell', 'getprop', 'ro.product.model']
        )
    else:
      device_tags['device_type'] = 'none'

    # Use same `none` as device version to consolidate metric data streams.
    # Do not use real distinct values: https://github.com/flutter/flutter/issues/112804
    device_tags['device_version'] = 'none'

    device_tags['host_type'] = self.m.platform.name
    device_tags['arch'] = self.m.properties.get('arch', self.m.platform.arch)

    return device_tags

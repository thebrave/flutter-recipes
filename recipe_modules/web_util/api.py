# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy
from recipe_engine import recipe_api


class WebUtilsApi(recipe_api.RecipeApi):
  """Utilities to use when running flutter web engine tests."""

  def firefox_driver(self, checkout):
    """Downloads the latest version of the Firefox web driver from CIPD."""
    # Download the driver for Firefox.
    firefox_driver_path = checkout.join('flutter', 'lib', 'web_ui',
                                        '.dart_tool', 'drivers', 'firefox')
    pkgdriver = self.m.cipd.EnsureFile()
    pkgdriver.add_package(
        'flutter_internal/browser-drivers/firefoxdriver-linux', 'latest')
    self.m.cipd.ensure(firefox_driver_path, pkgdriver)

  def chrome(self, checkout):
    """Downloads Chrome from CIPD.

    The chrome version to be used will be read from a file on the repo side.
    """
    browser_lock_yaml_file = checkout.join('flutter', 'lib', 'web_ui', 'dev',
                                           'browser_lock.yaml')
    with self.m.context(cwd=checkout):
      result = self.m.yaml.read(
          'read browser lock yaml',
          browser_lock_yaml_file,
          self.m.json.output(),
      )
      browser_lock_content = result.json.output
      platform = self.m.platform.name.capitalize()
      binary = browser_lock_content['chrome'][platform]
      chrome_path = checkout.join('flutter', 'lib', 'web_ui', '.dart_tool',
                                  'chrome', '%s' % binary)
    # Using the binary number since the repos side file uses binary names.
    # See: flutter/engine/blob/master/lib/web_ui/dev/browser_lock.yaml
    # Chrome also uses these binary numbers for archiving different versions.
    chrome_pkg = self.m.cipd.EnsureFile()
    chrome_pkg.add_package('flutter_internal/browsers/chrome/${platform}',
                           binary)
    self.m.cipd.ensure(chrome_path, chrome_pkg)

  def chrome_driver(self, checkout):
    """Downloads Chrome web driver from CIPD.

    The driver version to be used will be read from a file on the repo side.
    """
    # Get driver version from the engine repo.
    # See: flutter/engine/blob/master/lib/web_ui/dev/browser_lock.yaml
    browser_lock_yaml_file = checkout.join('flutter', 'lib', 'web_ui', 'dev',
                                           'browser_lock.yaml')
    with self.m.context(cwd=checkout):
      result = self.m.yaml.read(
          'read browser lock yaml',
          browser_lock_yaml_file,
          self.m.json.output(),
      )
      browser_lock_content = result.json.output
      version = browser_lock_content['required_driver_version']['chrome']
    chrome_driver_path = checkout.join('flutter', 'lib', 'web_ui', '.dart_tool',
                                       'drivers', 'chrome', '%s' % version)
    chrome_pkgdriver = self.m.cipd.EnsureFile()
    chrome_pkgdriver.add_package(
        'flutter_internal/browser-drivers/chrome/${platform}',
        'latest-%s' % version)
    self.m.cipd.ensure(chrome_driver_path, chrome_pkgdriver)

  def get_web_dependencies(self):
    return self.m.properties.get('web_dependencies', [])

  def prepare_web_dependencies(self, checkout):
    """Install all the required web_dependencies for a given felt test."""
    available_deps = {
        'chrome': self.chrome,
        'chrome_driver': self.chrome_driver,
        'firefox_driver': self.firefox_driver,
    }
    for dep in self.get_web_dependencies():
      dep_funct = available_deps.get(dep)
      if not dep_funct:
        raise ValueError('Web Dependency %s not available.' % dep)
      dep_funct(checkout)

# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy
from recipe_engine import recipe_api


class FlutterDepsApi(recipe_api.RecipeApi):
  """Utilities to install flutter build/test dependencies at runtime."""

  def flutter_engine(self, env, env_prefixes):
    """ Sets the local engine related information to environment variables.

    If the drone is started to run the tests with a local engine, it will
    contain a `local_engine_cas_hash` property where we can download engine files.
    If the `local_engine` property is present, it will override the
    default build configuration name, "host_debug_unopt"

    These files will be located in the build folder, whose name comes
    from the build configuration.
    Args:

      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
    """
    # No-op if `local_engine_cas_hash` property is empty
    cas_hash = self.m.properties.get('local_engine_cas_hash')
    local_engine = self.m.properties.get('local_engine')
    if cas_hash:
      checkout_engine = self.m.path['cleanup'].join('builder', 'src', 'out')
      # Download host_debug_unopt from CAS.
      if cas_hash:
        self.m.cas.download(
            'Download engine from CAS', cas_hash, checkout_engine
        )
      local_engine = checkout_engine.join(
          local_engine or 'host_debug_unopt')
      dart_bin = local_engine.join('dart-sdk', 'bin')
      paths = env_prefixes.get('PATH', [])
      paths.insert(0, dart_bin)
      env_prefixes['PATH'] = paths
      env['LOCAL_ENGINE'] = local_engine

  def required_deps(self, env, env_prefixes, deps):
    """Install all the required dependencies for a given builder.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      deps(list(dict)): A list of dictionaries with dependencies as
        {'dependency': 'android_sdk', version: ''} where an empty version
        means the default.
    """
    available_deps = {
        'android_sdk': self.android_sdk,
        'android_virtual_device': self.android_virtual_device,
        'apple_signing': self.apple_signing,
        'certs': self.certs,
        'chrome_and_driver': self.chrome_and_driver,
        'clang': self.clang,
        'cmake': self.cmake,
        'codesign': self.codesign,
        'cosign': self.cosign,
        'curl': self.curl,
        'dart_sdk': self.dart_sdk,
        'dashing': self.dashing,
        'firebase': self.firebase,
        'gh_cli': self.gh_cli,
        'go_sdk': self.go_sdk,
        'goldctl': self.goldctl,
        'gradle_cache': self.gradle_cache,
        'ios_signing': self.apple_signing, # TODO(drewroen): Remove this line once ios_signing is not being referenced
        'jazzy': self.jazzy,
        'ninja': self.ninja,
        'open_jdk': self.open_jdk,
        'vs_build': self.vs_build,
    }
    parsed_deps = []
    for dep in deps:
      dependency = dep.get('dependency')
      version = dep.get('version')
      # Ensure there are no duplicate entries
      if dependency in parsed_deps:
        msg = '''Dependency %s is duplicated
            Ensure ci.yaml contains only one entry for this target
            '''.format(dependency)
        raise ValueError(msg)
      parsed_deps.append(dependency)
      if dependency in ['xcode', 'gems', 'swift', 'arm64ruby']:
        continue
      dep_funct = available_deps.get(dependency)
      if not dep_funct:
        msg = '''Dependency %s not available.
            Ensure ci.yaml contains one of the following supported keys:
            %s'''.format(dependency, available_deps.keys())
        raise ValueError(msg)
      dep_funct(env, env_prefixes, version)

  def open_jdk(self, env, env_prefixes, version):
    """Downloads OpenJdk CIPD package and updates environment variables.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      version(str): The OpenJdk version to install.
    """
    version = version or 'version:1.8.0u202-b08'
    with self.m.step.nest('OpenJDK dependency'):
      java_cache_dir = self.m.path['cache'].join('java')
      self.m.cipd.ensure(
          java_cache_dir,
          self.m.cipd.EnsureFile().add_package(
              'flutter_internal/java/openjdk/${platform}', version
          )
      )
      java_home = java_cache_dir
      if self.m.platform.is_mac:
        java_home = java_cache_dir.join('contents', 'Home')

      env['JAVA_HOME'] = java_home
      path = env_prefixes.get('PATH', [])
      path.append(java_home.join('bin'))
      env_prefixes['PATH'] = path

  def goldctl(self, env, env_prefixes, version):
    """Downloads goldctl from CIPD and updates the environment variables.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      version(str): The goldctl version to install.
    """
    version = version or 'git_revision:d38e22e2bde5edd79b4137583097e6ef59dee329'
    with self.m.step.nest('Download goldctl'):
      goldctl_cache_dir = self.m.path['cache'].join('gold')
      self.m.cipd.ensure(
          goldctl_cache_dir,
          self.m.cipd.EnsureFile().add_package(
              'skia/tools/goldctl/${platform}', version
          )
      )
      env['GOLDCTL'] = goldctl_cache_dir.join('goldctl')

    if self.m.properties.get('git_ref') and self.m.properties.get('gold_tryjob'
                                                                 ) == True:
      env['GOLD_TRYJOB'] = self.m.properties.get('git_ref')

  def chrome_and_driver(self, env, env_prefixes, version):
    """Downloads chrome from CIPD and updates the environment variables.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      version(str): The Chrome version to install.
    """
    version = version or 'latest'
    with self.m.step.nest('Chrome and driver dependency'):
      env['CHROME_NO_SANDBOX'] = 'true'
      chrome_path = self.m.path['cache'].join('chrome', 'chrome')
      pkgs = self.m.cipd.EnsureFile()
      pkgs.add_package('flutter_internal/browsers/chrome/${platform}', version)
      self.m.cipd.ensure(chrome_path, pkgs)
      chrome_driver_path = self.m.path['cache'].join('chrome', 'drivers')
      pkgdriver = self.m.cipd.EnsureFile()
      pkgdriver.add_package(
          'flutter_internal/browser-drivers/chrome/${platform}', version
      )
      self.m.cipd.ensure(chrome_driver_path, pkgdriver)
      paths = env_prefixes.get('PATH', [])
      paths.append(chrome_path)
      paths.append(chrome_driver_path)
      env_prefixes['PATH'] = paths
      binary_name = 'chrome.exe' if self.m.platform.is_win else 'chrome'
      if self.m.platform.is_mac:
        exec_path = chrome_path.join(
            'chrome-mac', 'Chromium.app', 'Contents', 'MacOS', 'Chromium'
        )
        env['CHROME_EXECUTABLE'] = exec_path
      else:
        env['CHROME_EXECUTABLE'] = chrome_path.join(binary_name)

  def gh_cli(self, env, env_prefixes, version):
    """Installs GitHub CLI."""
    version = version or 'latest'
    gh_path = self.m.path['cache'].join('gh-cli')
    gh_file = self.m.cipd.EnsureFile()
    gh_file.add_package('flutter_internal/tools/gh-cli/${platform}', version)
    self.m.cipd.ensure(gh_path, gh_file)
    self.m.step('check gh version', [gh_path.join('bin', 'gh'), '--version'])
    paths = env_prefixes.get('PATH', [])
    paths.append(gh_path.join('bin'))
    env_prefixes['PATH'] = paths

  def go_sdk(self, env, env_prefixes, version):
    """Installs go sdk."""
    version = version or 'version:1.12.5'
    go_path = self.m.path['cache'].join('go')
    go = self.m.cipd.EnsureFile()
    go.add_package('infra/go/${platform}', version)
    self.m.cipd.ensure(go_path, go)
    paths = env_prefixes.get('PATH', [])
    paths.append(go_path.join('bin'))
    # Setup GOPATH and add to the env.
    bin_path = self.m.path['cleanup'].join('go_path')
    self.m.file.ensure_directory('Ensure go path', bin_path)
    env['GOPATH'] = bin_path
    paths.append(bin_path.join('bin'))
    env_prefixes['PATH'] = paths

  def dashing(self, env, env_prefixes, version):
    """Installs dashing."""
    version = version or 'git_revision:ed8da90e524f59c69781c8af65638f108d0bbba6'
    self.go_sdk(env, env_prefixes, 'latest')
    with self.m.context(env=env, env_prefixes=env_prefixes):
      self.m.step(
          'Install dashing',
          ['go', 'get', '-u', 'github.com/technosophos/dashing'],
          infra_step=True,
      )

  def curl(self, env, env_prefixes, version):
    """Installs curl."""
    version = version or 'latest'
    curl_path = self.m.path.mkdtemp().join('curl')
    curl = self.m.cipd.EnsureFile()
    curl.add_package('flutter_internal/tools/curl/${platform}', version)
    self.m.cipd.ensure(curl_path, curl)
    paths = env_prefixes.get('PATH', [])
    paths.append(curl_path)
    env_prefixes['PATH'] = paths

  def android_sdk(self, env, env_prefixes, version):
    """Installs android sdk."""
    version = version or 'latest'
    sdk_root = self.m.path['cache'].join('android')
    self.m.cipd.ensure(
        sdk_root,
        self.m.cipd.EnsureFile().add_package(
            'flutter/android/sdk/all/${platform}',
            version,
        ),
    )
    # Setup environment variables
    if (version == 'version:29.0'): # Handle the legacy case
      env['ANDROID_SDK_ROOT'] = sdk_root
      env['ANDROID_HOME'] = sdk_root
      env['ANDROID_NDK_PATH'] = sdk_root.join('ndk-bundle')
    else:
      env['ANDROID_SDK_ROOT'] = sdk_root.join('sdk')
      env['ANDROID_HOME'] = sdk_root.join('sdk')
      env['ANDROID_NDK_PATH'] = sdk_root.join('ndk')
    self.gradle_cache(env, env_prefixes, version)

  def gradle_cache(self, env, env_prefixes, version):
    # Specify the location of the shared cache used by Gradle builds.
    # This cache contains dependencies downloaded from network when a Gradle task is run.
    # When a cache hit occurs, the dependency is immediately provided to the Gradle build.
    env['GRADLE_USER_HOME'] = self.m.path['cache'].join('gradle')
    # Disable the Gradle daemon. Some builders aren't ephemeral, which means that state leaks out potentially
    # leaving the bot in a bad state.
    # For more, see CI section on https://docs.gradle.org/current/userguide/gradle_daemon.html#sec:disabling_the_daemon
    env['GRADLE_OPTS'] = '-Dorg.gradle.daemon=false'

  def arm64ruby(self, env, env_prefixes, gem_dir):
    """Installs arm64 Ruby.

    Context of arm64ruby:
      go/benchmarks-on-platforms
      https://github.com/flutter/flutter/issues/87508
    """
    version = 'version:311_3'
    with self.m.step.nest('Install arm64ruby'):
      ruby_path = self.m.path['cache'].join('ruby')
      ruby = self.m.cipd.EnsureFile()
      ruby.add_package('flutter/ruby/mac-arm64', version)
      self.m.cipd.ensure(ruby_path, ruby)
      paths = env_prefixes.get('PATH', [])
      paths.insert(0, ruby_path.join('bin'))
      env['RUBY_HOME'] = ruby_path.join('bin')
      env['GEM_HOME'] = gem_dir.join('ruby', '3.1.0')
      paths.append(gem_dir.join('ruby', '3.1.0', 'bin'))
      env_prefixes['PATH'] = paths

  def gems(self, env, env_prefixes, gemfile_dir):
    """Installs mac gems.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      gemfile_dir(Path): The path to the location of the repository gemfile.
    """
    deps_list = self.m.properties.get('dependencies', [])
    deps = [d['dependency'] for d in deps_list]
    if 'gems' not in deps:
      # Noop if gems property is not set.
      return
    gem_file = self.m.repo_util.sdk_checkout_path().join('flutter')
    gem_dir = self.m.path['start_dir'].join('gems')
    env['GEM_HOME'] = gem_dir
    if self.m.platform.arch == 'arm':
      self.arm64ruby(env, env_prefixes, gem_dir)
    with self.m.step.nest('Install gems'):
      self.m.file.ensure_directory('mkdir gems', gem_dir)
      # Temporarily install bundler
      with self.m.context(cwd=gem_dir):
        self.m.step(
            'install bundler',
            ['gem', 'install', 'bundler', '--install-dir', '.'],
            infra_step=True,
        )
      paths = env_prefixes.get('PATH', [])
      temp_paths = copy.deepcopy(paths)
      temp_paths.append(gem_dir.join('bin'))
      env_prefixes['PATH'] = temp_paths
      with self.m.context(env=env, env_prefixes=env_prefixes, cwd=gemfile_dir):
        self.m.step(
            'set gems path',
            ['bundle', 'config', 'set', 'path', gem_dir],
            infra_step=True,
        )
        self.m.step('install gems', ['bundler', 'install'], infra_step=True)
      # Update envs to the final destination.
      self.m.file.listdir('list bundle', gem_dir, recursive=True)
      if self.m.platform.arch != 'arm':
        env['GEM_HOME'] = gem_dir.join('ruby', '2.6.0')
        paths.append(gem_dir.join('ruby', '2.6.0', 'bin'))
      env_prefixes['PATH'] = paths

  def firebase(self, env, env_prefixes, version='latest'):
    """Installs firebase binary.

    This dependency is only supported in linux.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
    """
    firebase_dir = self.m.path['start_dir'].join('firebase')
    self.m.file.ensure_directory('ensure directory', firebase_dir)
    with self.m.step.nest('Install firebase'):
      self.m.step(
          'Install firebase bin',
          [
              'curl', '-Lo',
              firebase_dir.join('firebase'),
              'https://firebase.tools/bin/linux/latest'
          ],
          infra_step=True,
      )
      self.m.step(
          'Set execute permission',
          ['chmod', '755', firebase_dir.join('firebase')],
          infra_step=True,
      )
    paths = env_prefixes.get('PATH', [])
    paths.append(firebase_dir)
    env_prefixes['PATH'] = paths

  def clang(self, env, env_prefixes, version=None):
    """Installs clang toolchain.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
    """
    version = version or 'git_revision:7e9747b50bcb1be28d4a3236571e8050835497a6'
    clang_path = self.m.path['cache'].join('clang')
    clang = self.m.cipd.EnsureFile()
    clang.add_package('fuchsia/third_party/clang/${platform}', version)
    with self.m.step.nest('Install clang'):
      self.m.cipd.ensure(clang_path, clang)
    paths = env_prefixes.get('PATH', [])
    paths.append(clang_path.join('bin'))
    env_prefixes['PATH'] = paths

  def cmake(self, env, env_prefixes, version=None):
    """Installs cmake.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
    """
    version = version or 'version:3.16.1'
    cmake_path = self.m.path['cache'].join('cmake')
    cmake = self.m.cipd.EnsureFile()
    cmake.add_package('infra/cmake/${platform}', version)
    with self.m.step.nest('Install cmake'):
      self.m.cipd.ensure(cmake_path, cmake)
    paths = env_prefixes.get('PATH', [])
    paths.append(cmake_path.join('bin'))
    env_prefixes['PATH'] = paths

  def codesign(self, env, env_prefixes, version=None):
    """Installs codesign at https://chrome-infra-packages.appspot.com/p/flutter/codesign.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict): Current environment prefixes variables.
    """
    if version != 'latest':
        msg = 'codesign version is None.'
        raise ValueError(msg)
    version = version or 'latest'
    codesign_path = self.m.path.mkdtemp().join('codesign')
    codesign = self.m.cipd.EnsureFile()
    codesign.add_package('flutter/codesign/${platform}', version)
    with self.m.step.nest('Installing Mac codesign CIPD pkg'):
      self.m.cipd.ensure(codesign_path, codesign)
    paths = env_prefixes.get('PATH', [])
    paths.append(codesign_path)
    env_prefixes['PATH'] = paths

  def cosign(self, env, env_prefixes, version=None):
    """Installs cosign.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict): Current environment prefixes variables.
    """
    version = version or 'latest'
    cosign_path = self.m.path['cache'].join('cosign')
    cosign = self.m.cipd.EnsureFile()
    cosign.add_package('flutter/tools/cosign/${platform}', version)
    with self.m.step.nest('Install cosign'):
      self.m.cipd.ensure(cosign_path, cosign)
    paths = env_prefixes.get('PATH', [])
    paths.append(cosign_path.join('bin'))
    env_prefixes['PATH'] = paths

  def ninja(self, env, env_prefixes, version=None):
    """Installs ninja.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
    """
    version = version or 'version:1.9.0'
    ninja_path = self.m.path['cache'].join('ninja')
    ninja = self.m.cipd.EnsureFile()
    ninja.add_package("infra/ninja/${platform}", version)
    with self.m.step.nest('Install ninja'):
      self.m.cipd.ensure(ninja_path, ninja)
    paths = env_prefixes.get('PATH', [])
    paths.append(ninja_path)
    env_prefixes['PATH'] = paths

  def dart_sdk(self, env, env_prefixes, version=None):
    """Installs dart sdk.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
    """
    version = version or 'stable'
    dart_sdk_path = self.m.path['cache'].join('dart_sdk')
    dart_sdk = self.m.cipd.EnsureFile()
    dart_sdk.add_package("dart/dart-sdk/${platform}", version)
    with self.m.step.nest('Install dart sdk'):
      self.m.cipd.ensure(dart_sdk_path, dart_sdk)
    paths = env_prefixes.get('PATH', [])
    paths.insert(0, dart_sdk_path)
    env_prefixes['PATH'] = paths

  def certs(self, env, env_prefixes, version=None):
    """Installs root certificates for windows.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
    """
    if not self.m.platform.is_win:
      # noop for non windows platforms.
      return
    version = version or 'latest'
    certs_path = self.m.path['cache'].join('certs')
    certs = self.m.cipd.EnsureFile()
    certs.add_package("flutter_internal/certs", version)
    with self.m.step.nest('Install certs'):
      self.m.cipd.ensure(certs_path, certs)
    paths = env_prefixes.get('PATH', [])
    paths.insert(0, certs_path)
    env_prefixes['PATH'] = paths
    with self.m.context(env=env, env_prefixes=env_prefixes, cwd=certs_path):
      self.m.step(
          'Install Certs',
          [
              'powershell.exe',
              certs_path.join('install.ps1'),
          ],
      )

  def vs_build(self, env, env_prefixes, version=None):
    """Installs visual studio build.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
    """
    if not self.m.platform.is_win:
      # noop for non windows platforms.
      return
    version = version or 'latest'
    vs_path = self.m.path['cache'].join('vsbuild')
    vs = self.m.cipd.EnsureFile()
    vs.add_package("flutter_internal/windows/vsbuild", version)
    with self.m.step.nest('Install VSBuild'):
      self.m.cipd.ensure(vs_path, vs)
    paths = env_prefixes.get('PATH', [])
    paths.insert(0, vs_path)
    env_prefixes['PATH'] = paths
    with self.m.context(env=env, env_prefixes=env_prefixes, cwd=vs_path):
      self.m.step(
          'Install VS build',
          ['powershell.exe', vs_path.join('install.ps1')],
      )

  def apple_signing(self, env, env_prefixes, version=None):
    """Sets up mac for code signing.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
    """
    with self.m.step.nest('Prepare code signing'):
      self.m.step(
          'unlock login keychain',
          ['unlock_login_keychain.sh'],
          infra_step=True,
      )
      # See go/googler-flutter-signing about how to renew the Apple development
      # certificate and provisioning profile.
      env['FLUTTER_XCODE_CODE_SIGN_STYLE'] = 'Manual'
      env['FLUTTER_XCODE_DEVELOPMENT_TEAM'] = 'S8QB4VV633'
      env['FLUTTER_XCODE_PROVISIONING_PROFILE_SPECIFIER'
         ] = 'match Development *'

  def jazzy(self, env, env_prefixes, version=None):
    """Installs mac Jazzy.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      gemfile_dir(Path): The path to the location of the repository gemfile.
    """
    version = version or '0.9.5'
    gem_dir = self.m.path['start_dir'].join('gems')
    with self.m.step.nest('Install jazzy'):
      self.m.file.ensure_directory('mkdir gems', gem_dir)
      with self.m.context(cwd=gem_dir):
        # TODO: Un-pin sqlite3 version.
        # https://github.com/flutter/flutter/issues/111226

        # The next minor release of `sqlite3-ruby`, 1.5.0, caused build issues,
        # so 1.4.4 is pinned. A proper fix should remove this step, as jazzy
        # attempts to install sqlite3 on its own.
        # https://github.com/flutter/flutter/issues/111193
        self.m.step(
            'install sqlite3', [
                'gem', 'install', 'sqlite3:1.4.4',
            '--install-dir', '.'
            ]
        )
        self.m.step(
            'install jazzy', [
                'gem', 'install', 'jazzy:%s' % version,
            '--install-dir', '.'
            ]
        )
      env['GEM_HOME'] = gem_dir
      paths = env_prefixes.get('PATH', [])
      temp_paths = copy.deepcopy(paths)
      temp_paths.append(gem_dir.join('bin'))
      env_prefixes['PATH'] = temp_paths

  def android_virtual_device(self, env, env_prefixes, version=None):
    """Installs and starts an android avd emulator.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      version: Android API version of the avd.
    """
    avd_root = self.m.path['cache'].join('avd')
    self.m.android_virtual_device.download(avd_root, env, env_prefixes, version)

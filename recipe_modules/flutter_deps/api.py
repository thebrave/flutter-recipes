# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy
from recipe_engine import recipe_api


class FlutterDepsApi(recipe_api.RecipeApi):
  """Utilities to install flutter build/test dependencies at runtime."""

  def flutter_engine(self, env, env_prefixes):
    """Sets the local engine related information to environment variables.

    If the drone is started to run the tests with a local engine, it will
    contain a `local_engine_cas_hash` property where we can download engine files.
    If the `local_engine` property is present, it will override the
    default build configuration name, "host_debug_unopt"

    Similarly, if the drone is started to run the tests against a local web
    sdk, it will contain a `local_web_sdk_cas_hash` property.
    If the `local_web_sdk` property is present, it will override the default
    build configuration name, "wasm_release"

    These files will be located in the build folder, whose name comes
    from the build configuration.
    Args:

      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
    """
    # No-op if `local_engine_cas_hash` property is empty
    cas_hash = self.m.properties.get('local_engine_cas_hash')
    if cas_hash:
      checkout_engine = self.m.path['cleanup'].join('builder', 'src', 'out')
      # Download built engines from CAS.
      if cas_hash:
        self.m.cas.download(
            'Download engine from CAS', cas_hash, checkout_engine
        )
      local_engine = checkout_engine.join(self.m.properties.get('local_engine'))
      local_engine_host = self.m.properties.get('local_engine_host')
      dart_bin = local_engine.join('dart-sdk', 'bin')
      paths = env_prefixes.get('PATH', [])
      paths.insert(0, dart_bin)
      env_prefixes['PATH'] = paths
      env['LOCAL_ENGINE'] = local_engine
      env['LOCAL_ENGINE_HOST'] = local_engine_host

    web_sdk_cas_hash = self.m.properties.get('local_web_sdk_cas_hash')
    local_web_sdk = self.m.properties.get('local_web_sdk')
    if web_sdk_cas_hash:
      checkout_src = self.m.path['cleanup'].join('builder', 'src')
      self.m.cas.download(
          'Download web sdk from CAS', web_sdk_cas_hash, checkout_src
      )
      local_web_sdk = checkout_src.join('out', local_web_sdk or 'wasm_release')
      dart_bin = checkout_src.join(
          'flutter', 'prebuilts', '${platform}', 'dart-sdk', 'bin'
      )
      paths = env_prefixes.get('PATH', [])
      paths.insert(0, dart_bin)
      env_prefixes['PATH'] = paths
      env['LOCAL_WEB_SDK'] = local_web_sdk

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
        'arm_tools': self.arm_tools,
        'certs': self.certs,
        'chrome_and_driver': self.chrome_and_driver,
        'clang': self.clang,
        'cmake': self.cmake,
        'codesign': self.codesign,
        'cosign': self.cosign,
        'curl': self.curl,
        'dart_sdk': self.dart_sdk,
        'dashing': self.dashing,
        'doxygen': self.doxygen,
        'firebase': self.firebase,
        'firefox': self.firefox,
        'gh_cli': self.gh_cli,
        'go_sdk': self.go_sdk,
        'goldctl': self.goldctl,
        'gradle_cache': self.gradle_cache,
        'ios_signing':
            self.
            apple_signing,  # TODO(drewroen): Remove this line once ios_signing is not being referenced
        'ninja': self.ninja,
        'open_jdk': self.open_jdk,
        'ruby': self.ruby,
        'vs_build': self.vs_build,
    }
    parsed_deps = []
    for dep in deps:
      dependency = dep.get('dependency')
      version = dep.get('version')
      # Ensure there are no duplicate entries
      if dependency in parsed_deps:
        msg = '''Dependency {} is duplicated
            Ensure ci.yaml contains only one entry for this target
            '''.format(dependency)
        raise ValueError(msg)
      parsed_deps.append(dependency)
      if dependency in ['xcode']:
        continue
      dep_funct = available_deps.get(dependency)
      if not dep_funct:
        msg = '''Dependency {} not available.
            Ensure ci.yaml contains one of the following supported keys:
            {}
            If this is a new dependency, update https://cs.opensource.google/flutter/recipes/+/main:recipe_modules/flutter_deps/api.py
            '''.format(dependency, available_deps.keys())
        raise ValueError(msg)
      dep_funct(env, env_prefixes, version)

  def android_virtual_device(self, env, env_prefixes, version):
    """Simply sets the version of the emulator globally as the module will download the package itself.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      version(str): The OpenJdk version to install.
    """
    env['USE_EMULATOR'] = True
    env['EMULATOR_VERSION'] = version

  def open_jdk(self, env, env_prefixes, version):
    """Downloads OpenJdk CIPD package and updates environment variables.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      version(str): The OpenJdk version to install.
    """
    version = version or 'version:11'
    with self.m.step.nest('OpenJDK dependency'):
      java_cache_dir = self.m.path['cache'].join('java')
      self.m.cipd.ensure(
          java_cache_dir,
          self.m.cipd.EnsureFile().add_package(
              'flutter/java/openjdk/${platform}', version
          )
      )
      java_home = java_cache_dir
      if self.m.platform.is_mac:
        java_home = java_cache_dir.join('contents', 'Home')

      env['JAVA_HOME'] = java_home
      path = env_prefixes.get('PATH', [])
      path.append(java_home.join('bin'))
      env_prefixes['PATH'] = path

  def arm_tools(self, env, env_prefixes, version=None):
    """Downloads Arm Tools CIPD package and updates environment variables.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      version(str): The Arm Tools version to install.
    """
    version = version or 'last_updated:2023-02-03T15:32:01-0800'
    with self.m.step.nest('Arm Tools dependency'):
      arm_tools_cache_dir = self.m.path['cache'].join('arm-tools')
      self.m.cipd.ensure(
          self.m.path['cache'],
          self.m.cipd.EnsureFile().add_package(
              'flutter_internal/tools/arm-tools', version
          )
      )
      self.m.file.listdir('arm-tools contents', arm_tools_cache_dir)
      self.m.file.listdir(
          'arm-tools malioc contents',
          arm_tools_cache_dir.join('mali_offline_compiler')
      )
      env['ARM_TOOLS'] = arm_tools_cache_dir
      env['MALIOC_PATH'] = arm_tools_cache_dir.join(
          'mali_offline_compiler', 'malioc'
      )

  def goldctl(self, env, env_prefixes, version):
    """Downloads goldctl from CIPD and updates the environment variables.

    To roll to a new version of goldctl visit this page:

    https://chrome-infra-packages.appspot.com/p/skia/tools/goldctl

    Select linux-amd64 and click on a package marked "latest". In the "Tags"
    section find the freshest tag prefixed with `git_revision`. Copy the value
    of the tag including "git_revision:" and the SHA following it, for example:

    git_revision:somelongshacontainingnumbersandletters12

    Then replace the default value of `version` variable in this function with
    it.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      version(str): The goldctl version to install.
    """
    version = version or 'git_revision:720a542f6fe4f92922c3b8f0fdcc4d2ac6bb83cd'
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
        if version.count('.') == 1:
          # This is the old mac path for vanilla Chromium, which is expressed
          # as just a major and minor version (e.g. 117.0)
          exec_path = chrome_path.join(
              'chrome-mac', 'Chromium.app', 'Contents', 'MacOS', 'Chromium'
          )
        else:
          # Google Chrome For Testing path, which is usually expressed with a
          # four part version number (e.g. 117.0.5938.149)
          exec_path = chrome_path.join(
              'Google Chrome for Testing.app', 'Contents', 'MacOS',
              'Google Chrome for Testing'
          )
        env['CHROME_EXECUTABLE'] = exec_path
      else:
        env['CHROME_EXECUTABLE'] = chrome_path.join(binary_name)

  def firefox(self, env, env_prefixes, version):
    """Downloads Firefox from CIPD and updates the environment variables.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      version(str): The Firefox version to install.
    """
    version = version or 'latest'
    with self.m.step.nest('Firefox dependency'):
      firefox_path = self.m.path['cache'].join('firefox')
      pkgs = self.m.cipd.EnsureFile()
      pkgs.add_package('flutter_internal/browsers/firefox/${platform}', version)
      self.m.cipd.ensure(firefox_path, pkgs)
      paths = env_prefixes.get('PATH', [])
      paths.append(firefox_path)
      env_prefixes['PATH'] = paths
      env['FIREFOX_EXECUTABLE'] = firefox_path.join('firefox')

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
    go_path = self.m.path['cache'].join('go')
    go = self.m.cipd.EnsureFile()
    go.add_package('infra/3pp/tools/go/${platform}', version)
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
    version = version or '0.4.0'
    self.go_sdk(env, env_prefixes, 'version:2@1.19.3')
    with self.m.context(env=env, env_prefixes=env_prefixes):
      self.m.step(
          'Install dashing',
          ['go', 'install',
           'github.com/technosophos/dashing@%s' % version],
          infra_step=True,
      )

  def doxygen(self, _, env_prefixes, version):
    """Installs doxygen."""
    version = version or 'latest'
    doxygen_path = self.m.path.mkdtemp().join('doxygen')
    doxygen = self.m.cipd.EnsureFile()
    doxygen.add_package('flutter/doxygen/${platform}', version)
    self.m.cipd.ensure(doxygen_path, doxygen)
    paths = env_prefixes.get('PATH', [])
    paths.append(doxygen_path.join('bin'))
    env_prefixes['PATH'] = paths

  def curl(self, _, env_prefixes, version):
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
    if (version == 'version:29.0'):  # Handle the legacy case
      env['ANDROID_SDK_ROOT'] = sdk_root
      env['ANDROID_HOME'] = sdk_root
      env['ANDROID_NDK_PATH'] = sdk_root.join('ndk-bundle')
    else:
      env['ANDROID_SDK_ROOT'] = sdk_root.join('sdk')
      env['ANDROID_HOME'] = sdk_root.join('sdk')
      env['ANDROID_NDK_PATH'] = sdk_root.join('ndk')
    android_tmp = self.m.path.mkdtemp()
    env['ANDROID_SDK_HOME'] = android_tmp
    env['ANDROID_USER_HOME'] = android_tmp.join('.android')
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
    cmake_path = self.m.path['cache'].join('cmake')
    cmake = self.m.cipd.EnsureFile()
    version = version or 'build_id:8787856497187628321'
    cmake.add_package('infra/3pp/tools/cmake/${platform}', version)
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
    version = version or 'latest'
    codesign_path = self.m.path.mkdtemp()
    codesign = self.m.cipd.EnsureFile()
    codesign.add_package('flutter/codesign/${platform}', version)
    with self.m.step.nest('Installing Mac codesign CIPD pkg'):
      self.m.cipd.ensure(codesign_path, codesign)
    paths = env_prefixes.get('PATH', [])
    paths.append(codesign_path)
    env_prefixes['PATH'] = paths
    return codesign_path.join('codesign')

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
      # Unlock keychain for devicelab tasks.
      if self.m.test_utils.is_devicelab_bot():
        self.m.step(
            'unlock login keychain',
            ['unlock_login_keychain.sh'],
            infra_step=True,
        )
      # Download and copy provisiong profile to default location for Chromium Host only bots.
      else:
        version = version or 'latest'
        mobileprovision_path = self.m.path.mkdtemp().join('mobileprovision')
        mobileprovision = self.m.cipd.EnsureFile()
        mobileprovision.add_package(
            'flutter_internal/mac/mobileprovision/${platform}', version
        )
        with self.m.step.nest('Installing Mac mobileprovision'):
          self.m.cipd.ensure(mobileprovision_path, mobileprovision)

        mobileprovision_profile = mobileprovision_path.join(
            'development.mobileprovision'
        )
        copy_script = self.resource('copy_mobileprovisioning_profile.sh')
        self.m.step('Set execute permission', ['chmod', '755', copy_script])
        self.m.step(
            'copy mobileprovisioning profile',
            [copy_script, mobileprovision_profile]
        )

      # See go/googler-flutter-signing about how to renew the Apple development
      # certificate and provisioning profile.
      env['FLUTTER_XCODE_CODE_SIGN_STYLE'] = 'Manual'
      env['FLUTTER_XCODE_DEVELOPMENT_TEAM'] = 'S8QB4VV633'
      env['FLUTTER_XCODE_PROVISIONING_PROFILE_SPECIFIER'
         ] = 'match Development *'

  # pylint: disable=unused-argument
  def ruby(self, env, env_prefixes, version=None):
    """Installs a self contained Ruby.

   Args:
     env(dict): Current environment variables.
     env_prefixes(dict):  Current environment prefixes variables.
    """
    version = version or 'latest'
    with self.m.step.nest('Install ruby'):
      ruby_path = self.m.path['cache'].join('ruby')
      ruby = self.m.cipd.EnsureFile()
      ruby.add_package('flutter/ruby/${platform}', version)
      self.m.cipd.ensure(ruby_path, ruby)
      paths = env_prefixes.get('PATH', [])
      paths.insert(0, ruby_path.join('bin'))
      env_prefixes['PATH'] = paths

  def contexts(self):
    """Available contexts across recipes repository."""
    return {
        'metric_center_token': self.m.token_util.metric_center_token,
        'android_virtual_device': self.m.android_virtual_device,
        'osx_sdk': self.m.osx_sdk,
        'osx_sdk_devicelab': self.m.osx_sdk,
        'depot_tools_on_path': self.m.depot_tools.on_path,
    }

  def enter_contexts(self, exit_stack, contexts, env, env_prefixes):
    """Enter corresponding contexts to exit_stack.

    Args:
      exit_stack(ExitStack): Context manager for dynamic management of a stack of exit callbacks.
      contexts(list): List of required contexts.
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
    """
    available_contexts = self.contexts()
    params = (env, env_prefixes)
    for context in contexts:
      aux_params = params
      if context == 'osx_sdk':
        aux_params = ('ios',)
      if context == 'osx_sdk_devicelab':
        aux_params = ('ios', True)
      if context == 'android_virtual_device':
        aux_params = params + (env['EMULATOR_VERSION'],)  # pragma: nocover
      if context == 'depot_tools_on_path':
        aux_params = tuple()
      exit_stack.enter_context(available_contexts[context](*aux_params))

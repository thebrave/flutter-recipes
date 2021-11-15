# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for engine repository tests."""

import contextlib
import copy

from recipe_engine import recipe_api

from PB.recipes.flutter.engine import InputProperties
from PB.recipes.flutter.engine import EnvProperties

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'depot_tools/depot_tools',
    'depot_tools/gclient',
    'flutter/display_util',
    'flutter/flutter_deps',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/repo_util',
    'flutter/retry',
    'flutter/shard_util',
    'flutter/test_utils',
    'flutter/web_util',
    'fuchsia/cas_util',
    'fuchsia/goma',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/runtime',
    'recipe_engine/step',
    'recipe_engine/swarming',
]

GIT_REPO = (
    'https://chromium.googlesource.com/external/github.com/flutter/engine'
)

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties


@contextlib.contextmanager
def SetupXcode(api):
  # See cr-buildbucket.cfg for how the version is passed in.
  # https://github.com/flutter/infra/blob/master/config/cr-buildbucket.cfg#L148
  with api.osx_sdk('ios'):
    yield


def Build(api, config, *targets):
  checkout = GetCheckoutPath(api)
  build_dir = checkout.join('out/%s' % config)
  goma_jobs = api.properties['goma_jobs']
  ninja_args = [api.depot_tools.ninja_path, '-j', goma_jobs, '-C', build_dir]
  ninja_args.extend(targets)
  with api.goma.build_with_goma():
    name = 'build %s' % ' '.join([config] + list(targets))
    api.step(name, ninja_args)


def Archive(api, target):
  checkout = GetCheckoutPath(api)
  build_dir = checkout.join('out', target)
  cas_dir = api.path.mkdtemp('cas-directory')
  cas_engine = cas_dir.join(target)
  api.file.copytree('Copy host_debug_unopt', build_dir, cas_engine)
  return api.cas_util.upload(cas_dir, step_name='Archive Flutter Engine Test CAS')


def RunGN(api, *args):
  checkout = GetCheckoutPath(api)
  gn_cmd = ['python', checkout.join('flutter/tools/gn'), '--goma']
  gn_cmd.extend(args)
  api.step('gn %s' % ' '.join(args), gn_cmd)


def GetCheckoutPath(api):
  return api.path['cache'].join('builder', 'src')


def CleanUpProcesses(api):
  # This is to clean up leaked processes.
  api.os_utils.kill_processes()
  # Collect memory/cpu/process after task execution.
  api.os_utils.collect_os_info()


def RunSteps(api, properties, env_properties):
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()
  """Steps to checkout flutter engine and execute web tests."""
  cache_root = api.path['cache'].join('builder')
  checkout = GetCheckoutPath(api)

  if properties.clobber:
    api.file.rmtree('Clobber cache', cache_root)
  api.file.rmtree('Clobber build output', checkout.join('out'))

  api.file.ensure_directory('Ensure checkout cache', cache_root)
  api.goma.ensure()
  dart_bin = checkout.join(
      'third_party', 'dart', 'tools', 'sdks', 'dart-sdk', 'bin'
  )

  android_home = checkout.join('third_party', 'android_tools', 'sdk')

  env = {
      'GOMA_DIR': api.goma.goma_dir,
      'ANDROID_HOME': str(android_home),
      'CHROME_NO_SANDBOX': 'true',
      'ENGINE_PATH': cache_root,
      'FLUTTER_PREBUILT_DART_SDK': 'True',
  }
  env_prefixes = {'PATH': [dart_bin]}

  api.flutter_deps.certs(env, env_prefixes)

  # Enable long path support on Windows.
  api.os_utils.enable_long_paths()

  # Checkout source code and build
  api.repo_util.engine_checkout(cache_root, env, env_prefixes)

  # Ensure required deps are installed
  api.flutter_deps.required_deps(
      env, env_prefixes, api.properties.get('dependencies', [])
  )

  if api.platform.is_mac:
    api.web_util.clone_goldens_repo(checkout)

  with api.context(cwd=cache_root, env=env,
                   env_prefixes=env_prefixes), api.depot_tools.on_path():

    api.gclient.runhooks()

    target_name = 'host_debug_unopt'
    gn_flags = ['--unoptimized', '--full-dart-sdk', '--prebuilt-dart-sdk']
    # Mac needs to install xcode as part of the building process.
    additional_args = []
    felt_cmd = [
        checkout.join('out', target_name, 'dart-sdk', 'bin', 'dart'),
        'dev/felt.dart'
    ]

    cas_hash = ''
    builds = []
    if api.platform.is_linux:
      RunGN(api, *gn_flags)
      Build(api, target_name)
      # Archieve the engine. Start the drones. Due to capacity limits we are
      # Only using the drones on the Linux for now.
      # Archive build directory into CAS.
      cas_hash = Archive(api, target_name)
      # Schedule builds.
      # TODO(nurhan): Currently this recipe only shards Linux. The web drones
      # recipe is written in a way that it can also support sharding for
      # macOS and Windows OSes. When more resources are available or when
      # MWE or WWE builders start running more than 1 hour, also shard those
      # builders.
      builds = schedule_builds_on_linux(api, cas_hash)
    elif api.platform.is_mac:
      with SetupXcode(api):
        RunGN(api, *gn_flags)
        Build(api, target_name)
        additional_args = ['--browser', 'ios-safari']
    else:
      # Platform = windows.
      RunGN(api, *gn_flags)
      Build(api, target_name)
      if api.platform.is_win:
        felt_cmd = [
            checkout.join(
                'flutter', 'lib', 'web_ui', 'dev', 'felt_windows.bat'
            )
        ]

    # Update dart packages and run tests.
    local_pub = checkout.join('out', target_name, 'dart-sdk', 'bin', 'pub')
    with api.context(
        cwd=checkout.join('flutter', 'web_sdk', 'web_engine_tester')):
      api.step('pub get in web_engine_tester', [local_pub, 'get'])
    with api.context(cwd=checkout.join('flutter', 'lib', 'web_ui')):
      api.step('pub get in web_engine_tester', [local_pub, 'get'])
      # TODO(nurhan): carry licenses to another shard when we have more
      # resources.
      felt_licenses = copy.deepcopy(felt_cmd)
      felt_licenses.append('check-licenses')
      api.step('felt licenses', felt_licenses)
      if api.platform.is_mac:
        additional_args_safari_desktop = ['--browser', 'safari']
        felt_test_safari_desktop = copy.deepcopy(felt_cmd)
        felt_test_safari_desktop.append('test')
        felt_test_safari_desktop.extend(additional_args_safari_desktop)
        api.retry.step(
            api.test_utils.test_step_name('felt test safari desktop'),
            felt_test_safari_desktop
        )
      if api.platform.is_linux:
        # TODO(nurhan): Web engine analysis can also be part of felt and used
        # in a shard.
        web_engine_analysis_cmd = [
            checkout.join(
                'flutter', 'lib', 'web_ui', 'dev', 'web_engine_analysis.sh'
            ),
        ]
        api.step('web engine analysis', web_engine_analysis_cmd)
        builds = api.shard_util.collect_builds(builds)
        api.display_util.display_builds(
            step_name='display builds',
            builds=builds,
            raise_on_failure=True,
        )
        CleanUpProcesses(api)
      elif api.platform.is_mac:
        with SetupXcode(api):
          with recipe_api.defer_results():
            felt_test = copy.deepcopy(felt_cmd)
            felt_test.append('test')
            felt_test.extend(additional_args)
            api.step(
                api.test_utils.test_step_name('felt ios-safari test'), felt_test
            )
            api.web_util.upload_failing_goldens(checkout, 'ios-safari')
            CleanUpProcesses(api)
      else:
        api.web_util.chrome(checkout)
        felt_test = copy.deepcopy(felt_cmd)
        felt_test.append('test')
        felt_test.extend(additional_args)
        api.step(api.test_utils.test_step_name('felt test chrome'), felt_test)
        CleanUpProcesses(api)


def schedule_builds_on_linux(api, cas_hash):
  """Schedules one subbuild per subshard."""
  reqs = []

  # For running Chrome Unit tests:
  command_name = 'chrome-unit-linux'
  # These are the required dependencies.
  web_dependencies = ['chrome', 'goldens_repo']
  # These are the felt commands which will be used.
  command_args = ['test', '--browser=chrome']
  addShardTask(
      api, reqs, command_name, web_dependencies, command_args, cas_hash
  )

  # For running Firefox Unit tests:
  command_name = 'firefox-unit-linux'
  # We don't need extra dependencies since felt tools handles firefox itself.
  # TODO(nurhan): Use cipd packages for Firefox. As we are doing for chrome
  # still respect to the version from browser_lock.yaml.
  web_dependencies = []
  # These are the felt commands which will be used.
  command_args = ['test', '--browser=firefox']
  addShardTask(
      api, reqs, command_name, web_dependencies, command_args, cas_hash
  )

  return api.buildbucket.schedule(reqs)


def addShardTask(
    api, reqs, command_name, web_dependencies, command_args, cas_hash
):
  # These are dependencies specified in the yaml file. We want to pass them down
  # to drones so they also install these dependencies.
  inherited_dependencies = [{'dependency': d['dependency']} for d in api.properties.get('dependencies', [])]
  drone_props = {
      'command_name': command_name, 'web_dependencies': web_dependencies,
      'command_args': command_args, 'local_engine_cas_hash': cas_hash,
      'inherited_dependencies': inherited_dependencies,
  }

  git_url = GIT_REPO
  git_ref = api.buildbucket.gitiles_commit.ref
  if 'git_url' in api.properties and 'git_ref' in api.properties:
    git_url = api.properties['git_url']
    git_ref = api.properties['git_ref']

  drone_props['git_url'] = git_url
  if not git_ref:
    drone_props['git_ref'] = 'refs/heads/master'
  else:
    drone_props['git_ref'] = git_ref

  req = api.buildbucket.schedule_request(
      swarming_parent_run_id=api.swarming.task_id,
      builder='Linux Web Drone',
      properties=drone_props,
      priority=25
  )
  reqs.append(req)


def GenTests(api):
  browser_yaml_file = {
      'required_driver_version': {'chrome': 84},
      'chrome': {'Linux': '768968', 'Mac': '768985', 'Win': '768975'}
  }
  golden_yaml_file = {'repository': 'repo', 'revision': 'b6efc758'}
  yield api.test('linux-post-submit') + api.properties(
      goma_jobs='200'
  ) + api.platform('linux', 64) + api.runtime(is_experimental=False)
  yield api.test(
      'windows-post-submit',
      api.step_data(
          'read browser lock yaml.parse', api.json.output(browser_yaml_file)
      ), api.properties(goma_jobs='200'), api.platform('win', 64)
  ) + api.runtime(is_experimental=False)
  yield api.test(
      'mac-post-submit',
      api.step_data('read yaml.parse', api.json.output(golden_yaml_file)),
      api.properties(goma_jobs='200'), api.platform('mac', 64)
  ) + api.runtime(is_experimental=False)
  yield api.test('linux-pre-submit') + api.properties(
      goma_jobs='200',
      git_url='https://mygitrepo',
      git_ref='refs/pull/1/head',
      gcs_goldens_bucket='mybucket',
      clobber=True
  ) + api.platform('linux', 64) + api.runtime(is_experimental=False)

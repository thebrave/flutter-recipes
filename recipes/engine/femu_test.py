# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager

from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from google.protobuf import struct_pb2

import re

DEPS = [
    'depot_tools/depot_tools',
    'flutter/repo_util',
    'flutter/retry',
    'flutter/shard_util_v2',
    'flutter/ssh',
    'flutter/test_utils',
    'flutter/yaml',
    'fuchsia/cas_util',
    'flutter/goma',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties
# FFX is still a little bit flaky sometimes. A temporary workaround will be to
# retry the tests multiple times if they fail.
MAX_RETRIES = 3


def GetCheckoutPath(api):
  return api.path['cache'].join('builder', 'src')


def GetEmulatorArch(api):
  arch = api.properties.get('emulator_arch', 'x64')
  if arch not in ['arm64', 'x64']:
    api.step.StepWarning('invalid architecture: %s - defaulting to x64' % arch)
    return 'x64'
  return arch


def Build(api, config, *targets):
  checkout = GetCheckoutPath(api)
  build_dir = checkout.join('out/%s' % config)
  goma_jobs = api.properties['goma_jobs']
  ninja_path = checkout.join('flutter', 'third_party', 'ninja', 'ninja')
  ninja_args = [ninja_path, '-j', goma_jobs, '-C', build_dir]
  ninja_args.extend(targets)
  with api.goma():
    name = 'build %s' % ' '.join([config] + list(targets))
    api.step(name, ninja_args)


def GetFlutterFuchsiaBuildTargets(product, include_test_targets=False):
  targets = ['flutter/shell/platform/fuchsia:fuchsia']
  if include_test_targets:
    targets += ['fuchsia_tests']
  return targets


def BuildAndTestFuchsia(api, build_script, git_rev):
  arch = GetEmulatorArch(api)
  # Prepares build files for debug/JIT Fuchsia
  RunGN(
      api, '--fuchsia', '--fuchsia-cpu', arch, '--runtime-mode', 'debug',
      '--no-lto'
  )
  # Prepares build files for profile/AOT Fuchsia
  RunGN(
      api, '--fuchsia', '--fuchsia-cpu', arch, '--runtime-mode', 'profile',
      '--no-lto'
  )
  # Builds debug/JIT Fuchsia
  Build(
      api, 'fuchsia_debug_%s' % arch,
      *GetFlutterFuchsiaBuildTargets(False, True)
  )
  # Builds profile/AOT Fuchsia
  Build(
      api, 'fuchsia_profile_%s' % arch,
      *GetFlutterFuchsiaBuildTargets(False, True)
  )

  # Package the build artifacts.
  #
  # We pass --skip-build here to take the existing artifacts that have been built
  # and package them. This will not build fuchsia artifacts despite the name of
  # the build_script being build_fuchsia_artifacts.
  #
  # TODO(akbiggs): Clean this up if we feel brave.
  fuchsia_debug_package_cmd = [
      'python3',
      build_script,
      '--engine-version',
      git_rev,
      '--skip-build',
      '--archs',
      arch,
      '--runtime-mode',
      'debug',
  ]
  fuchsia_profile_package_cmd = [
      'python3', build_script, '--engine-version', git_rev, '--skip-build',
      '--archs', arch, '--runtime-mode', 'profile', '--skip-remove-buckets'
  ]
  api.step('package Debug/JIT Fuchsia Artifacts', fuchsia_debug_package_cmd)
  api.step('package Profile/AOT Fuchsia Artifacts', fuchsia_profile_package_cmd)
  TestFuchsiaFEMU(api)


def RunGN(api, *args):
  checkout = GetCheckoutPath(api)
  gn_cmd = ['python3', checkout.join('flutter/tools/gn'), '--goma']
  gn_cmd.extend(args)
  # Run with goma_dir context.
  env = {'GOMA_DIR': api.goma.goma_dir}
  with api.context(env=env):
    api.step('gn %s' % ' '.join(args), gn_cmd)


def GetFuchsiaBuildId(api):
  checkout = GetCheckoutPath(api)
  manifest_path = checkout.join(
      'fuchsia', 'sdk', 'linux', 'meta', 'manifest.json'
  )
  manifest_data = api.file.read_json('read manifest', manifest_path)
  return manifest_data['id']


def CasRoot(api):
  """Create a CAS containing flutter test components and fuchsia runfiles for FEMU."""
  sdk_version = GetFuchsiaBuildId(api)
  checkout = GetCheckoutPath(api)
  root_dir = api.path.mkdtemp('femu_runfiles_')
  cas_tree = api.file.symlink_tree(root=root_dir)
  test_suites = []

  def add(src, name_rel_to_root):
    # CAS requires the files to be located directly inside the root folder.
    cas_tree.register_link(
        target=src,
        linkname=cas_tree.root.join(name_rel_to_root),
    )

  def addFlutterTests():
    arch = GetEmulatorArch(api)
    add(
        checkout.join(
            'out', 'fuchsia_bucket', 'flutter', arch, 'debug', 'aot',
            'flutter_aot_runner-0.far'
        ), 'flutter_aot_runner-0.far'
    )
    test_suites_file = checkout.join(
        'flutter', 'testing', 'fuchsia', 'test_suites.yaml'
    )

    for suite in api.yaml.read('retrieve list of test suites', test_suites_file,
                               api.json.output()).json.output:
      # Default behavior is to run all tests on x64 if "emulator_arch" isn't present
      # If "emulator_arch" is present, we run based on the emulator_arch specified
      # x64 - femu_test.py
      # arm64 - arm_femu_test.py
      if arch not in suite.get('emulator_arch', ['x64']):
        continue

      # Ensure command is well-formed.
      # See https://fuchsia.dev/fuchsia-src/concepts/packages/package_url.
      match = re.match(
          r'^(test run) (?P<test_far_file>fuchsia-pkg://[0-9a-z\-_\.]+/(?P<name>[0-9a-z\-_\.]+)#meta/[0-9a-z\-_\.]+(\.cm|\.cmx))( +[0-9a-zA-Z\-_*\.: =]+)?$',
          suite['test_command']
      )
      if not match:
        raise api.step.StepFailure(
            'Invalid test command: %s' % suite['test_command']
        )

      suite['name'] = match.group('name')
      suite['run_with_dart_aot'] = 'run_with_dart_aot' in suite and suite[
          'run_with_dart_aot'] == 'true'
      suite['test_far_file'] = match.group('test_far_file')

      if 'packages' not in suite:
        suite['packages'] = [suite['package']]
      suite['package_basenames'] = []
      for path in suite['packages']:
        # Captures the FAR name (long/path/to/far/file/actual_far.far would output actual_far.far)
        basename = re.match(r'(:?.*/)*([^/]*$)', path).group(2)
        suite['package_basenames'].append(basename)
        if suite['run_with_dart_aot']:
          add(checkout.join('out', 'fuchsia_profile_%s' % arch, path), basename)
        else:
          add(checkout.join('out', 'fuchsia_debug_%s' % arch, path), basename)
      test_suites.append(suite)

  addFlutterTests()

  cas_tree.create_links("create tree of runfiles")
  cas_hash = api.cas_util.upload(
      cas_tree.root, step_name='archive FEMU Run Files'
  )
  return test_suites, root_dir, cas_hash


def RunTestSuiteOnFfxEmuImpl(api, suite, ffx, arch, pb_path):
  # Launch the emulator
  emu_cmd = [ffx, '-v', 'emu', 'start', pb_path, '--headless']
  if arch == 'arm64':
    api.step(
        'launch arm64 emulator with QEMU engine', emu_cmd +
        ['--engine', 'qemu', '--headless', '--startup-timeout', '360']
    )
  else:
    api.step('launch x64 emulator', emu_cmd)

  # Output information for current emulator
  # Contains version, product information, etc.
  api.step('list all targets in the collection', [ffx, 'target', 'list'])
  api.step('retrieve femu information', [ffx, 'target', 'show'])
  ffx_repo_list_json = api.step(
      'get repository information',
      [ffx, '--machine', 'json', 'repository', 'list'],
      stdout=api.json.output()
  ).stdout
  ffx_blob_repo_path = ffx_repo_list_json[0]['spec']['blob_repo_path']

  for package in suite['package_basenames']:
    api.step(
        'ffx repository publish {}'.format(package), [
            ffx, 'repository', 'publish', pb_path, '--package-archive', package,
            '--blob-repo-dir', ffx_blob_repo_path
        ]
    )

  api.step('start FFX repository', [ffx, 'repository', 'server', 'start'])
  api.step(
      'Register repository',
      [ffx, 'target', 'repository', 'register', '--alias', 'fuchsia.com']
  )

  # Run the actual test
  # Test command is guaranteed to be well-formed
  # TODO(http://fxb/121613): Emulator instances are not cleaned up
  # when tests fail. Added a clean up step before tests start to
  # stop all running emulators.
  api.retry.step('run ffx test', [ffx] + suite['test_command'].split(' '))


def ReadLogFiles(api, ffx):
  """
  Read the log files generated by ffx and by the Fuchsia emulator and present
  them in the test result page.
  """
  with api.step.nest('logs') as dump_step:
    dump_step.presentation.logs['target_logs'] = api.step(
        'dump target log', [ffx, 'log', 'dump'],
        stdout=api.raw_io.output_text()
    ).stdout
    dump_step.presentation.logs['ffx_daemon_log'] = api.file.read_text(
        'read ffx daemon log',
        api.path.join(
            api.context.env.get('FFX_ISOLATE_DIR'), 'cache', 'logs',
            'ffx.daemon.log'
        )
    )
    dump_step.presentation.logs['ffx_log'] = api.file.read_text(
        'read ffx log',
        api.path.join(
            api.context.env.get('FFX_ISOLATE_DIR'), 'cache', 'logs', 'ffx.log'
        )
    )
    dump_step.presentation.logs['emulator_log'] = api.file.read_text(
        'read ffx emulator log',
        api.path.join(
            api.context.env.get('FFX_ISOLATE_DIR'), 'data', 'emu', 'instances',
            'fuchsia-emulator', 'emulator.log'
        )
    )
    dump_step.presentation.logs['emulator_serial_log'] = api.file.read_text(
        'read ffx serial log',
        api.path.join(
            api.context.env.get('FFX_ISOLATE_DIR'), 'data', 'emu', 'instances',
            'fuchsia-emulator', 'emulator.log.serial'
        )
    )


def CleanupAfterTestRun(api, ffx, arch):
  ReadLogFiles(api, ffx)
  # Cleans up running processes to prevent clashing with future test runs
  api.step('stop FFX repository', [ffx, 'repository', 'server', 'stop'])
  api.step('stop {} emulator'.format(arch), [ffx, '-v', 'emu', 'stop', '--all'])


def RunTestSuiteOnFfxEmu(api, suite, ffx, arch, pb_path):
  """
  Run the Fuchsia test suite |suite| on the Fuchsia emulator, using ffx.
  """
  for attempt in range(MAX_RETRIES):
    step_name = 'run %s' % suite['name']
    if attempt != 0:
      step_name += ' (attempt #%d)' % (attempt + 1)
    with api.step.nest(step_name):
      try:
        return RunTestSuiteOnFfxEmuImpl(api, suite, ffx, arch, pb_path)
      except api.step.StepFailure as ex:
        if attempt == MAX_RETRIES - 1:
          raise
      finally:
        CleanupAfterTestRun(api, ffx, arch)


def TestFuchsiaFEMU(api):
  """Run flutter tests on FEMU."""
  test_suites, root_dir, cas_hash = CasRoot(api)
  arch = GetEmulatorArch(api)
  checkout = GetCheckoutPath(api)

  ffx = checkout.join('fuchsia/sdk/linux/tools/x64/ffx')

  with api.context(cwd=root_dir), api.step.nest('Set FFX config'):
    # Conditionally enable ffx's CSO flag
    if api.properties.get('enable_cso', False):
      api.step(
          'enable CSO in ffx', [ffx, 'config', 'set', 'overnet.cso', 'enabled']
      )
    else:
      api.step(
          'disable CSO in ffx',
          [ffx, 'config', 'set', 'overnet.cso', 'disabled']
      )

    # Disable ffx analytics so this does not count as a real user
    api.step('disable ffx analytics', [ffx, 'config', 'analytics', 'disable'])

    # Set the log level to debug to help investigate failures.
    api.step('set logging level', [ffx, 'config', 'set', 'log.level', 'debug'])

  # Pick up new config change
  api.step('restart ffx daemon', [ffx, 'daemon', 'stop'])
  # TODO(fxb/121613). Workaround for the issue of previously running
  # emulator.
  api.step('list emulators', [ffx, 'emu', 'list'])
  api.step('stop all emulator instances', [ffx, 'emu', 'stop', '--all'])

  # Fuchsia LSC runs will override the remote SDK and product bundles that
  # should be used for the tests. The path to the product bundle is passed
  # through the `gclient_variables`.
  pb_override_path = api.properties.get('gclient_variables', {}
                                       ).get('product_bundles_v2_path', None)
  if pb_override_path:
    gs_bucket = 'fuchsia-artifacts'
    with api.step.nest('parse external sdk id'):
      sdk_id = re.search(
          r'^development/(?P<sdk_id>\d+)/product_bundles.json', pb_override_path
      ).group('sdk_id')
  else:
    # Read the sdk version; this is necessary to get the right product bundle
    gs_bucket = 'fuchsia'
    sdk_id = api.step(
        'read sdk version', [ffx, 'sdk', 'version'],
        stdout=api.raw_io.output_text()
    ).stdout.strip()

  # Lookup the product bundle
  # qemu-x64 has been merged into x64, but other arches still have qemu-specific
  # builds published.
  product_name = 'terminal.%s' % arch if arch == 'x64' else 'terminal.qemu-%s' % arch
  product_transfer_manifest = api.step(
      'lookup %s product bundle' % product_name, [
          ffx, '--machine', 'json-pretty', 'product', 'lookup',
          product_name, sdk_id, '--base-url',
          'gs://%s/development/%s' % (gs_bucket, sdk_id)
      ],
      stdout=api.json.output(),
  ).stdout['transfer_manifest_url']

  local_pb = '/tmp/local_pb'

  # Retrieve the required product bundle and store in a temporary directory
  # Contains necessary images, packages, etc to launch the emulator
  api.step(
      'download %s product bundle' % product_name, [
          ffx, 'product', 'download', product_transfer_manifest, local_pb,
          '--force'
      ]
  )

  # Add the product bundle's repository
  api.step(
      'add product bundle repository',
      [ffx, '--config', 'ffx-repo-add=true', 'repository', 'add', local_pb]
  )

  with api.context(cwd=root_dir), api.step.nest('run FEMU test on %s' % arch):
    for suite in test_suites:
      RunTestSuiteOnFfxEmu(api, suite, ffx, arch, local_pb)

  api.file.rmtree('delete product bundle', local_pb)


def BuildFuchsia(api):
  """
  Schedules release builds for x64 on other bots, and then builds the x64 runners
  (which do not require LTO and thus are faster to build).

  On Linux, we also run tests for the runner against x64, and if they fail
  we cancel the scheduled builds.
  """
  checkout = GetCheckoutPath(api)
  build_script = str(
      checkout.join('flutter/tools/fuchsia/build_fuchsia_artifacts.py')
  )
  git_rev = api.buildbucket.gitiles_commit.id or 'HEAD'
  BuildAndTestFuchsia(api, build_script, git_rev)


def RunSteps(api, properties, env_properties):
  cache_root = api.buildbucket.builder_cache_path
  checkout = GetCheckoutPath(api)
  api.file.rmtree('clobber build output', checkout.join('out'))
  api.file.ensure_directory('ensure checkout cache', cache_root)
  dart_bin = checkout.join(
      'third_party', 'dart', 'tools', 'sdks', 'dart-sdk', 'bin'
  )

  ffx_isolate_dir = api.path.mkdtemp('ffx_isolate_files')

  env = {
      'FFX_ISOLATE_DIR': ffx_isolate_dir,
  }
  env_prefixes = {'PATH': [dart_bin]}

  api.repo_util.engine_checkout(cache_root, env, env_prefixes)

  # Various scripts we run assume access to depot_tools on path for `ninja`.
  with api.context(cwd=cache_root, env=env,
                   env_prefixes=env_prefixes), api.depot_tools.on_path():
    if api.platform.is_linux and api.properties.get('build_fuchsia', True):
      BuildFuchsia(api)


############ RECIPE TEST ############


def GenTests(api):
  output_props = struct_pb2.Struct()
  output_props['cas_output_hash'] = 'deadbeef'
  build = api.buildbucket.try_build_message(
      builder='FEMU Test', project='flutter'
  )
  build.output.CopyFrom(build_pb2.Build.Output(properties=output_props))

  def ffx_repo_list_step_data(step_name):
    return api.step_data(
        step_name,
        stdout=api.json.output([{
            "name": "devhost.fuchsia.com",
            "spec": {
                "type": "file_system",
                "metadata_repo_path": "/tmp/local_pb/repository",
                "blob_repo_path": "/tmp/local_pb/blobs",
                "aliases": ["fuchsia.com",],
            },
        }]),
        retcode=0
    )

  def ffx_repo_list_step_data_with_retries(base_step_name, retry_count):
    ret = []
    for i in range(retry_count):
      if i == 0:
        step_name = base_step_name + '.get repository information'
      else:
        step_name = base_step_name + (
            ' (attempt #%d).get repository information' % (i + 1)
        )
      ret.append(ffx_repo_list_step_data(step_name))
    return tuple(ret)

  def fail_step_with_retries(base_step_name, step_suffix):
    return (
        api.step_data(base_step_name + '.' + step_suffix, retcode=1),
        api.step_data(
            base_step_name + ' (attempt #2).' + step_suffix, retcode=1
        ),
        api.step_data(
            base_step_name + ' (attempt #3).' + step_suffix, retcode=1
        )
    )

  yield api.test(
      'start_femu',
      api.properties(
          InputProperties(
              goma_jobs='1024',
              build_fuchsia=True,
              test_fuchsia=True,
              git_url='https://github.com/flutter/engine',
              git_ref='refs/pull/1/head',
              clobber=False,
          ),
          clobber=False,
      ),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
              'package':
                  'v2_test-123.far',
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm -- --gtest_filter=-ParagraphTest.*:a.b'
          }, {
              'package':
                  'v1_test_component-321.far',
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/v1_test_component#meta/v1_test_component.cmx -ParagraphTest.*:a.b'
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text(
              '''# This is a comment.
- package: v2_test-123.far
  test_command: test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm -- --gtest_filter=-ParagraphTest.*:a.b

# Legacy cfv1 test
- package: v1_test_component-321.far
  test_command: test run fuchsia-pkg://fuchsia.com/v1_test_component#meta/v1_test_component.cmx -ParagraphTest.*:a.b'''
          )
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.step_data(
          'read sdk version',
          stdout=api.raw_io.output_text('ARBITRARY_SDK_VERSION'),
      ),
      api.step_data(
          'lookup terminal.x64 product bundle',
          stdout=api.json.output({
              'name': 'terminal.x64',
              'transfer_manifest_url': 'gs://path/to/transfer_manifest.json',
          }),
      ),
      *fail_step_with_retries(
          'run FEMU test on x64.run v2_test', 'launch x64 emulator'
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
      status='FAILURE'
  )

  yield api.test(
      'femu_with_package_list',
      api.properties(
          InputProperties(
              goma_jobs='1024',
              build_fuchsia=True,
              test_fuchsia=True,
              git_url='https://github.com/flutter/engine',
              git_ref='refs/pull/1/head',
              clobber=False,
          ),
          clobber=False,
      ),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm -- --gtest_filter=-ParagraphTest.*:a.b',
              'packages': ['v2_test-123.far']
          }, {
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/v1_test_component#meta/v1_test_component.cmx -ParagraphTest.*:a.b',
              'packages': ['v1_test_component-321.far']
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text(
              '''# This is a comment.
- test_command: test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm -- --gtest_filter=-ParagraphTest.*:a.b
  packages:
    - v2_test-123.far

# Legacy cfv1 test
- test_command: test run fuchsia-pkg://fuchsia.com/v1_test_component#meta/v1_test_component.cmx -ParagraphTest.*:a.b
  packages:
    - v1_test_component-321.far'''
          )
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.step_data(
          'read sdk version',
          stdout=api.raw_io.output_text('ARBITRARY_SDK_VERSION'),
      ),
      api.step_data(
          'lookup terminal.x64 product bundle',
          stdout=api.json.output({
              'name': 'terminal.x64',
              'transfer_manifest_url': 'gs://path/to/transfer_manifest.json',
          }),
      ),
      *ffx_repo_list_step_data_with_retries(
          'run FEMU test on x64.run v2_test', MAX_RETRIES
      ),
      *fail_step_with_retries(
          'run FEMU test on x64.run v2_test',
          'ffx repository publish v2_test-123.far'
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
      status='FAILURE'
  )

  yield api.test(
      'multiple_non_root_fars',
      api.properties(
          InputProperties(
              goma_jobs='1024',
              build_fuchsia=True,
              test_fuchsia=True,
              git_url='https://github.com/flutter/engine',
              git_ref='refs/pull/1/head',
              clobber=False,
          ),
          clobber=False,
      ),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/flutter-embedder-test#meta/flutter-embedder-test.cmx',
              'packages': [
                  'flutter-embedder-test-0.far',
                  'gen/flutter/shell/platform/fuchsia/flutter/integration_flutter_tests/embedder/child-view/child-view/child-view.far',
                  'gen/flutter/shell/platform/fuchsia/flutter/integration_flutter_tests/embedder/parent-view/parent-view/parent-view.far'
              ]
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text(
              '''# This is a comment.
- test_command: test run fuchsia-pkg://fuchsia.com/flutter-embedder-test#meta/flutter-embedder-test.cmx
  packages:
    - flutter-embedder-test-0.far
    - gen/flutter/shell/platform/fuchsia/flutter/integration_flutter_tests/embedder/child-view/child-view/child-view.far
    - gen/flutter/shell/platform/fuchsia/flutter/integration_flutter_tests/embedder/parent-view/parent-view/parent-view.far'''
          )
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.step_data(
          'read sdk version',
          stdout=api.raw_io.output_text('ARBITRARY_SDK_VERSION'),
      ),
      api.step_data(
          'lookup terminal.x64 product bundle',
          stdout=api.json.output({
              'name': 'terminal.x64',
              'transfer_manifest_url': 'gs://path/to/transfer_manifest.json',
          }),
      ),
      *ffx_repo_list_step_data_with_retries(
          'run FEMU test on x64.run flutter-embedder-test', 2
      ),
      api.step_data(
          'run FEMU test on x64.run flutter-embedder-test.ffx repository publish flutter-embedder-test-0.far',
          retcode=1
      ),
      api.step_data(
          'run FEMU test on x64.run flutter-embedder-test (attempt #2).ffx repository publish flutter-embedder-test-0.far',
          retcode=0
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
  )

  yield api.test(
      'no_zircon_file',
      api.properties(
          InputProperties(
              goma_jobs='1024',
              build_fuchsia=True,
              test_fuchsia=True,
              git_url='https://github.com/flutter/engine',
              git_ref='refs/pull/1/head',
              vdl_version='g3-revision:vdl_fuchsia_xxxxxxxx_RC00',
              clobber=False,
          ),
          clobber=False,
      ),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
              'package':
                  'v2_test-123.far',
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm'
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text(
              """# This is a comment.
- package: v2_test-123.far
  test_command: test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm"""
          )
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.step_data(
          'read sdk version',
          stdout=api.raw_io.output_text('ARBITRARY_SDK_VERSION'),
      ),
      api.step_data(
          'lookup terminal.x64 product bundle',
          stdout=api.json.output({
              'name': 'terminal.x64',
              'transfer_manifest_url': 'gs://path/to/transfer_manifest.json',
          }),
      ),
      ffx_repo_list_step_data(
          'run FEMU test on x64.run v2_test.get repository information'
      ),
  )

  yield api.test(
      'dangerous_test_commands',
      api.properties(
          InputProperties(
              goma_jobs='1024',
              build_fuchsia=True,
              test_fuchsia=True,
              git_url='https://github.com/flutter/engine',
              git_ref='refs/pull/1/head',
              clobber=False,
          ),
          clobber=False,
      ),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
              'package': 'ordinary_package1.far',
              'test_command': 'suspicious command'
          }, {
              'package':
                  'ordinary_package2.far',
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/ordinary_package2#meta/ordinary_package2.cmx; suspicious command'
          }, {
              'package':
                  'ordinary_package3.far',
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/ordinary_package3#meta/ordinary_package3.cmx $(suspicious command)'
          }, {
              'package':
                  'ordinary_package4.far',
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/ordinary_package4#meta/ordinary_package4.cmx `suspicious command`'
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text(
              '''
- package: ordinary_package1.far
  test_command: suspicious command
- package: ordinary_package2.far
  test_command: test run fuchsia-pkg://fuchsia.com/ordinary_package2#meta/ordinary_package2.cmx; suspicious command
- package: ordinary_package3.far
  test_command: test run fuchsia-pkg://fuchsia.com/ordinary_package3#meta/ordinary_package3.cmx $(suspicious command)
- package: ordinary_package4.far
  test_command: test run fuchsia-pkg://fuchsia.com/ordinary_package4#meta/ordinary_package4.cmx `suspicious command`'''
          )
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
      status='FAILURE'
  )

  yield api.test(
      'run_with_dart_aot_behavior',
      api.properties(
          InputProperties(
              goma_jobs='1024',
              build_fuchsia=True,
              test_fuchsia=True,
              git_url='https://github.com/flutter/engine',
              git_ref='refs/pull/1/head',
              clobber=False,
          ),
          clobber=False,
      ),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/dart-jit-runner-integration-test#meta/dart-jit-runner-integration-test.cm',
              'run_with_dart_aot':
                  'true',
              'packages': [
                  'dart-aot-runner-integration-test-0.far',
                  'dart_aot_runner-0.far',
                  'gen/flutter/shell/platform/fuchsia/dart_runner/tests/startup_integration_test/dart_jit_runner/dart_jit_echo_server/dart_jit_echo_server/dart_jit_echo_server.far'
              ]
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text(
              '''# This is a comment.
- test_command: test run fuchsia-pkg://fuchsia.com/dart-jit-runner-integration-test#meta/dart-jit-runner-integration-test.cm
  run_with_dart_aot: true
  packages:
    - dart-aot-runner-integration-test-0.far
    - dart_aot_runner-0.far
    - gen/flutter/shell/platform/fuchsia/dart_runner/tests/startup_integration_test/dart_jit_runner/dart_jit_echo_server/dart_jit_echo_server/dart_jit_echo_server.far'''
          )
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.step_data(
          'read sdk version',
          stdout=api.raw_io.output_text('ARBITRARY_SDK_VERSION'),
      ),
      api.step_data(
          'lookup terminal.x64 product bundle',
          stdout=api.json.output({
              'name': 'terminal.x64',
              'transfer_manifest_url': 'gs://path/to/transfer_manifest.json',
          }),
      ),
      ffx_repo_list_step_data(
          'run FEMU test on x64.run dart-jit-runner-integration-test.get repository information'
      ),
      api.step_data(
          'run FEMU test on x64.run dart-jit-runner-integration-test.ffx repository publish dart_aot_runner-0.far',
          retcode=0
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
  )

  yield api.test(
      'invalid_emulator_arch',
      api.properties(
          InputProperties(
              goma_jobs='1024',
              build_fuchsia=True,
              test_fuchsia=True,
              git_url='https://github.com/flutter/engine',
              git_ref='refs/pull/1/head',
              clobber=False,
              emulator_arch='x32'
          ),
      ),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
              'package':
                  'v2_test-123.far',
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm'
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text(
              """# This is a comment.
- package: v2_test-123.far
  test_command: test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm"""
          )
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.step_data(
          'read sdk version',
          stdout=api.raw_io.output_text('ARBITRARY_SDK_VERSION'),
      ),
      api.step_data(
          'lookup terminal.x64 product bundle',
          stdout=api.json.output({
              'name': 'terminal.x64',
              'transfer_manifest_url': 'gs://path/to/transfer_manifest.json',
          }),
      ),
      ffx_repo_list_step_data(
          'run FEMU test on x64.run v2_test.get repository information'
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
  )

  yield api.test(
      'run_on_test_specified_arch',
      api.properties(
          InputProperties(
              goma_jobs='1024',
              build_fuchsia=True,
              test_fuchsia=True,
              git_url='https://github.com/flutter/engine',
              git_ref='refs/pull/1/head',
              clobber=False,
          ),
      ),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/run-on-both-arch#meta/run-on-both-arch.cm',
              'packages': [
                  'dart-aot-runner-integration-test-0.far',
                  'dart_aot_runner-0.far',
              ], 'emulator_arch': [
                  'x64',
                  'arm64',
              ]
          }, {
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/only-run-on-arm64#meta/only-run-on-arm64',
              'packages': ['dart_aot_runner-0.far'], 'emulator_arch': ['arm64']
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text(
              '''# This is a comment.
- test_command: test run fuchsia-pkg://fuchsia.com/run-on-both-arch#meta/run-on-both-arch.cm
  run_with_dart_aot: true
  packages:
    - dart-aot-runner-integration-test-0.far
    - dart_aot_runner-0.far
  emulator_arch:
    - x64
    - arm64
- test_command: test run fuchsia-pkg://fuchsia.com/only-run-on-arm64#meta/only-run-on-arm64',
  packages:
    - dart_aot_runner-0.far'
  emulator_arch:
    - arm64'''
          )
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.step_data(
          'read sdk version',
          stdout=api.raw_io.output_text('ARBITRARY_SDK_VERSION'),
      ),
      api.step_data(
          'lookup terminal.x64 product bundle',
          stdout=api.json.output({
              'name': 'terminal.x64',
              'transfer_manifest_url': 'gs://path/to/transfer_manifest.json',
          }),
      ),
      ffx_repo_list_step_data(
          'run FEMU test on x64.run run-on-both-arch.get repository information'
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
  )

  yield api.test(
      'arm64_emulator_arch',
      api.properties(
          InputProperties(
              goma_jobs='1024',
              build_fuchsia=True,
              test_fuchsia=True,
              git_url='https://github.com/flutter/engine',
              git_ref='refs/pull/1/head',
              clobber=False,
              emulator_arch='arm64'
          ),
      ),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
              'package':
                  'v2_test-123.far',
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm',
              'emulator_arch': ['arm64']
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text(
              """# This is a comment.
- package: v2_test-123.far
  test_command: test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm
  emulator_arch:
    - arm64"""
          )
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.step_data(
          'read sdk version',
          stdout=api.raw_io.output_text('ARBITRARY_SDK_VERSION'),
      ),
      api.step_data(
          'lookup terminal.qemu-arm64 product bundle',
          stdout=api.json.output({
              'name': 'terminal.qemu-arm64',
              'transfer_manifest_url': 'gs://path/to/transfer_manifest.json',
          }),
      ),
      ffx_repo_list_step_data(
          'run FEMU test on arm64.run v2_test.get repository information'
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
  )

  yield api.test(
      'start_femu_with_cso',
      api.properties(
          InputProperties(
              goma_jobs='1024',
              build_fuchsia=True,
              test_fuchsia=True,
              git_url='https://github.com/flutter/engine',
              git_ref='refs/pull/1/head',
              clobber=False,
              enable_cso=True,
          ),
          clobber=False,
      ),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
              'package':
                  'v2_test-123.far',
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm -- --gtest_filter=-ParagraphTest.*:a.b'
          }, {
              'package':
                  'v1_test_component-321.far',
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/v1_test_component#meta/v1_test_component.cmx -ParagraphTest.*:a.b'
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text(
              '''# This is a comment.
- package: v2_test-123.far
  test_command: test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm -- --gtest_filter=-ParagraphTest.*:a.b

# Legacy cfv1 test
- package: v1_test_component-321.far
  test_command: test run fuchsia-pkg://fuchsia.com/v1_test_component#meta/v1_test_component.cmx -ParagraphTest.*:a.b'''
          )
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.step_data(
          'read sdk version',
          stdout=api.raw_io.output_text('ARBITRARY_SDK_VERSION'),
      ),
      api.step_data(
          'lookup terminal.x64 product bundle',
          stdout=api.json.output({
              'name': 'terminal.x64',
              'transfer_manifest_url': 'gs://path/to/transfer_manifest.json',
          }),
      ),
      *fail_step_with_retries(
          'run FEMU test on x64.run v2_test', 'launch x64 emulator'
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
      status='FAILURE'
  )

  yield api.test(
      'start_femu_with_override_pbm',
      api.properties(
          InputProperties(
              goma_jobs='1024',
              build_fuchsia=True,
              test_fuchsia=True,
              git_url='https://github.com/flutter/engine',
              git_ref='refs/pull/1/head',
              clobber=False,
              enable_cso=True,
              gclient_variables={
                  "download_fuchsia_sdk":
                      True,
                  "fuchsia_sdk_path":
                      "development/8787238722685733041/sdk/linux-amd64/core.tar.gz",
                  "product_bundles_v2_path":
                      "development/8776934483789347937/product_bundles.json"
              },
          ),
          clobber=False,
      ),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
              'package':
                  'v2_test-123.far',
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm -- --gtest_filter=-ParagraphTest.*:a.b'
          }, {
              'package':
                  'v1_test_component-321.far',
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/v1_test_component#meta/v1_test_component.cmx -ParagraphTest.*:a.b'
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text(
              '''# This is a comment.
- package: v2_test-123.far
  test_command: test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm -- --gtest_filter=-ParagraphTest.*:a.b

# Legacy cfv1 test
- package: v1_test_component-321.far
  test_command: test run fuchsia-pkg://fuchsia.com/v1_test_component#meta/v1_test_component.cmx -ParagraphTest.*:a.b'''
          )
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.step_data(
          'lookup terminal.x64 product bundle',
          stdout=api.json.output({
              'name': 'terminal.x64',
              'transfer_manifest_url': 'gs://path/to/transfer_manifest.json',
          }),
      ),
      *fail_step_with_retries(
          'run FEMU test on x64.run v2_test', 'launch x64 emulator'
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
      status='FAILURE'
  )

  yield api.test(
      'run_test_with_retry',
      api.properties(
          InputProperties(
              goma_jobs='1024',
              build_fuchsia=True,
              test_fuchsia=True,
              git_url='https://github.com/flutter/engine',
              git_ref='refs/pull/1/head',
              clobber=False,
          ),
      ),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/run-on-x64#meta/run-on-x64.cm',
              'packages': [
                  'dart-aot-runner-integration-test-0.far',
                  'dart_aot_runner-0.far',
              ], 'emulator_arch': ['x64',]
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text(
              '''# This is a comment.
- test_command: test run fuchsia-pkg://fuchsia.com/run-on-both-arch#meta/run-on-both-arch.cm
  run_with_dart_aot: true
  packages:
    - dart-aot-runner-integration-test-0.far
    - dart_aot_runner-0.far
  emulator_arch:
    - x64'''
          )
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.step_data(
          'read sdk version',
          stdout=api.raw_io.output_text('ARBITRARY_SDK_VERSION'),
      ),
      api.step_data(
          'lookup terminal.x64 product bundle',
          stdout=api.json.output({
              'name': 'terminal.x64',
              'transfer_manifest_url': 'gs://path/to/transfer_manifest.json',
          }),
      ),
      api.step_data(
          'run FEMU test on x64.run run-on-x64.launch x64 emulator', retcode=1
      ),
      api.step_data(
          'run FEMU test on x64.run run-on-x64 (attempt #2).launch x64 emulator',
          retcode=1
      ),
      ffx_repo_list_step_data(
          'run FEMU test on x64.run run-on-x64 (attempt #3).get repository information',
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
  )

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
    'flutter/sdk',
    'flutter/shard_util_v2',
    'flutter/ssh',
    'flutter/test_utils',
    'flutter/vdl',
    'flutter/yaml',
    'fuchsia/cas_util',
    'fuchsia/goma',
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
FSERVE_PORT = 8084


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
  with api.goma.build_with_goma():
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
  RunGN(api, '--fuchsia', '--fuchsia-cpu', arch, '--runtime-mode', 'debug',
        '--no-lto')
  # Prepares build files for profile/AOT Fuchsia
  RunGN(api, '--fuchsia', '--fuchsia-cpu', arch, '--runtime-mode', 'profile',
        '--no-lto')
  # Builds debug/JIT Fuchsia
  Build(api, 'fuchsia_debug_%s' % arch, *GetFlutterFuchsiaBuildTargets(False, True))
  # Builds profile/AOT Fuchsia
  Build(api, 'fuchsia_profile_%s' % arch, *GetFlutterFuchsiaBuildTargets(False, True))

  # Package the build artifacts.
  #
  # We pass --skip-build here to take the existing artifacts that have been built
  # and package them. This will not build fuchsia artifacts despite the name of
  # the build_script being build_fuchsia_artifacts.
  #
  # TODO(akbiggs): Clean this up if we feel brave.
  fuchsia_debug_package_cmd = [
      'python3', build_script, '--engine-version', git_rev, '--skip-build',
      '--archs', arch, '--runtime-mode', 'debug',
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
  api.step('gn %s' % ' '.join(args), gn_cmd)


def GetFuchsiaBuildId(api):
  checkout = GetCheckoutPath(api)
  manifest_path = checkout.join('fuchsia', 'sdk', 'linux', 'meta',
                                'manifest.json')
  manifest_data = api.file.read_json('read manifest', manifest_path)
  return manifest_data['id']


# TODO(yuanzhi) Move this logic to vdl recipe_module
def CasRoot(api):
  """Create a CAS containing flutter test components and fuchsia runfiles for FEMU."""
  sdk_version = GetFuchsiaBuildId(api)
  checkout = GetCheckoutPath(api)
  root_dir = api.path.mkdtemp('femu_runfiles_')
  cas_tree = api.cas_util.tree(root=root_dir)
  test_suites = []

  def add(src, name_rel_to_root):
    # CAS requires the files to be located directly inside the root folder.
    cas_tree.register_link(
        target=src,
        linkname=cas_tree.root.join(name_rel_to_root),
    )

  def addPackageFiles():
    fuchsia_packages = api.vdl.get_package_paths(sdk_version=sdk_version)
    add(fuchsia_packages.pm, api.path.basename(fuchsia_packages.pm))
    add(fuchsia_packages.amber_files,
        api.path.basename(fuchsia_packages.amber_files))

  def addImageFiles():
    ssh_files = api.vdl.gen_ssh_files()
    add(ssh_files.id_public, api.path.basename(ssh_files.id_public))
    add(ssh_files.id_private, api.path.basename(ssh_files.id_private))

    fuchsia_images = api.vdl.get_image_paths(sdk_version=sdk_version)
    add(fuchsia_images.build_args, "qemu_buildargs")
    add(fuchsia_images.kernel_file, "qemu_kernel")
    add(fuchsia_images.system_fvm, "qemu_fvm")
    add(api.sdk.sdk_path.join("tools", "x64", "far"), "far")
    add(api.sdk.sdk_path.join("tools", "x64", "fvm"), "fvm")
    add(api.sdk.sdk_path.join("tools", "x64", "symbolizer"), "symbolizer")

    ## Provision and add zircon-a
    authorized_zircona = api.buildbucket.builder_cache_path.join(
        'zircon-authorized.zbi')
    api.sdk.authorize_zbi(
        ssh_key_path=ssh_files.id_public,
        zbi_input_path=fuchsia_images.zircona,
        zbi_output_path=authorized_zircona,
    )
    add(authorized_zircona, "qemu_zircona-ed25519")

    ## Generate and add ssh_config
    ssh_config = api.buildbucket.builder_cache_path.join('ssh_config')
    api.ssh.generate_ssh_config(
        private_key_path=api.path.basename(ssh_files.id_private),
        dest=ssh_config)
    add(ssh_config, "ssh_config")

  def addFlutterTests():
    arch = GetEmulatorArch(api)
    add(
        checkout.join('out', 'fuchsia_bucket', 'flutter', arch, 'debug', 'aot',
                      'flutter_aot_runner-0.far'), 'flutter_aot_runner-0.far')
    test_suites_file = checkout.join(
      'flutter', 'testing', 'fuchsia', 'test_suites.yaml')

    for suite in api.yaml.read('retrieve list of test suites',
                      test_suites_file, api.json.output()).json.output:
      # Default behavior is to run all tests on x64 if "emulator_arch" isn't present
      # If "emulator_arch" is present, we run based on the emulator_arch specified
      # x64 - femu_test.py
      # arm64 - arm_femu_test.py
      if arch not in suite.get('emulator_arch', ['x64']):
        continue

      # Ensure command is well-formed.
      # See https://fuchsia.dev/fuchsia-src/concepts/packages/package_url.
      match = re.match(r'^(test run) (?P<test_far_file>fuchsia-pkg://[0-9a-z\-_\.]+/(?P<name>[0-9a-z\-_\.]+)#meta/[0-9a-z\-_\.]+(\.cm|\.cmx))( +[0-9a-zA-Z\-_*\.: =]+)?$', suite['test_command'])
      if not match:
        raise api.step.StepFailure('Invalid test command: %s' % suite['test_command'])

      suite['name'] = match.group('name')
      suite['run_with_dart_aot'] = 'run_with_dart_aot' in suite and suite['run_with_dart_aot'] == 'true'
      suite['test_far_file'] = match.group('test_far_file')

      if 'packages' not in suite:
        suite['packages'] = [ suite['package'] ]
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

  addPackageFiles()
  addImageFiles()
  addFlutterTests()

  cas_tree.create_links("create tree of runfiles")
  cas_hash = api.cas_util.upload(cas_tree.root, step_name='archive FEMU Run Files')
  return test_suites, root_dir, cas_hash


def TestFuchsiaFEMU(api):
  """Run flutter tests on FEMU."""
  test_suites, root_dir, cas_hash = CasRoot(api)
  arch = GetEmulatorArch(api)
  checkout = GetCheckoutPath(api)

  ffx = checkout.join('fuchsia/sdk/linux/tools/x64/ffx')
  fserve = checkout.join('fuchsia/sdk/linux/tools/x64/fserve')
  fpublish = checkout.join('fuchsia/sdk/linux/tools/x64/fpublish')

  api.step('disable ffx analytics', [ffx, 'config', 'analytics', 'disable'])

  # Retrieve the required product bundle
  # Contains necessary images, packages, etc to launch the emulator
  api.step('get terminal.qemu-%s product bundle' % arch,
            [ffx, 'product-bundle', 'get',
            'terminal.qemu-%s' % arch])

  with api.context(cwd=root_dir), api.step.nest('run FEMU test on %s' % arch):
    for suite in test_suites:
      with api.step.nest('run %s' % suite['name']):
        # Launch the emulator
        # Route the emulator_log to a temporary, defined path to output later
        emulator_log_path = api.path.mkstemp('emulator_log')
        if arch == 'arm64':
          launch_step = api.step(
              'launch arm64 emulator with QEMU engine', [
                  ffx, '-v', 'emu', 'start', 'terminal.qemu-arm64', '--engine',
                  'qemu', '--headless', '--startup-timeout', '360', '--log',
                  api.raw_io.output_text(
                      name='emulator_log', leak_to=emulator_log_path)
              ],
              step_test_data=(lambda: api.raw_io.test_api.output_text(
                  'log', name='emulator_log')))
        else:
          launch_step = api.step(
              'launch x64 emulator', [
                  ffx, '-v', 'emu', 'start', 'terminal.qemu-x64', '--headless',
                  '--log',
                  api.raw_io.output_text(
                      name='emulator_log', leak_to=emulator_log_path)
              ],
              step_test_data=(lambda: api.raw_io.test_api.output_text(
                  'log', name='emulator_log')))

        # Output information for current emulator
        # Contains version, product information, etc.
        api.step('retrieve femu information', [ffx, 'target', 'show']);

        # Start a package server, this listens in the background for published files
        # https://fuchsia.dev/reference/tools/sdk/fserve
        api.step(
            'start fserve',
            [fserve, '-image',
              'qemu-%s' % arch, '-server-port', FSERVE_PORT])

        # Publishes the required FAR files needed to run the test to the package server
        # https://fuchsia.dev/reference/tools/sdk/fpublish
        for package in suite['package_basenames']:
          api.step('publishing {}'.format(package), [fpublish, package])

        # Run the actual test
        # Test command is guaranteed to be well-formed
        with api.step.defer_results():
          api.retry.step('run ffx test', [ffx] + suite['test_command'].split(' '))

        # Outputs ffx log and emulator_log for debugging
        dump_step = api.step('ffx log dump', [ffx, 'log', 'dump'])
        # TODO(http://fxb/115447): Investigate why emulator_log isn't
        # outputting full emulator logs
        dump_step.presentation.logs[
          'emulator_log'] = launch_step.raw_io.output_texts['emulator_log']

        # Cleans up running processes to prevent clashing with future test runs
        api.step('kill fserve', [fserve, '-kill'])
        api.step('stop %s emulator' % arch, [ffx, '-v', 'emu', 'stop', '--all'])


def BuildFuchsia(api):
  """
  Schedules release builds for x64 on other bots, and then builds the x64 runners
  (which do not require LTO and thus are faster to build).

  On Linux, we also run tests for the runner against x64, and if they fail
  we cancel the scheduled builds.
  """
  checkout = GetCheckoutPath(api)
  build_script = str(
      checkout.join('flutter/tools/fuchsia/build_fuchsia_artifacts.py'))
  git_rev = api.buildbucket.gitiles_commit.id or 'HEAD'
  BuildAndTestFuchsia(api, build_script, git_rev)


def RunSteps(api, properties, env_properties):
  cache_root = api.buildbucket.builder_cache_path
  checkout = GetCheckoutPath(api)
  api.file.rmtree('clobber build output', checkout.join('out'))
  api.file.ensure_directory('ensure checkout cache', cache_root)
  api.goma.ensure()
  dart_bin = checkout.join('third_party', 'dart', 'tools', 'sdks', 'dart-sdk',
                           'bin')

  env = {'GOMA_DIR': api.goma.goma_dir}
  env_prefixes = {'PATH': [dart_bin]}

  api.repo_util.engine_checkout(cache_root, env, env_prefixes)

  # Various scripts we run assume access to depot_tools on path for `ninja`.
  with api.context(
      cwd=cache_root, env=env,
      env_prefixes=env_prefixes), api.depot_tools.on_path():
    if api.platform.is_linux and api.properties.get('build_fuchsia', True):
      BuildFuchsia(api)


############ RECIPE TEST ############


def GenTests(api):
  output_props = struct_pb2.Struct()
  output_props['cas_output_hash'] = 'deadbeef'
  build = api.buildbucket.try_build_message(
      builder='FEMU Test', project='flutter')
  build.output.CopyFrom(build_pb2.Build.Output(properties=output_props))

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
          ), clobber=False,),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
            'package': 'v2_test-123.far',
            'test_command': 'test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm -- --gtest_filter=-ParagraphTest.*:a.b'
          }, {
            'package': 'v1_test_component-321.far',
            'test_command': 'test run fuchsia-pkg://fuchsia.com/v1_test_component#meta/v1_test_component.cmx -ParagraphTest.*:a.b'
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text('''# This is a comment.
- package: v2_test-123.far
  test_command: test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm -- --gtest_filter=-ParagraphTest.*:a.b

# Legacy cfv1 test
- package: v1_test_component-321.far
  test_command: test run fuchsia-pkg://fuchsia.com/v1_test_component#meta/v1_test_component.cmx -ParagraphTest.*:a.b''')
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.step_data('run FEMU test on x64.run v2_test.launch x64 emulator', retcode=1),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
      api.platform('linux', 64),
      api.path.exists(
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/buildargs.gn'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/qemu-kernel.kernel'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/storage-full.blk'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/zircon-a.zbi'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/pm'),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/amber-files'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/qemu-x64.tar.gz'
          ),
          api.path['cache'].join('builder/ssh/id_ed25519.pub'),
          api.path['cache'].join('builder/ssh/id_ed25519'),
          api.path['cache'].join('builder/ssh/ssh_host_key.pub'),
          api.path['cache'].join('builder/ssh/ssh_host_key'),
      ),
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
          ), clobber=False,),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
            'test_command': 'test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm -- --gtest_filter=-ParagraphTest.*:a.b',
            'packages': [
              'v2_test-123.far'
            ]
          }, {
            'test_command': 'test run fuchsia-pkg://fuchsia.com/v1_test_component#meta/v1_test_component.cmx -ParagraphTest.*:a.b',
            'packages': [
              'v1_test_component-321.far'
            ]
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text('''# This is a comment.
- test_command: test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm -- --gtest_filter=-ParagraphTest.*:a.b
  packages:
    - v2_test-123.far

# Legacy cfv1 test
- test_command: test run fuchsia-pkg://fuchsia.com/v1_test_component#meta/v1_test_component.cmx -ParagraphTest.*:a.b
  packages:
    - v1_test_component-321.far''')
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.step_data('run FEMU test on x64.run v2_test.publishing v2_test-123.far', retcode=1),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
      api.platform('linux', 64),
      api.path.exists(
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/buildargs.gn'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/qemu-kernel.kernel'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/storage-full.blk'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/zircon-a.zbi'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/pm'),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/amber-files'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/qemu-x64.tar.gz'
          ),
          api.path['cache'].join('builder/ssh/id_ed25519.pub'),
          api.path['cache'].join('builder/ssh/id_ed25519'),
          api.path['cache'].join('builder/ssh/ssh_host_key.pub'),
          api.path['cache'].join('builder/ssh/ssh_host_key'),
      ),
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
          ), clobber=False,),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
            'test_command': 'test run fuchsia-pkg://fuchsia.com/flutter-embedder-test#meta/flutter-embedder-test.cmx',
            'packages': [
              'flutter-embedder-test-0.far',
              'gen/flutter/shell/platform/fuchsia/flutter/integration_flutter_tests/embedder/child-view/child-view/child-view.far',
              'gen/flutter/shell/platform/fuchsia/flutter/integration_flutter_tests/embedder/parent-view/parent-view/parent-view.far'
            ]
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text('''# This is a comment.
- test_command: test run fuchsia-pkg://fuchsia.com/flutter-embedder-test#meta/flutter-embedder-test.cmx
  packages:
    - flutter-embedder-test-0.far
    - gen/flutter/shell/platform/fuchsia/flutter/integration_flutter_tests/embedder/child-view/child-view/child-view.far
    - gen/flutter/shell/platform/fuchsia/flutter/integration_flutter_tests/embedder/parent-view/parent-view/parent-view.far''')
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.step_data('run FEMU test on x64.run flutter-embedder-test.publishing flutter-embedder-test-0.far', retcode=1),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
      api.platform('linux', 64),
      api.path.exists(
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/buildargs.gn'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/qemu-kernel.kernel'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/storage-full.blk'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/zircon-a.zbi'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/pm'),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/amber-files'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/qemu-x64.tar.gz'
          ),
          api.path['cache'].join('builder/ssh/id_ed25519.pub'),
          api.path['cache'].join('builder/ssh/id_ed25519'),
          api.path['cache'].join('builder/ssh/ssh_host_key.pub'),
          api.path['cache'].join('builder/ssh/ssh_host_key'),
      ),
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
          ), clobber=False,),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.platform('linux', 64),
      api.path.exists(
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/buildargs.gn'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/qemu-kernel.kernel'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/storage-full.blk'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/pm'),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/amber-files'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/qemu-x64.tar.gz'
          ),
          api.path['cache'].join('builder/ssh/id_ed25519.pub'),
          api.path['cache'].join('builder/ssh/id_ed25519'),
          api.path['cache'].join('builder/ssh/ssh_host_key.pub'),
          api.path['cache'].join('builder/ssh/ssh_host_key'),
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
          ), clobber=False,),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
            'package': 'ordinary_package1.far',
            'test_command': 'suspicious command'
          }, {
            'package': 'ordinary_package2.far',
            'test_command': 'test run fuchsia-pkg://fuchsia.com/ordinary_package2#meta/ordinary_package2.cmx; suspicious command'
          }, {
            'package': 'ordinary_package3.far',
            'test_command': 'test run fuchsia-pkg://fuchsia.com/ordinary_package3#meta/ordinary_package3.cmx $(suspicious command)'
          }, {
            'package': 'ordinary_package4.far',
            'test_command': 'test run fuchsia-pkg://fuchsia.com/ordinary_package4#meta/ordinary_package4.cmx `suspicious command`'
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text('''
- package: ordinary_package1.far
  test_command: suspicious command
- package: ordinary_package2.far
  test_command: test run fuchsia-pkg://fuchsia.com/ordinary_package2#meta/ordinary_package2.cmx; suspicious command
- package: ordinary_package3.far
  test_command: test run fuchsia-pkg://fuchsia.com/ordinary_package3#meta/ordinary_package3.cmx $(suspicious command)
- package: ordinary_package4.far
  test_command: test run fuchsia-pkg://fuchsia.com/ordinary_package4#meta/ordinary_package4.cmx `suspicious command`''')
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
      api.platform('linux', 64),
      api.path.exists(
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/buildargs.gn'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/qemu-kernel.kernel'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/storage-full.blk'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/zircon-a.zbi'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/pm'),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/amber-files'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/qemu-x64.tar.gz'
          ),
          api.path['cache'].join('builder/ssh/id_ed25519.pub'),
          api.path['cache'].join('builder/ssh/id_ed25519'),
          api.path['cache'].join('builder/ssh/ssh_host_key.pub'),
          api.path['cache'].join('builder/ssh/ssh_host_key'),
      ),
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
          ),  clobber=False,),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
            'test_command': 'test run fuchsia-pkg://fuchsia.com/dart-jit-runner-integration-test#meta/dart-jit-runner-integration-test.cm',
            'run_with_dart_aot': 'true',
            'packages': [
              'dart-aot-runner-integration-test-0.far',
              'dart_aot_runner-0.far',
              'gen/flutter/shell/platform/fuchsia/dart_runner/tests/startup_integration_test/dart_jit_runner/dart_jit_echo_server/dart_jit_echo_server/dart_jit_echo_server.far'
            ]
          }])
      ),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text('''# This is a comment.
- test_command: test run fuchsia-pkg://fuchsia.com/dart-jit-runner-integration-test#meta/dart-jit-runner-integration-test.cm
  run_with_dart_aot: true
  packages:
    - dart-aot-runner-integration-test-0.far
    - dart_aot_runner-0.far
    - gen/flutter/shell/platform/fuchsia/dart_runner/tests/startup_integration_test/dart_jit_runner/dart_jit_echo_server/dart_jit_echo_server/dart_jit_echo_server.far''')
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.step_data('run FEMU test on x64.run dart-jit-runner-integration-test.publishing dart_aot_runner-0.far', retcode=1),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
      api.platform('linux', 64),
      api.path.exists(
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/buildargs.gn'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/qemu-kernel.kernel'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/storage-full.blk'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/zircon-a.zbi'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/pm'),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/amber-files'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/qemu-x64.tar.gz'
          ),
          api.path['cache'].join('builder/ssh/id_ed25519.pub'),
          api.path['cache'].join('builder/ssh/id_ed25519'),
          api.path['cache'].join('builder/ssh/ssh_host_key.pub'),
          api.path['cache'].join('builder/ssh/ssh_host_key'),
      ),
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
          ),),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
              'package':
                  'v2_test-123.far',
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm'
          }])),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text("""# This is a comment.
- package: v2_test-123.far
  test_command: test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm""")),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
      api.platform('linux', 64),
      api.path.exists(
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/buildargs.gn'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/qemu-kernel.kernel'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/storage-full.blk'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/zircon-a.zbi'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/pm'),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/amber-files'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/qemu-x64.tar.gz'
          ),
          api.path['cache'].join('builder/ssh/id_ed25519.pub'),
          api.path['cache'].join('builder/ssh/id_ed25519'),
          api.path['cache'].join('builder/ssh/ssh_host_key.pub'),
          api.path['cache'].join('builder/ssh/ssh_host_key'),
      ),
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
        ),),
    api.step_data(
        'retrieve list of test suites.parse',
        api.json.output([{
          'test_command': 'test run fuchsia-pkg://fuchsia.com/run-on-both-arch#meta/run-on-both-arch.cm',
          'packages': [
            'dart-aot-runner-integration-test-0.far',
            'dart_aot_runner-0.far',
          ],
          'emulator_arch': [
            'x64',
            'arm64',
          ]
        },{
          'test_command': 'test run fuchsia-pkg://fuchsia.com/only-run-on-arm64#meta/only-run-on-arm64',
          'packages': [
            'dart_aot_runner-0.far'
          ],
          'emulator_arch': [
            'arm64'
          ]
        }])
    ),
    api.step_data(
        'retrieve list of test suites.read',
        api.file.read_text('''# This is a comment.
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
    - arm64''')
      ),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
      api.platform('linux', 64),
      api.path.exists(
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/buildargs.gn'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/qemu-kernel.kernel'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/storage-full.blk'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/zircon-a.zbi'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/pm'),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/amber-files'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/qemu-x64.tar.gz'
          ),
          api.path['cache'].join('builder/ssh/id_ed25519.pub'),
          api.path['cache'].join('builder/ssh/id_ed25519'),
          api.path['cache'].join('builder/ssh/ssh_host_key.pub'),
          api.path['cache'].join('builder/ssh/ssh_host_key'),
      ),
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
          ),),
      api.step_data(
          'retrieve list of test suites.parse',
          api.json.output([{
              'package':
                  'v2_test-123.far',
              'test_command':
                  'test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm',
              'emulator_arch': ['arm64']
          }])),
      api.step_data(
          'retrieve list of test suites.read',
          api.file.read_text("""# This is a comment.
- package: v2_test-123.far
  test_command: test run fuchsia-pkg://fuchsia.com/v2_test#meta/v2_test.cm
  emulator_arch:
    - arm64""")),
      api.step_data(
          'read manifest',
          api.file.read_json({'id': '0.20200101.0.1'}),
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
      api.platform('linux', 64),
      api.path.exists(
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/buildargs.gn'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/qemu-kernel.kernel'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/storage-full.blk'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/zircon-a.zbi'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/pm'),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/amber-files'
          ),
          api.path['cache'].join(
              'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/qemu-x64.tar.gz'
          ),
          api.path['cache'].join('builder/ssh/id_ed25519.pub'),
          api.path['cache'].join('builder/ssh/id_ed25519'),
          api.path['cache'].join('builder/ssh/ssh_host_key.pub'),
          api.path['cache'].join('builder/ssh/ssh_host_key'),
      ),
  )

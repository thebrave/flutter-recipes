# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager

from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from google.protobuf import struct_pb2, json_format

DEPS = [
    'depot_tools/depot_tools',
    'depot_tools/gclient',
    'depot_tools/gsutil',
    'flutter/archives',
    'flutter/bucket_util',
    'flutter/build_util',
    'flutter/display_util',
    'flutter/flutter_bcid',
    'flutter/flutter_deps',
    'flutter/goma',
    'flutter/logs_util',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/repo_util',
    'flutter/retry',
    'flutter/shard_util_v2',
    'flutter/test_utils',
    'flutter/zip',
    'fuchsia/gcloud',
    'recipe_engine/buildbucket',
    'recipe_engine/cas',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/futures',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/runtime',
    'recipe_engine/step',
    'recipe_engine/swarming',
]

# Account for ~1 hour queue time when there is a high number of commits.
DRONE_TIMEOUT_SECS = 7200

BUCKET_NAME = 'flutter_infra_release'
MAVEN_BUCKET_NAME = 'download.flutter.io'
FUCHSIA_ARTIFACTS_BUCKET_NAME = 'fuchsia-artifacts-release'
FUCHSIA_ARTIFACTS_DEBUG_NAMESPACE = 'debug'
ICU_DATA_PATH = 'third_party/icu/flutter/icudtl.dat'
GIT_REPO = (
    'https://flutter.googlesource.com/mirrors/engine'
)

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties

IMPELLERC_SHADER_LIB_PATH = 'shader_lib'


# Relative paths used to mock paths for testing.
MOCK_JAR_PATH = (
    'io/flutter/x86_debug/'
    '1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/'
    'x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.jar'
)
MOCK_POM_PATH = (
    'io/flutter/x86_debug/'
    '1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/'
    'x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.pom'
)

# Used for mock paths
DIRECTORY = 'DIRECTORY'


def UploadArtifact(api, config, platform, artifact_name):
  path = GetCheckoutPath(api).join(
      'out',
      config,
      'zip_archives',
      platform,
      artifact_name
  )
  api.path.mock_add_file(path)
  assert api.path.exists(path), '%s does not exist' % str(path)
  if not api.flutter_bcid.is_prod_build():
    return
  dst = '%s/%s' % (platform, artifact_name) if platform else artifact_name
  api.bucket_util.safe_upload(
      path,
      GetCloudPath(api, dst)
  )


def UploadToDownloadFlutterIO(api, config):
  src = GetCheckoutPath(api).join(
      'out',
      config,
      'zip_archives',
      'download.flutter.io'
  )
  api.path.mock_add_file(src)
  assert api.path.exists(src), '%s does not exist' % str(src)
  if not api.flutter_bcid.is_prod_build():
    return
  paths = api.file.listdir(
      'Expand directory', src,
      recursive=True, test_data=(MOCK_JAR_PATH, MOCK_POM_PATH))
  paths = [api.path.abspath(p) for p in paths]
  experimental = 'experimental' if api.runtime.is_experimental else ''
  for path in paths:
    dst_list = [
        'gs://download.flutter.io',
        experimental,
        str(path).split('download.flutter.io/')[1]
    ]
    dst = '/'.join(filter(bool, dst_list))
    api.archives.upload_artifact(path, dst)


def GetCheckoutPath(api):
  return api.path['cache'].join('builder', 'src')


def GetCloudPath(api, path):
  git_hash = api.buildbucket.gitiles_commit.id
  if api.runtime.is_experimental:
    return 'flutter/experimental/%s/%s' % (git_hash, path)
  return 'flutter/%s/%s' % (git_hash, path)


def Build(api, config, *targets):
  checkout = GetCheckoutPath(api)
  build_dir = checkout.join('out/%s' % config)
  goma_jobs = api.properties['goma_jobs']
  ninja_path = checkout.join('flutter', 'third_party', 'ninja', 'ninja')
  ninja_args = [ninja_path, '-j', goma_jobs, '-C', build_dir]
  ninja_args.extend(targets)
  with api.goma(), api.depot_tools.on_path():
    name = 'build %s' % ' '.join([config] + list(targets))
    api.step(name, ninja_args)


def RunTests(api, out_dir, android_out_dir=None, types='all'):
  script_path = GetCheckoutPath(api).join('flutter', 'testing', 'run_tests.py')
  # TODO(godofredoc): use .vpython from engine when file are available.
  venv_path = api.depot_tools.root.join('.vpython3')
  args = [
      'vpython3', '-vpython-spec', venv_path,
      script_path,
      '--variant', out_dir,
      '--type', types,
      '--engine-capture-core-dump'
  ]
  if android_out_dir:
    args.extend(['--android-variant', android_out_dir])

  step_name = api.test_utils.test_step_name('Host Tests for %s' % out_dir)

  def run_test():
    # Sometimes tests build artifacts, which will be extremelly slow if it does not run
    # from a goma context.
    env = {'GOMA_DIR': api.goma.goma_dir}
    with api.context(env=env):
      return api.step(step_name, args)

  # Rerun test step 3 times by default if failing.
  # TODO(keyonghan): notify tree gardener for test failures/flakes:
  # https://github.com/flutter/flutter/issues/89308
  api.retry.wrap(run_test, step_name=step_name)


def ScheduleBuilds(api, builder_name, drone_props):
  req = api.buildbucket.schedule_request(
      swarming_parent_run_id=api.swarming.task_id,
      builder=builder_name,
      properties=drone_props,
      # Having main build and subbuilds with the same priority can lead
      # to a deadlock situation when there are limited resources. For example
      # if we have only 7 mac bots and we get more than 7 new build requests the
      # within minutes of each other then the 7 bots will be used by main tasks
      # and they will all timeout waiting for resources to run subbuilds.
      # Increasing priority won't fix the problem but will make the deadlock
      # situation less unlikely.
      # https://github.com/flutter/flutter/issues/59169.
      #
      # Set priority to be same of main build temporily to help triage
      # https://github.com/flutter/flutter/issues/124155
      priority=30,
      exe_cipd_version=api.properties.get('exe_cipd_version', 'refs/heads/main')
  )
  return api.buildbucket.schedule([req])


def CancelBuilds(api, builds):
  for build in builds:
    api.buildbucket.cancel_build(build.id)


def CollectBuilds(api, builds):
  return api.buildbucket.collect_builds([build.id for build in builds],
                                        timeout=DRONE_TIMEOUT_SECS,
                                        mirror_status=True)


def GetFlutterFuchsiaBuildTargets(product, include_test_targets=False):
  targets = ['flutter/shell/platform/fuchsia:fuchsia']
  if include_test_targets:
    targets += ['fuchsia_tests']
  return targets


def GetFuchsiaOutputFiles(product):
  return [
      'dart_jit_%srunner' % ('product_' if product else ''),
      'dart_aot_%srunner' % ('product_' if product else ''),
      'flutter_jit_%srunner' % ('product_' if product else ''),
      'flutter_aot_%srunner' % ('product_' if product else ''),
  ]


def GetFuchsiaOutputDirs(product):
  return [
      'dart_jit_%srunner_far' % ('product_' if product else ''),
      'dart_aot_%srunner_far' % ('product_' if product else ''),
      'flutter_jit_%srunner_far' % ('product_' if product else ''),
      'flutter_aot_%srunner_far' % ('product_' if product else ''),
      'dart_runner_patched_sdk',
      'flutter_runner_patched_sdk',
      'clang_x64',
      '.build-id',
  ]


def BuildAndPackageFuchsia(api, build_script, git_rev):
  RunGN(
      api, '--fuchsia', '--fuchsia-cpu', 'x64', '--runtime-mode', 'debug',
      '--no-lto',
  )
  Build(api, 'fuchsia_debug_x64', *GetFlutterFuchsiaBuildTargets(False, True))

  # Package debug x64 on Linux builds.
  #
  # We pass --skip-build here, which means build_script will only take the existing artifacts
  # that we just built and package them. Invoking this command will not build fuchsia artifacts
  # despite the name of the build_script being build_fuchsia_artifacts.
  #
  # TODO(akbiggs): What is this actually used for? The artifacts aren't uploaded here,
  # they're uploaded in a second call to build_fuchsia_artifacts.py later, and calling
  # build_fuchsia_artifacts.py again will delete the bucket we created from the previous run. So
  # what is the package we're creating here used for?
  #
  # TODO(akbiggs): Clean this up if we feel brave.
  if api.platform.is_linux:
    fuchsia_package_cmd = [
        'python3', build_script, '--engine-version', git_rev, '--skip-build',
        '--archs', 'x64', '--runtime-mode', 'debug',
    ]
    api.step('Package Fuchsia Artifacts', fuchsia_package_cmd)

  RunGN(
      api, '--fuchsia', '--fuchsia-cpu', 'arm64', '--runtime-mode', 'debug',
      '--no-lto',
  )
  Build(api, 'fuchsia_debug_arm64', *GetFlutterFuchsiaBuildTargets(False, True))


def RunGN(api, *args):
  checkout = GetCheckoutPath(api)
  gn_cmd = ['python3', checkout.join('flutter/tools/gn'), '--goma']
  if api.properties.get('no_lto', False) and '--no-lto' not in args:
    args += ('--no-lto',)
  gn_cmd.extend(args)
  # Run GN with a goma_dir context.
  env = {'GOMA_DIR': api.goma.goma_dir}
  with api.context(env=env):
    api.step('gn %s' % ' '.join(args), gn_cmd)


def UploadArtifacts(
    api,
    platform,
    file_paths=[],
    directory_paths=[],
    archive_name='artifacts.zip',
    pkg_root=None
):
  dir_label = '%s UploadArtifacts %s' % (platform, archive_name)
  with api.os_utils.make_temp_directory(dir_label) as temp_dir:
    local_zip = temp_dir.join('artifacts.zip')
    remote_name = '%s/%s' % (platform, archive_name)
    remote_zip = GetCloudPath(api, remote_name)
    if pkg_root is None:
      pkg_root = GetCheckoutPath(api)
    pkg = api.zip.make_package(pkg_root, local_zip)
    api.bucket_util.add_files(pkg, file_paths)
    api.bucket_util.add_directories(pkg, directory_paths)

    pkg.zip('Zip %s %s' % (platform, archive_name))

    # Do not upload if not running from the prod bucket.
    if not api.flutter_bcid.is_prod_build():
      return

    api.bucket_util.safe_upload(local_zip, remote_zip)


def UploadSkyEngineToCIPD(api, package_name):
  git_rev = api.buildbucket.gitiles_commit.id or 'HEAD'
  package_dir = 'src/out/android_debug/dist/packages'
  parent_dir = api.path['cache'].join('builder', package_dir)
  folder_path = parent_dir.join(package_name)
  with api.os_utils.make_temp_directory(package_name) as temp_dir:
    zip_path = temp_dir.join('%s.zip' % package_name)
    cipd_package_name = 'flutter/%s' % package_name
    api.cipd.build(
        folder_path, zip_path, cipd_package_name, install_mode='copy'
    )
    if api.bucket_util.should_upload_packages():
      api.cipd.register(
          cipd_package_name,
          zip_path,
          refs=['latest'],
          tags={'git_revision': git_rev}
      )


def UploadSkyEngineDartPackage(api):
  UploadSkyEngineToCIPD(api, 'sky_engine')


def VerifyExportedSymbols(api):
  checkout = GetCheckoutPath(api)
  out_dir = checkout.join('out')
  script_dir = checkout.join('flutter/testing/symbols')
  script_path = script_dir.join('verify_exported.dart')
  api.step(
      'Verify exported symbols on release binaries',
      ['dart', script_path, out_dir]
  )


def UploadTreeMap(api, upload_dir, lib_flutter_path, android_triple):
  with api.os_utils.make_temp_directory('treemap') as temp_dir:
    checkout = GetCheckoutPath(api)
    script_path = checkout.join(
        'third_party/dart/runtime/'
        'third_party/binary_size/src/run_binary_size_analysis.py'
    )
    library_path = checkout.join(lib_flutter_path)
    destination_dir = temp_dir.join('sizes')
    addr2line = checkout.join(
        'third_party/android_tools/ndk/toolchains/' + android_triple +
        '-4.9/prebuilt/linux-x86_64/bin/' + android_triple + '-addr2line'
    )
    args = [
        '--library', library_path, '--destdir', destination_dir,
        "--addr2line-binary", addr2line
    ]

    # additional info: https://github.com/flutter/flutter/issues/84377
    file_command = ['file', library_path]
    api.step('file on libflutter.so', file_command)
    sha1sum_command = ['sha1sum', library_path]
    api.step('sha1sum on libflutter.so', sha1sum_command)

    command = ['python3', script_path]
    command.extend(args)
    api.step('generate treemap for %s' % upload_dir, command)

    remote_name = GetCloudPath(api, upload_dir)
    if api.bucket_util.should_upload_packages():
      # TODO(fujino): create SafeUploadDirectory() wrapper
      result = api.gsutil.upload(
          destination_dir,
          BUCKET_NAME,
          remote_name,
          args=['-r'],
          name='upload treemap for %s' % lib_flutter_path,
          link_name=None
      )
      result.presentation.links['Open Treemap'] = (
          'https://storage.googleapis.com/%s/%s/sizes/index.html' %
          (BUCKET_NAME, remote_name)
      )


class AndroidAotVariant:

  def __init__(
      self, android_cpu, out_dir, artifact_dir, clang_dir, android_triple, abi,
      gn_args, ninja_targets
  ):
    self.android_cpu = android_cpu
    self.out_dir = out_dir
    self.artifact_dir = artifact_dir
    self.clang_dir = clang_dir
    self.android_triple = android_triple
    self.abi = abi
    self.gn_args = gn_args
    self.ninja_targets = ninja_targets

  def GetBuildOutDir(self):
    return self.out_dir

  def GetUploadDir(self):
    return self.artifact_dir

  def GetLibFlutterPath(self):
    return 'libflutter.so'

  def GetGNArgs(self):
    return self.gn_args

  def GetNinjaTargets(self):
    return self.ninja_targets


# This variant is built on the scheduling bot to run firebase tests.
def BuildLinuxAndroidAOTArm64Profile(api, swarming_task_id, aot_variant):
  checkout = GetCheckoutPath(api)
  build_output_dir = aot_variant.GetBuildOutDir()

  RunGN(api, *aot_variant.GetGNArgs())
  Build(api, build_output_dir, *aot_variant.GetNinjaTargets())

  env = {
    'STORAGE_BUCKET': 'gs://flutter_firebase_testlab_staging',
    'GCP_PROJECT': 'flutter-infra-staging'
  }

  with api.context(env=env, cwd=checkout):
    args = [
        'python3', './flutter/ci/firebase_testlab.py',
        '--variant', build_output_dir,
        '--build-id', swarming_task_id,
    ]

    step_name = api.test_utils.test_step_name('Android Firebase Test')

    def firebase_func():
      api.step(step_name, args)

    api.retry.wrap(
        firebase_func, step_name=step_name, retriable_codes=(1, 15, 20)
    )


def BuildLinuxAndroidAOT(api, swarming_task_id):
  # Build and upload engines for the runtime modes that use AOT compilation.
  # Do arm64 first because we have more tests for that one, and can bail out
  # earlier if they fail.
  aot_variants = [
      AndroidAotVariant(
          android_cpu='arm64',
          out_dir='android_profile_arm64',
          artifact_dir='android-arm64-profile',
          clang_dir='clang_x64',
          android_triple='aarch64-linux-android',
          abi='arm64_v8a',
          gn_args=[
              '--runtime-mode',
              'profile',
              '--android',
              '--android-cpu',
              'arm64'
          ],
          ninja_targets=[
              'default',
              'clang_x64/gen_snapshot',
              'flutter/shell/platform/android:abi_jars',
              'flutter/shell/platform/android:analyze_snapshot'
          ]
      ),
      AndroidAotVariant(
          android_cpu='arm64',
          out_dir='android_release_arm64',
          artifact_dir='android-arm64-release',
          clang_dir='clang_x64',
          android_triple='aarch64-linux-android',
          abi='arm64_v8a',
          gn_args=[
              '--runtime-mode',
              'release',
              '--android',
              '--android-cpu',
              'arm64'
          ],
          ninja_targets=[
              'default',
              'clang_x64/gen_snapshot',
              'flutter/shell/platform/android:abi_jars',
              'flutter/shell/platform/android:analyze_snapshot'
          ]
      ),
      AndroidAotVariant(
          android_cpu='arm',
          out_dir='android_profile',
          artifact_dir='android-arm-profile',
          clang_dir='clang_x64',
          android_triple='arm-linux-androideabi',
          abi='armeabi_v7a',
          gn_args=[
              '--runtime-mode',
              'profile',
              '--android',
              '--android-cpu', 'arm'
          ],
          ninja_targets=[
              'default',
              'clang_x64/gen_snapshot',
              'flutter/shell/platform/android:embedding_jars',
              'flutter/shell/platform/android:abi_jars'
          ]
      ),
      AndroidAotVariant(
          android_cpu='arm',
          out_dir='android_release',
          artifact_dir='android-arm-release',
          clang_dir='clang_x64',
          android_triple='arm-linux-androideabi',
          abi='armeabi_v7a',
          gn_args=[
              '--runtime-mode',
              'release',
              '--android',
              '--android-cpu',
              'arm'
          ],
          ninja_targets=[
              'default',
              'clang_x64/gen_snapshot',
              'flutter/shell/platform/android:embedding_jars',
              'flutter/shell/platform/android:abi_jars'
          ]
      ),
      AndroidAotVariant(
          android_cpu='x64',
          out_dir='android_profile_x64',
          artifact_dir='android-x64-profile',
          clang_dir='clang_x64',
          android_triple='x86_64-linux-android',
          abi='x86_64',
          gn_args=[
              '--runtime-mode',
              'profile',
              '--android',
              '--android-cpu',
              'x64'
          ],
          ninja_targets=[
              'default',
              'clang_x64/gen_snapshot',
              'flutter/shell/platform/android:abi_jars',
              'flutter/shell/platform/android:analyze_snapshot'
          ]
      ),
      AndroidAotVariant(
          android_cpu='x64',
          out_dir='android_release_x64',
          artifact_dir='android-x64-release',
          clang_dir='clang_x64',
          android_triple='x86_64-linux-android',
          abi='x86_64',
          gn_args=[
              '--runtime-mode',
              'release',
              '--android',
              '--android-cpu', 'x64'
          ],
          ninja_targets=[
              'default',
              'clang_x64/gen_snapshot',
              'flutter/shell/platform/android:abi_jars',
              'flutter/shell/platform/android:analyze_snapshot'
          ]
      ),
  ]

  builds = []
  for aot_variant in aot_variants:
    build_out_dir = aot_variant.GetBuildOutDir()
    if build_out_dir == 'android_profile_arm64':
      continue
    props = {
        'builds': [{
            'gn_args': aot_variant.GetGNArgs(),
            'dir': build_out_dir,
            'targets': aot_variant.GetNinjaTargets(),
            'output_files': ['zip_archives', 'libflutter.so']
        }],
    }

    if 'git_url' in api.properties and 'git_ref' in api.properties:
      props['git_url'] = api.properties['git_url']
      props['git_ref'] = api.properties['git_ref']

    with api.step.nest('Schedule build %s' % build_out_dir):
      builds += ScheduleBuilds(api, 'Linux Engine Drone', props)

  checkout = GetCheckoutPath(api)
  git_rev = api.buildbucket.gitiles_commit.id or 'HEAD'

  try:
    with api.step.nest('Build and test arm64 profile'):
      BuildLinuxAndroidAOTArm64Profile(api, swarming_task_id, aot_variants[0])
  except (api.step.StepFailure, api.step.InfraFailure) as e:
    CancelBuilds(api, builds)
    raise e

  builds = CollectBuilds(api, builds)
  api.display_util.display_builds(
      step_name='display builds',
      builds=builds.values(),
      raise_on_failure=True,
  )
  for build_id in builds:
    build_props = builds[build_id].output.properties
    if 'cas_output_hash' in build_props:
      api.cas.download(
          'Download for build %s' % build_id,
          build_props['cas_output_hash'], GetCheckoutPath(api)
      )

  # Explicitly upload artifacts.

  # Artifacts.zip
  UploadArtifact(api, config='android_profile', platform='android-arm-profile',
                 artifact_name='artifacts.zip')
  UploadArtifact(api, config='android_profile_x64', platform='android-x64-profile',
                 artifact_name='artifacts.zip')
  UploadArtifact(api, config='android_profile_arm64', platform='android-arm64-profile',
                 artifact_name='artifacts.zip')

  UploadArtifact(api, config='android_release', platform='android-arm-release',
                 artifact_name='artifacts.zip')
  UploadArtifact(api, config='android_release_x64', platform='android-x64-release',
                 artifact_name='artifacts.zip')
  UploadArtifact(api, config='android_release_arm64', platform='android-arm64-release',
                 artifact_name='artifacts.zip')

  # Linux-x64.zip.
  UploadArtifact(api, config='android_profile', platform='android-arm-profile',
                 artifact_name='linux-x64.zip')
  UploadArtifact(api, config='android_profile_x64', platform='android-x64-profile',
                 artifact_name='linux-x64.zip')
  UploadArtifact(api, config='android_profile_arm64', platform='android-arm64-profile',
                 artifact_name='linux-x64.zip')

  UploadArtifact(api, config='android_release', platform='android-arm-release',
                 artifact_name='linux-x64.zip')
  UploadArtifact(api, config='android_release_x64', platform='android-x64-release',
                 artifact_name='linux-x64.zip')
  UploadArtifact(api, config='android_release_arm64', platform='android-arm64-release',
                 artifact_name='linux-x64.zip')

  # Symbols.zip
  UploadArtifact(api, config='android_profile', platform='android-arm-profile',
                 artifact_name='symbols.zip')
  UploadArtifact(api, config='android_profile_x64', platform='android-x64-profile',
                 artifact_name='symbols.zip')
  UploadArtifact(api, config='android_profile_arm64', platform='android-arm64-profile',
                 artifact_name='symbols.zip')

  UploadArtifact(api, config='android_release', platform='android-arm-release',
                 artifact_name='symbols.zip')
  UploadArtifact(api, config='android_release_x64', platform='android-x64-release',
                 artifact_name='symbols.zip')
  UploadArtifact(api, config='android_release_arm64', platform='android-arm64-release',
                 artifact_name='symbols.zip')

  # analyze-snapshot-linux-x64.zip
  UploadArtifact(api, config='android_profile_x64', platform='android-x64-profile',
                 artifact_name='analyze-snapshot-linux-x64.zip')
  UploadArtifact(api, config='android_profile_arm64', platform='android-arm64-profile',
                 artifact_name='analyze-snapshot-linux-x64.zip')

  UploadArtifact(api, config='android_release_x64', platform='android-x64-release',
                 artifact_name='analyze-snapshot-linux-x64.zip')
  UploadArtifact(api, config='android_release_arm64', platform='android-arm64-release',
                 artifact_name='analyze-snapshot-linux-x64.zip')

  # Jar, pom, embedding files.
  UploadToDownloadFlutterIO(api, 'android_profile')
  UploadToDownloadFlutterIO(api, 'android_profile_x64')
  UploadToDownloadFlutterIO(api, 'android_profile_arm64')

  UploadToDownloadFlutterIO(api, 'android_release')
  UploadToDownloadFlutterIO(api, 'android_release_x64')
  UploadToDownloadFlutterIO(api, 'android_release_arm64')

  for aot_variant in aot_variants:
    upload_dir = aot_variant.GetUploadDir()
    with api.step.nest('Upload artifacts %s' % upload_dir):
      # Paths in AndroidAotVariant do not prefix build_dir
      # that is expected when uploading artifacts.
      def prefix_build_dir(path):
        build_dir = aot_variant.GetBuildOutDir()
        return 'out/%s/%s' % (build_dir, path)

      unstripped_lib_flutter_path = prefix_build_dir(
          aot_variant.GetLibFlutterPath()
      )

      if aot_variant.GetBuildOutDir() in ['android_release_arm64', 'android_release']:
        triple = aot_variant.android_triple
        UploadTreeMap(api, upload_dir, unstripped_lib_flutter_path, triple)


def BuildLinuxAndroid(api, swarming_task_id):
  if api.properties.get('build_android_jit_release', True):
    RunGN(
        api,
        '--android',
        '--android-cpu=x86',
        '--runtime-mode=jit_release'
    )
    Build(
       api,
       'android_jit_release_x86',
       'flutter',
       'flutter/shell/platform/android:abi_jars',
       'flutter/shell/platform/android:embedding_jars',
       'flutter/shell/platform/android:robolectric_tests'
    )

    # Upload artifacts.zip
    UploadArtifact(
        api,
        config='android_jit_release_x86',
        platform='android-x86-jit-release',
        artifact_name='artifacts.zip'
    )
    RunTests(
        api,
        'android_jit_release_x86',
        android_out_dir='android_jit_release_x86',
        types='java'
    )

  if api.properties.get('build_android_debug', True):
    debug_variants = [
        AndroidAotVariant(
          android_cpu='x86',
          out_dir='android_debug_x86',
          artifact_dir='android-x86',
          clang_dir='',
          android_triple='',
          abi='x86',
          gn_args=[
              '--android',
              '--android-cpu=x86',
              '--no-lto'
          ],
          ninja_targets=[
              'flutter',
              'flutter/shell/platform/android:abi_jars',
              'flutter/shell/platform/android:robolectric_tests'
          ]
        ),
        AndroidAotVariant(
          android_cpu='x64',
          out_dir='android_debug_x64',
          artifact_dir='android-x64',
          clang_dir='',
          android_triple='',
          abi='x86_64',
          gn_args=[
              '--android',
              '--android-cpu=x64',
              '--no-lto'
          ],
          ninja_targets=[
              'flutter',
              'flutter/shell/platform/android:abi_jars'
          ]
        ),
        AndroidAotVariant(
          android_cpu='arm',
          out_dir='android_debug',
          artifact_dir='android-arm',
          clang_dir='',
          android_triple='',
          abi='armeabi_v7a',
          gn_args=[
              '--android',
              '--android-cpu=arm',
              '--no-lto'
          ],
          ninja_targets=[
              'flutter',
              'flutter/sky/dist:zip_old_location',
              'flutter/shell/platform/android:embedding_jars',
              'flutter/shell/platform/android:abi_jars'
          ]
        ),
        AndroidAotVariant(
          android_cpu='arm64',
          out_dir='android_debug_arm64',
          artifact_dir='android-arm64',
          clang_dir='',
          android_triple='',
          abi='arm64_v8a',
          gn_args=[
              '--android',
              '--android-cpu=arm64',
              '--no-lto'
          ],
          ninja_targets=[
              'flutter',
              'flutter/shell/platform/android:abi_jars'
          ]
        )
    ]
    for debug_variant in debug_variants:
      RunGN(api, *(debug_variant.GetGNArgs()))
      Build(api, debug_variant.GetBuildOutDir(), *(debug_variant.GetNinjaTargets()))

    # Run tests
    RunGN(api, '--android', '--unoptimized', '--runtime-mode=debug', '--no-lto')
    Build(api, 'android_debug', 'flutter/shell/platform/android:robolectric_tests')
    RunTests(api, 'android_debug', android_out_dir='android_debug', types='java')

    # Explicitly upload artifacts.

    # Artifacts.zip
    UploadArtifact(api, config='android_debug_x86', platform='android-x86',
                   artifact_name='artifacts.zip')
    UploadArtifact(api, config='android_debug_x64', platform='android-x64',
                   artifact_name='artifacts.zip')
    UploadArtifact(api, config='android_debug', platform='android-arm',
                   artifact_name='artifacts.zip')
    UploadArtifact(api, config='android_debug_arm64', platform='android-arm64',
                   artifact_name='artifacts.zip')

    # Symbols.zip
    UploadArtifact(api, config='android_debug_x86', platform='android-x86',
                   artifact_name='symbols.zip')
    UploadArtifact(api, config='android_debug_x64', platform='android-x64',
                   artifact_name='symbols.zip')
    UploadArtifact(api, config='android_debug', platform='android-arm',
                   artifact_name='symbols.zip')
    UploadArtifact(api, config='android_debug_arm64', platform='android-arm64',
                   artifact_name='symbols.zip')

    # Jar, pom, embedding files.
    UploadToDownloadFlutterIO(api, 'android_debug_x86')
    UploadToDownloadFlutterIO(api, 'android_debug_x64')
    UploadToDownloadFlutterIO(api, 'android_debug') #arm
    UploadToDownloadFlutterIO(api, 'android_debug_arm64')

    # Additional artifacts for android_debug
    UploadArtifact(api, config='android_debug', platform='',
                   artifact_name='sky_engine.zip')
    UploadArtifact(api, config='android_debug', platform='',
                   artifact_name='android-javadoc.zip')

    # Upload to CIPD.
    # TODO(godofredoc): Validate if this can be removed.
    UploadSkyEngineDartPackage(api)

  if api.properties.get('build_android_aot', True):
    BuildLinuxAndroidAOT(api, swarming_task_id)


def BuildLinux(api):
  checkout = GetCheckoutPath(api)
  RunGN(api, '--runtime-mode', 'debug', '--prebuilt-dart-sdk', '--build-embedder-examples')
  RunGN(api, '--runtime-mode', 'debug', '--unoptimized', '--prebuilt-dart-sdk')
  RunGN(api, '--runtime-mode', 'profile', '--no-lto', '--prebuilt-dart-sdk', '--build-embedder-examples')
  RunGN(api, '--runtime-mode', 'release', '--prebuilt-dart-sdk', '--build-embedder-examples')
  # flutter/sky/packages from host_debug_unopt is needed for RunTests 'dart'
  # type.
  Build(api, 'host_debug_unopt', 'flutter/sky/packages')
  Build(api, 'host_debug',
        'flutter/build/archives:artifacts',
        'flutter/build/archives:dart_sdk_archive',
        'flutter/build/archives:embedder',
        'flutter/build/archives:flutter_patched_sdk',
        'flutter/build/dart:copy_dart_sdk',
        'flutter/tools/font-subset',
        'flutter:unittests',
  )
  # 'engine' suite has failing tests in host_debug.
  # https://github.com/flutter/flutter/issues/103757
  RunTests(api, 'host_debug', types='dart')

  Build(api, 'host_profile',
        'flutter/shell/testing',
        'flutter/tools/path_ops',
        'flutter/build/dart:copy_dart_sdk',
        'flutter/shell/testing',
        'flutter:unittests',
  )
  RunTests(api, 'host_profile', types='dart,engine')
  Build(api, 'host_release',
        'flutter/build/archives:flutter_patched_sdk',
        'flutter/build/dart:copy_dart_sdk',
        'flutter/display_list:display_list_benchmarks',
        'flutter/display_list:display_list_builder_benchmarks',
        'flutter/fml:fml_benchmarks',
        'flutter/impeller/geometry:geometry_benchmarks',
        'flutter/lib/ui:ui_benchmarks',
        'flutter/shell/common:shell_benchmarks',
        'flutter/shell/testing',
        'flutter/third_party/txt:txt_benchmarks',
        'flutter/tools/path_ops',
        'flutter:unittests'
  )
  RunTests(api, 'host_release', types='dart,engine,benchmarks')

  # host_debug
  UploadArtifact(api, config='host_debug', platform='linux-x64',
                   artifact_name='artifacts.zip')
  UploadArtifact(api, config='host_debug', platform='linux-x64',
                   artifact_name='linux-x64-embedder.zip')
  UploadArtifact(api, config='host_debug', platform='linux-x64',
                   artifact_name='font-subset.zip')
  UploadArtifact(api, config='host_debug', platform='',
                   artifact_name='flutter_patched_sdk.zip')
  UploadArtifact(api, config='host_release', platform='',
                   artifact_name='flutter_patched_sdk_product.zip')
  UploadArtifact(api, config='host_debug', platform='',
                   artifact_name='dart-sdk-linux-x64.zip')

  # Rebuild with fontconfig support enabled for the desktop embedding, since it
  # should be on for libflutter_linux_gtk.so, but not libflutter_engine.so.
  RunGN(api, '--runtime-mode', 'debug', '--enable-fontconfig', '--prebuilt-dart-sdk')
  RunGN(api, '--runtime-mode', 'profile', '--no-lto', '--enable-fontconfig', '--prebuilt-dart-sdk')
  RunGN(api, '--runtime-mode', 'release', '--enable-fontconfig', '--prebuilt-dart-sdk')

  Build(api, 'host_debug', 'flutter/shell/platform/linux:flutter_gtk')
  Build(api, 'host_profile', 'flutter/shell/platform/linux:flutter_gtk')
  Build(api, 'host_release', 'flutter/shell/platform/linux:flutter_gtk')

  UploadArtifact(api, config='host_debug', platform='linux-x64-debug',
                 artifact_name='linux-x64-flutter-gtk.zip')
  UploadArtifact(api, config='host_profile', platform='linux-x64-profile',
                 artifact_name='linux-x64-flutter-gtk.zip')
  UploadArtifact(api, config='host_release', platform='linux-x64-release',
                 artifact_name='linux-x64-flutter-gtk.zip')


def GetRemoteFileName(exec_path):
  # An example of exec_path is:
  # out/fuchsia_debug_x64/flutter-fuchsia-x64/d4/917f5976.debug
  # In the above example "d4917f5976" is the elf BuildID for the
  # executable. First 2 characters are used as the directory name
  # and the rest of the string is the name of the unstripped executable.
  parts = exec_path.split('/')
  # We want d4917f5976.debug as the result.
  return ''.join(parts[-2:])


def UploadFuchsiaDebugSymbolsToSymbolServer(api, arch, symbol_dirs):
  """Uploads debug symbols to the Fuchsia Symbol Server (GCS bucket)

  Parameters
  ----------
  api : recipe API object.
  arch: architecture of the executable, typically x64 or arm64.
  symbol_dirs: dirs where the executables were generated.
  """
  with api.step.nest('Upload to Symbol Server for arch: %s' % arch):
    for symbol_dir in symbol_dirs:
      executables = api.file.listdir(
          'list %s' % symbol_dir,
          symbol_dir,
          recursive=True,
          test_data=['test_dir/sub_dir/test_file.debug']
      )
      # TODO(kaushikiska): Upload all the binaries as one gsutil copy
      # rather than doing it file by file.
      for executable in executables:
        # if a file contains 'dbg_success' in its name, it is a stamp file.
        # An example of this would be
        # '._dart_jit_runner_dbg_symbols_unstripped_dbg_success' these
        # are generated by GN and have to be ignored.
        exec_path = str(executable)
        if 'dbg_success' not in exec_path:
          remote_file_name = GetRemoteFileName(exec_path)
          api.bucket_util.safe_upload(
              executable,
              '%s/%s' % (FUCHSIA_ARTIFACTS_DEBUG_NAMESPACE, remote_file_name),
              bucket_name=FUCHSIA_ARTIFACTS_BUCKET_NAME,
              args=['-n'],
              skip_on_duplicate=True,  # because this isn't namespaced by commit
          )


def UploadFuchsiaDebugSymbolsToCIPD(api, arch, symbol_dirs, upload):
  checkout = GetCheckoutPath(api)
  dbg_symbols_script = str(
      checkout.join('flutter/tools/fuchsia/merge_and_upload_debug_symbols.py')
  )
  git_rev = api.buildbucket.gitiles_commit.id or 'HEAD'
  with api.os_utils.make_temp_directory('FuchsiaDebugSymbols_%s' % arch
                                       ) as temp_dir:
    debug_symbols_cmd = [
        'python3', dbg_symbols_script, '--engine-version', git_rev
    ]
    if upload:
      debug_symbols_cmd += ['--upload']
    debug_symbols_cmd += [
        '--target-arch', arch, '--out-dir', temp_dir, '--symbol-dirs'
    ] + symbol_dirs
    api.step('Upload to CIPD for arch: %s' % arch, cmd=debug_symbols_cmd, infra_step=True)


def UploadFuchsiaDebugSymbols(api, upload):
  checkout = GetCheckoutPath(api)
  archs = ['arm64', 'x64']
  modes = ['debug', 'profile', 'release']

  arch_to_symbol_dirs = {}
  for arch in archs:
    symbol_dirs = []
    for mode in modes:
      out_dir = 'fuchsia_%s_%s' % (mode, arch)
      symbol_dir = checkout.join('out', out_dir, '.build-id')
      symbol_dirs.append(symbol_dir)
    arch_to_symbol_dirs[arch] = symbol_dirs

  debug_symbol_futures = []
  for arch in archs:
    symbol_dirs = arch_to_symbol_dirs[arch]
    sym_server_future = api.futures.spawn(
        UploadFuchsiaDebugSymbolsToSymbolServer, api, arch, symbol_dirs
    )
    debug_symbol_futures.append(sym_server_future)
    cipd_future = api.futures.spawn(
        UploadFuchsiaDebugSymbolsToCIPD, api, arch, symbol_dirs, upload
    )
    debug_symbol_futures.append(cipd_future)

  for debug_sym_future in api.futures.iwait(debug_symbol_futures):
    debug_sym_future.result()


def ShouldPublishToCIPD(api, package_name, git_rev):
  """
  CIPD will, upon request, tag multiple instances with the same tag. However, if
  you try to retrieve that tag, it will throw an error complaining that the tag
  amgiguously refers to multiple instances. We should check before tagging.
  """
  instances = api.cipd.search(package_name, "git_revision:%s" % git_rev)
  return len(instances) == 0


def BuildFuchsia(api, gclient_vars):
  """
  This schedules release and profile builds for x64 and arm64 on other bots,
  and then builds the x64 and arm64 runners (which do not require LTO and thus
  are faster to build). On Linux, we also run tests for the runner against x64,
  and if they fail we cancel the scheduled builds.

  Args:
    gclient_vars: A dictionary with gclient variable names as keys and their
      associated values as the dictionary values.
  """
  fuchsia_build_pairs = [
      ('arm64', 'profile'),
      ('arm64', 'release'),
      ('x64', 'profile'),
      ('x64', 'release'),
  ]
  builds = []

  for arch, build_mode in fuchsia_build_pairs:
    gn_args = ['--fuchsia', '--fuchsia-cpu', arch, '--runtime-mode', build_mode]
    product = build_mode == 'release'
    fuchsia_output_dirs = GetFuchsiaOutputDirs(product)
    props = {
        'builds': [{
            'gn_args': gn_args,
            'dir': 'fuchsia_%s_%s' % (build_mode, arch),
            'targets': GetFlutterFuchsiaBuildTargets(product),
            'output_files': GetFuchsiaOutputFiles(product),
            'output_dirs': fuchsia_output_dirs,
        }],
        'gclient_variables': gclient_vars,
    }
    if 'git_url' in api.properties and 'git_ref' in api.properties:
      props['git_url'] = api.properties['git_url']
      props['git_ref'] = api.properties['git_ref']
    builds += ScheduleBuilds(api, 'Linux Engine Drone', props)

  checkout = GetCheckoutPath(api)
  build_script = str(
      checkout.join('flutter/tools/fuchsia/build_fuchsia_artifacts.py')
  )
  git_rev = api.buildbucket.gitiles_commit.id or 'HEAD'

  try:
    BuildAndPackageFuchsia(api, build_script, git_rev)
  except (api.step.StepFailure, api.step.InfraFailure) as e:
    CancelBuilds(api, builds)
    raise e

  builds = CollectBuilds(api, builds)
  api.display_util.display_builds(
      step_name='display builds',
      builds=builds.values(),
      raise_on_failure=True,
  )
  for build_id in builds:
    build_props = builds[build_id].output.properties
    if 'cas_output_hash' in build_props:
      api.cas.download(
          'Download for build %s' % build_id,
          build_props['cas_output_hash'], GetCheckoutPath(api)
      )

  fuchsia_package_cmd = [
      'python3',
      build_script,
      '--engine-version',
      git_rev,
      '--skip-build',
  ]

  upload = (api.bucket_util.should_upload_packages() and
      not api.runtime.is_experimental and
      ShouldPublishToCIPD(api, 'flutter/fuchsia', git_rev))

  if upload:
    fuchsia_package_cmd += ['--upload']

  api.step('Upload Fuchsia Artifacts', fuchsia_package_cmd, infra_step=True)
  with api.step.nest('Upload Fuchsia Debug Symbols'):
    UploadFuchsiaDebugSymbols(api, upload)


@contextmanager
def SetupXcode(api):
  # See cr-buildbucket.cfg for how the version is passed in.
  # https://github.com/flutter/infra/blob/35f51ea4bfc91966b41d988f6028e34449aa4279/config/generated/flutter/luci/cr-buildbucket.cfg#L7176-L7203
  with api.osx_sdk('ios'):
    yield


def PackageMacOSVariant(
    api,
    label,
    arm64_out,
    x64_out,
    bucket_name,
):
  checkout = GetCheckoutPath(api)
  out_dir = checkout.join('out')

  # Package the multi-arch framework for macOS.
  label_dir = out_dir.join(label)
  create_macos_framework_cmd = [
      checkout.join('flutter/sky/tools/create_macos_framework.py'),
      '--dst',
      label_dir,
      '--arm64-out-dir',
      api.path.join(out_dir, arm64_out),
      '--x64-out-dir',
      api.path.join(out_dir, x64_out),
  ]
  if label == 'release':
    create_macos_framework_cmd.extend([
        "--dsym",
        "--strip",
    ])

  with api.context(cwd=checkout):
    api.step(
        'Create macOS %s FlutterMacOS.framework' % label,
        create_macos_framework_cmd
    )

  # Package the multi-arch gen_snapshot for macOS.
  create_macos_gen_snapshot_cmd = [
      checkout.join('flutter/sky/tools/create_macos_gen_snapshots.py'),
      '--dst',
      label_dir,
      '--arm64-out-dir',
      api.path.join(out_dir, arm64_out),
      '--x64-out-dir',
      api.path.join(out_dir, x64_out),
  ]

  with api.context(cwd=checkout):
    api.step(
        'Create macOS %s gen_snapshot' % label,
        create_macos_gen_snapshot_cmd
    )

  api.zip.directory(
      'Archive FlutterMacOS.framework',
      label_dir.join('FlutterMacOS.framework'),
      label_dir.join('FlutterMacOS.framework.zip')
  )

  UploadArtifacts(
      api, bucket_name, [
          'out/%s/FlutterMacOS.framework.zip' % label,
      ],
      archive_name='FlutterMacOS.framework.zip'
  )
  UploadArtifacts(
      api, bucket_name, [
          'out/%s/gen_snapshot_x64' % label,
          'out/%s/gen_snapshot_arm64' % label,
      ],
      archive_name='gen_snapshot.zip'
  )

  if label == 'release':
    api.zip.directory(
        'Archive FlutterMacOS.dSYM',
        label_dir.join('FlutterMacOS.dSYM'),
        label_dir.join('FlutterMacOS.dSYM.zip')
    )
    UploadArtifacts(
        api, bucket_name, [
            'out/%s/FlutterMacOS.dSYM.zip' % label,
        ],
        archive_name='FlutterMacOS.dSYM.zip'
    )


def BuildMac(api):
  if api.properties.get('build_host', True):
    # Host Debug x64
    RunGN(
        api,
        '--runtime-mode',
        'debug',
        '--no-lto',
        '--prebuilt-dart-sdk',
        '--build-embedder-examples'
    )
    Build(
        api,
        'host_debug',
        'flutter/build/archives:archive_gen_snapshot',
        'flutter/build/archives:artifacts',
        'flutter/build/archives:dart_sdk_archive',
        'flutter/build/archives:flutter_embedder_framework',
        'flutter/build/dart:copy_dart_sdk',
        'flutter/shell/platform/darwin/macos:zip_macos_flutter_framework',
        'flutter/tools/font-subset',
        'flutter:unittests'
    )
    RunTests(api, 'host_debug', types='dart')

    # Host Profile x64
    RunGN(
        api,
        '--runtime-mode',
        'profile', '--no-lto',
        '--prebuilt-dart-sdk',
        '--build-embedder-examples'
    )
    Build(
        api,
        'host_profile',
        'flutter/build/archives:archive_gen_snapshot',
        'flutter/build/archives:artifacts',
        'flutter/build/dart:copy_dart_sdk',
        'flutter/shell/platform/darwin/macos:zip_macos_flutter_framework',
        'flutter:unittests'
    )
    RunTests(api, 'host_profile', types='dart,engine')

    # Host release x64
    RunGN(
        api,
        '--runtime-mode',
        'release',
        '--no-lto',
        '--prebuilt-dart-sdk',
        '--build-embedder-examples'
    )
    Build(
        api,
        'host_release',
        'flutter/build/archives:archive_gen_snapshot',
        'flutter/build/archives:artifacts',
        'flutter/build/dart:copy_dart_sdk',
        'flutter/shell/platform/darwin/macos:zip_macos_flutter_framework',
        'flutter:unittests'
    )
    RunTests(api, 'host_release', types='dart,engine')

    # Host debug arm64
    RunGN(
        api,
        '--mac',
        '--mac-cpu',
        'arm64',
        '--runtime-mode',
        'debug',
        '--no-lto',
        '--prebuilt-dart-sdk'
    )
    Build(
        api,
        'mac_debug_arm64',
        'flutter/build/archives:archive_gen_snapshot',
        'flutter/build/archives:artifacts',
        'flutter/build/archives:dart_sdk_archive',
        'flutter/shell/platform/darwin/macos:zip_macos_flutter_framework',
        'flutter/tools/font-subset'
    )

    # Host profile arm64
    RunGN(
        api,
        '--mac',
        '--mac-cpu',
        'arm64',
        '--runtime-mode',
        'profile',
        '--no-lto',
        '--prebuilt-dart-sdk'
    )
    Build(
        api,
        'mac_profile_arm64',
        'flutter/build/archives:artifacts',
        'flutter/shell/platform/darwin/macos:zip_macos_flutter_framework'
    )

    # Host release arm64
    RunGN(
        api,
        '--mac',
        '--mac-cpu',
        'arm64',
        '--runtime-mode',
        'release',
        '--no-lto',
        '--prebuilt-dart-sdk'
    )
    Build(
        api,
        'mac_release_arm64',
        'flutter/build/archives:artifacts',
        'flutter/shell/platform/darwin/macos:zip_macos_flutter_framework'
    )

    # Artifact uploads.
    # Host Debug x64
    UploadArtifact(
        api,
        config='host_debug',
        platform='darwin-x64',
        artifact_name='artifacts.zip'
    )
    UploadArtifact(
        api,
        config='host_debug',
        platform='darwin-x64',
        artifact_name='FlutterEmbedder.framework.zip'
    )
    UploadArtifact(
        api,
        config='host_debug',
        platform='',
        artifact_name='dart-sdk-darwin-x64.zip'
    )
    UploadArtifact(
        api,
        config='host_debug',
        platform='darwin-x64',
        artifact_name='font-subset.zip'
    )

    # Host Profile x64
    UploadArtifact(
        api,
        config='host_profile',
        platform='darwin-x64-profile',
        artifact_name='artifacts.zip'
    )

    # Host release x64
    UploadArtifact(
        api,
        config='host_release',
        platform='darwin-x64-release',
        artifact_name='artifacts.zip'
    )

    # Host debug arm64
    UploadArtifact(
        api,
        config='mac_debug_arm64',
        platform='darwin-arm64',
        artifact_name='artifacts.zip'
    )
    UploadArtifact(
        api,
        config='mac_debug_arm64',
        platform='',
        artifact_name='dart-sdk-darwin-arm64.zip'
    )
    UploadArtifact(
        api,
        config='mac_debug_arm64',
        platform='darwin-arm64',
        artifact_name='font-subset.zip'
    )

    # Host profile arm64
    UploadArtifact(
        api,
        config='mac_profile_arm64',
        platform='darwin-arm64-profile',
        artifact_name='artifacts.zip'
    )

    # Host release arm64
    UploadArtifact(
        api,
        config='mac_release_arm64',
        platform='darwin-arm64-release',
        artifact_name='artifacts.zip'
    )

    # These artifacts will translate to global generators.
    PackageMacOSVariant(
        api, 'debug', 'mac_debug_arm64', 'host_debug', 'darwin-x64'
    )
    PackageMacOSVariant(
        api, 'profile', 'mac_profile_arm64', 'host_profile', 'darwin-x64-profile'
    )
    PackageMacOSVariant(
        api, 'release', 'mac_release_arm64', 'host_release', 'darwin-x64-release'
    )


  if api.properties.get('build_android_aot', True):
    # Profile arm
    RunGN(
        api,
        '--runtime-mode',
        'profile',
        '--android'
    )
    Build(
        api,
        'android_profile',
        'flutter/lib/snapshot',
        'flutter/shell/platform/android:gen_snapshot'
    )
    UploadArtifact(
        api,
        config='android_profile',
        platform='android-arm-profile',
        artifact_name='darwin-x64.zip'
    )

    # Profile arm64
    RunGN(
        api,
        '--runtime-mode',
        'profile',
        '--android',
        '--android-cpu=arm64'
    )
    Build(
        api,
        'android_profile_arm64',
        'flutter/lib/snapshot',
        'flutter/shell/platform/android:gen_snapshot'
    )
    UploadArtifact(
        api,
        config='android_profile_arm64',
        platform='android-arm64-profile',
        artifact_name='darwin-x64.zip'
    )

    # Profile x64
    RunGN(
        api,
        '--runtime-mode',
        'profile',
        '--android',
        '--android-cpu=x64'
    )
    Build(
        api,
        'android_profile_x64',
        'flutter/lib/snapshot',
        'flutter/shell/platform/android:gen_snapshot'
    )
    UploadArtifact(
        api,
        config='android_profile_x64',
        platform='android-x64-profile',
        artifact_name='darwin-x64.zip'
    )

    # Release arm
    RunGN(
        api,
        '--runtime-mode',
        'release',
        '--android'
    )
    Build(
        api,
        'android_release',
        'flutter/lib/snapshot',
        'flutter/shell/platform/android:gen_snapshot'
    )
    UploadArtifact(
        api,
        config='android_release',
        platform='android-arm-release',
        artifact_name='darwin-x64.zip'
    )

    # Release arm64
    RunGN(
        api,
        '--runtime-mode',
        'release',
        '--android',
        '--android-cpu=arm64'
    )
    Build(
        api,
        'android_release_arm64',
        'flutter/lib/snapshot',
        'flutter/shell/platform/android:gen_snapshot'
    )
    UploadArtifact(
        api,
        config='android_release_arm64',
        platform='android-arm64-release',
        artifact_name='darwin-x64.zip'
    )

    # Release x64
    RunGN(
        api,
        '--runtime-mode',
        'release',
        '--android',
        '--android-cpu=x64'
    )
    Build(
        api,
        'android_release_x64',
        'flutter/lib/snapshot',
        'flutter/shell/platform/android:gen_snapshot'

    )
    UploadArtifact(
        api,
        config='android_release_x64',
        platform='android-x64-release',
        artifact_name='darwin-x64.zip'
    )


def PackageIOSVariant(
    api,
    label,
    arm64_out,
    sim_x64_out,
    sim_arm64_out,
    bucket_name,
):
  checkout = GetCheckoutPath(api)
  out_dir = checkout.join('out')

  # Package the multi-arch framework for iOS.
  label_dir = out_dir.join(label)
  create_ios_framework_cmd = [
      checkout.join('flutter/sky/tools/create_ios_framework.py'),
      '--dst',
      label_dir,
      '--arm64-out-dir',
      api.path.join(out_dir, arm64_out),
      '--simulator-x64-out-dir',
      api.path.join(out_dir, sim_x64_out),
      '--simulator-arm64-out-dir',
      api.path.join(out_dir, sim_arm64_out),
  ]

  if label == 'release':
    create_ios_framework_cmd.extend([
        "--dsym",
        "--strip",
    ])
  with api.context(cwd=checkout):
    api.step(
        'Create iOS %s Flutter.xcframework' % label, create_ios_framework_cmd
    )

  # Package the multi-arch gen_snapshot for macOS.
  create_macos_gen_snapshot_cmd = [
      checkout.join('flutter/sky/tools/create_macos_gen_snapshots.py'),
      '--dst',
      label_dir,
      '--arm64-out-dir',
      api.path.join(out_dir, arm64_out),
  ]

  with api.context(cwd=checkout):
    api.step(
        'Create macOS %s gen_snapshot' % label, create_macos_gen_snapshot_cmd
    )

  # Upload the artifacts to cloud storage.
  file_artifacts = [
      'gen_snapshot_arm64',
  ]
  directory_artifacts = [
      'Flutter.xcframework',
  ]

  label_root = checkout.join('out', label)
  UploadArtifacts(
      api,
      bucket_name,
      file_artifacts,
      directory_artifacts,
      pkg_root=label_root
  )

  if label == 'release':
    dsym_zip = label_dir.join('Flutter.dSYM.zip')
    pkg = api.zip.make_package(label_dir, dsym_zip)
    pkg.add_directory(label_dir.join('Flutter.dSYM'))
    pkg.zip('Zip Flutter.dSYM')
    remote_name = '%s/Flutter.dSYM.zip' % bucket_name
    remote_zip = GetCloudPath(api, remote_name)
    api.bucket_util.safe_upload(dsym_zip, remote_zip)


def BuildIOS(api, env, env_prefixes):
  # Simulator binary is needed in all runtime modes.
  RunGN(api, '--ios', '--runtime-mode', 'debug', '--simulator', '--no-lto')
  Build(api, 'ios_debug_sim')

  # The impellerc that was built as part of ios_debug_sim is used as a
  # prebuilt to the builds below in order to reduce build times. This is
  # not the impellerc that is shipped, so the exact details of how it is
  # built (e.g. --no-lto) don't matter.
  checkout = GetCheckoutPath(api)
  out_dir = checkout.join('out')
  impellerc_path = api.path.join(
      out_dir, 'ios_debug_sim', 'clang_x64', 'impellerc'
  )

  RunGN(
      api, '--ios', '--runtime-mode', 'debug', '--simulator',
      '--simulator-cpu=arm64', '--no-lto',
      '--prebuilt-impellerc', impellerc_path
  )
  Build(api, 'ios_debug_sim_arm64')

  if api.properties.get('ios_debug', True):
    RunGN(
        api, '--ios', '--runtime-mode', 'debug',
        '--prebuilt-impellerc', impellerc_path
    )
    Build(api, 'ios_debug')

    BuildObjcDoc(api, env, env_prefixes)

    PackageIOSVariant(
        api, 'debug', 'ios_debug', 'ios_debug_sim',
        'ios_debug_sim_arm64', 'ios'
    )

  if api.properties.get('ios_profile', True):
    RunGN(
        api, '--ios', '--runtime-mode', 'profile',
        '--prebuilt-impellerc', impellerc_path
    )
    Build(api, 'ios_profile')

    PackageIOSVariant(
        api, 'profile', 'ios_profile', 'ios_debug_sim',
        'ios_debug_sim_arm64', 'ios-profile'
    )

  if api.properties.get('ios_release', True):
    RunGN(
        api, '--ios', '--runtime-mode', 'release',
        '--prebuilt-impellerc', impellerc_path
    )
    Build(api, 'ios_release')

    PackageIOSVariant(
        api, 'release', 'ios_release', 'ios_debug_sim',
        'ios_debug_sim_arm64', 'ios-release'
    )


def BuildWindows(api):
  if api.properties.get('build_host', True):
    RunGN(api, '--runtime-mode', 'debug', '--no-lto', '--prebuilt-dart-sdk')
    Build(api, 'host_debug', 'flutter:unittests', 'flutter/build/archives:artifacts',
          'flutter/build/archives:embedder', 'flutter/tools/font-subset',
          'flutter/build/archives:dart_sdk_archive',
          'flutter/shell/platform/windows/client_wrapper:client_wrapper_archive',
          'flutter/build/archives:windows_flutter'
    )
    RunTests(api, 'host_debug', types='engine')
    RunGN(api, '--runtime-mode', 'profile', '--no-lto', '--prebuilt-dart-sdk')
    Build(api, 'host_profile', 'windows', 'flutter:gen_snapshot', 'flutter/build/archives:windows_flutter')
    RunGN(api, '--runtime-mode', 'release', '--no-lto', '--prebuilt-dart-sdk')
    Build(api, 'host_release', 'windows', 'flutter:gen_snapshot', 'flutter/build/archives:windows_flutter')

    branch = api.properties.get('git_branch', None)
    if branch == 'main':
      RunGN(api, '--runtime-mode', 'debug', '--no-lto', '--prebuilt-dart-sdk',
            '--windows-cpu', 'arm64')
      Build(api, 'host_debug_arm64', 'flutter/build/archives:artifacts',
            'flutter/build/archives:embedder', 'flutter/tools/font-subset',
            'flutter/build/archives:dart_sdk_archive',
            'flutter/shell/platform/windows/client_wrapper:client_wrapper_archive',
            'flutter/build/archives:windows_flutter')
      RunGN(api, '--runtime-mode', 'profile', '--no-lto', '--prebuilt-dart-sdk',
            '--windows-cpu', 'arm64')
      Build(api, 'host_profile_arm64', 'windows', 'gen_snapshot',
            'flutter/build/archives:windows_flutter')
      RunGN(api, '--runtime-mode', 'release', '--no-lto', '--prebuilt-dart-sdk',
            '--windows-cpu', 'arm64')
      Build(api, 'host_release_arm64', 'windows', 'gen_snapshot',
          'flutter/build/archives:windows_flutter')

    api.file.listdir(
        'host_release zips',
        GetCheckoutPath(api).join('out', 'host_release', 'zip_archives'))


    # host_debug
    UploadArtifact(api, config='host_debug', platform='windows-x64',
                   artifact_name='artifacts.zip')
    UploadArtifact(api, config='host_debug', platform='windows-x64',
                   artifact_name='windows-x64-embedder.zip')
    UploadArtifact(api, config='host_debug', platform='windows-x64-debug',
                   artifact_name='windows-x64-flutter.zip')
    UploadArtifact(api, config='host_debug', platform='windows-x64',
                   artifact_name='flutter-cpp-client-wrapper.zip')
    UploadArtifact(api, config='host_debug', platform='windows-x64',
                   artifact_name='font-subset.zip')
    UploadArtifact(api, config='host_debug', platform='',
                   artifact_name='dart-sdk-windows-x64.zip')

    # Host_profile
    UploadArtifact(api, config='host_profile', platform='windows-x64-profile',
                   artifact_name='windows-x64-flutter.zip')

    # Host_release
    UploadArtifact(api, config='host_release', platform='windows-x64-release',
                   artifact_name='windows-x64-flutter.zip')

    if branch == 'main':
      # host_debug_arm64.
      UploadArtifact(api, config='host_debug_arm64', platform='windows-arm64',
                     artifact_name='artifacts.zip')
      UploadArtifact(api, config='host_debug_arm64', platform='windows-arm64',
                     artifact_name='windows-arm64-embedder.zip')
      UploadArtifact(api, config='host_debug_arm64', platform='windows-arm64-debug',
                     artifact_name='windows-arm64-flutter.zip')
      UploadArtifact(api, config='host_debug_arm64', platform='windows-arm64',
                     artifact_name='flutter-cpp-client-wrapper.zip')
      UploadArtifact(api, config='host_debug_arm64', platform='',
                     artifact_name='dart-sdk-windows-arm64.zip')
      UploadArtifact(api, config='host_debug_arm64', platform='windows-arm64',
                     artifact_name='font-subset.zip')
      # host_profile_arm64.
      UploadArtifact(api, config='host_profile_arm64', platform='windows-arm64-profile',
                     artifact_name='windows-arm64-flutter.zip')
      # host_release_arm64.
      UploadArtifact(api, config='host_release_arm64', platform='windows-arm64-release',
                     artifact_name='windows-arm64-flutter.zip')

  if api.properties.get('build_android_aot', True):
    RunGN(api, '--runtime-mode', 'profile', '--android')
    RunGN(api, '--runtime-mode', 'profile', '--android', '--android-cpu=arm64')
    RunGN(api, '--runtime-mode', 'profile', '--android', '--android-cpu=x64')

    RunGN(api, '--runtime-mode', 'release', '--android')
    RunGN(api, '--runtime-mode', 'release', '--android', '--android-cpu=arm64')
    RunGN(api, '--runtime-mode', 'release', '--android', '--android-cpu=x64')

    Build(api, 'android_profile', 'flutter/build/archives:archive_win_gen_snapshot')
    Build(api, 'android_profile_arm64', 'flutter/build/archives:archive_win_gen_snapshot')
    Build(api, 'android_profile_x64', 'flutter/build/archives:archive_win_gen_snapshot')
    Build(api, 'android_release', 'flutter/build/archives:archive_win_gen_snapshot')
    Build(api, 'android_release_arm64', 'flutter/build/archives:archive_win_gen_snapshot')
    Build(api, 'android_release_x64', 'flutter/build/archives:archive_win_gen_snapshot')
    UploadArtifact(api, config='android_profile', platform='android-arm-profile',
                   artifact_name='windows-x64.zip')
    UploadArtifact(api, config='android_profile_arm64', platform='android-arm64-profile',
                   artifact_name='windows-x64.zip')
    UploadArtifact(api, config='android_profile_x64', platform='android-x64-profile',
                   artifact_name='windows-x64.zip')
    UploadArtifact(api, config='android_release', platform='android-arm-release',
                   artifact_name='windows-x64.zip')
    UploadArtifact(api, config='android_release_arm64', platform='android-arm64-release',
                   artifact_name='windows-x64.zip')
    UploadArtifact(api, config='android_release_x64', platform='android-x64-release',
                   artifact_name='windows-x64.zip')


def BuildObjcDoc(api, env, env_prefixes):
  """Builds documentation for the Objective-C variant of engine."""
  api.flutter_deps.jazzy(env, env_prefixes)
  checkout = GetCheckoutPath(api)
  with api.os_utils.make_temp_directory('BuildObjcDoc') as temp_dir:
    objcdoc_cmd = [checkout.join('flutter/tools/gen_objcdoc.sh'), temp_dir]
    with api.context(env=env, env_prefixes=env_prefixes, cwd=checkout.join('flutter')):
      api.step('build obj-c doc', objcdoc_cmd)
    api.zip.directory(
        'archive obj-c doc', temp_dir, checkout.join('out/ios-objcdoc.zip')
    )

    api.bucket_util.safe_upload(
        checkout.join('out/ios-objcdoc.zip'),
        GetCloudPath(api, 'ios-objcdoc.zip')
    )


def RunSteps(api, properties, env_properties):
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()

  cache_root = api.path['cache'].join('builder')
  checkout = GetCheckoutPath(api)

  api.file.rmtree('Clobber build output', checkout.join('out'))

  api.file.ensure_directory('Ensure checkout cache', cache_root)
  dart_bin = checkout.join(
      'third_party', 'dart', 'tools', 'sdks', 'dart-sdk', 'bin'
  )

  android_home = checkout.join('third_party', 'android_tools', 'sdk')

  env = {
    'ANDROID_HOME': str(android_home),
  }

  use_prebuilt_dart = (api.properties.get('build_host', True) or
                       api.properties.get('build_android_aot', True))

  if use_prebuilt_dart:
    env['FLUTTER_PREBUILT_DART_SDK'] = 'True'

  env_prefixes = {'PATH': [dart_bin]}

  api.logs_util.initialize_logs_collection(env)

  # Add certificates and print the ones required for pub.
  api.flutter_deps.certs(env, env_prefixes)
  api.os_utils.print_pub_certs()

  # Enable long path support on Windows.
  api.os_utils.enable_long_paths()
  api.repo_util.engine_checkout(cache_root, env, env_prefixes)

  # Delete derived data on mac. This is a noop for other platforms.
  api.os_utils.clean_derived_data()

  # Ensure required deps are installed
  api.flutter_deps.required_deps(
      env, env_prefixes, api.properties.get('dependencies', {})
  )

  # Various scripts we run assume access to depot_tools on path for `ninja`.
  with api.context(cwd=cache_root, env=env,
                   env_prefixes=env_prefixes), api.depot_tools.on_path():

    api.gclient.runhooks()
    gclient_vars = api.shard_util_v2.unfreeze_dict(api.properties.get('gclient_variables', {}))

    try:
      if api.platform.is_linux:
        if api.properties.get('build_host', True):
          BuildLinux(api)
        if env_properties.SKIP_ANDROID != 'TRUE':
          BuildLinuxAndroid(api, env_properties.SWARMING_TASK_ID)
        if api.properties.get('build_fuchsia', True):
          BuildFuchsia(api, gclient_vars)
        VerifyExportedSymbols(api)

      if api.platform.is_mac:
        with SetupXcode(api):
          BuildMac(api)
          if api.properties.get('build_ios', True):
            BuildIOS(api, env, env_prefixes)
          if api.properties.get('build_fuchsia', True):
            BuildFuchsia(api, gclient_vars)
          VerifyExportedSymbols(api)

      if api.platform.is_win:
        BuildWindows(api)
    finally:
      api.logs_util.upload_logs('engine')
      # This is to clean up leaked processes.
      api.os_utils.kill_processes()

  # Collect memory/cpu/process after task execution.
  api.os_utils.collect_os_info()


# pylint: disable=line-too-long
# See https://chromium.googlesource.com/infra/luci/recipes-py/+/refs/heads/master/doc/user_guide.md
# The tests in here make sure that every line of code is used and does not fail.
# pylint: enable=line-too-long
def GenTests(api):
  git_revision = 'abcd1234'
  output_props = struct_pb2.Struct()
  output_props['cas_output_hash'] = 'deadbeef'
  build = api.buildbucket.try_build_message(
      builder='Linux Drone', project='flutter'
  )
  build.output.CopyFrom(build_pb2.Build.Output(properties=output_props))
  collect_build_output = api.buildbucket.simulated_collect_output([build])
  for platform in ('mac', 'linux', 'win'):
    for should_upload in (True, False):
      for maven in (True, False):
        for should_publish_cipd in (True, False):
          for no_lto in (True, False):
            for font_subset in (True, False):
              for bucket in ('prod', 'staging', 'flutter'):
                for branch in ('main', 'flutter-3.8-candidate.10'):
                  if maven and platform in ['mac', 'win']:
                    continue
                  test = api.test(
                      '%s%s%s%s%s%s_%s_%s' % (
                          platform, '_upload' if should_upload else '',
                          '_maven' if maven else '', '_publish_cipd'
                          if should_publish_cipd else '', '_no_lto' if no_lto else '',
                          '_font_subset' if font_subset else '',
                          bucket,
                          branch
                      ),
                      api.platform(platform, 64),
                      api.buildbucket.ci_build(
                          builder='%s Engine' % platform.capitalize(),
                          git_repo=GIT_REPO,
                          project='flutter',
                          revision='%s' % git_revision,
                          bucket=bucket,
                      ),
                      api.runtime(is_experimental=False),
                      api.properties(
                          **{
                              'clobber': False,
                              'goma_jobs': '1024',
                              'fuchsia_ctl_version': 'version:0.0.2',
                              'build_host': True,
                              'build_fuchsia': True,
                              'build_android_aot': True,
                              'build_android_debug': True,
                              'git_branch': branch,
                              'no_maven': maven,
                              'upload_packages': should_upload,
                              'force_upload': True,
                              'no_lto': no_lto,
                              'build_font_subset': font_subset,
                          }
                      ),
                      api.properties.environ(
                          EnvProperties(SWARMING_TASK_ID='deadbeef')
                      ),
                  )
                  if platform == 'linux' and should_upload:
                    instances = 0 if should_publish_cipd else 1
                    test += (
                        api.override_step_data(
                            'cipd search flutter/fuchsia git_revision:%s' %
                            git_revision,
                            api.cipd.example_search(
                                'flutter/fuchsia', instances=instances
                            )
                        )
                    )
                  if platform != 'win':
                    test += collect_build_output
                  if platform == 'mac':
                    test += (
                        api.properties(
                            **{
                                'jazzy_version': '0.8.4',
                                'build_ios': True,
                                'ios_debug': True,
                                'ios_profile': True,
                                'ios_release': True,
                            }
                        )
                    )
                  yield test

  for should_upload in (True, False):
    yield api.test(
        'experimental%s' % ('_upload' if should_upload else ''),
        api.buildbucket.ci_build(
            builder='Linux Engine',
            git_repo=GIT_REPO,
            project='flutter',
        ),
        collect_build_output,
        api.runtime(is_experimental=True),
        api.properties(
            **{
                'goma_jobs': '1024',
                'fuchsia_ctl_version': 'version:0.0.2',
                'android_sdk_license': 'android_sdk_hash',
                'android_sdk_preview_license': 'android_sdk_preview_hash',
                'upload_packages': should_upload,
            }
        ),
    )
  yield api.test(
      'clobber',
      api.buildbucket.ci_build(
          builder='Linux Host Engine',
          git_repo='https://github.com/flutter/engine',
          project='flutter'
      ),
      collect_build_output,
      api.runtime(is_experimental=True),
      api.properties(
          **{
              'clobber': True,
              'git_url': 'https://github.com/flutter/engine',
              'goma_jobs': '200',
              'git_ref': 'refs/pull/1/head',
              'fuchsia_ctl_version': 'version:0.0.2',
              'build_host': True,
              'build_fuchsia': True,
              'build_android_aot': True,
              'build_android_debug': True,
              'android_sdk_license': 'android_sdk_hash',
              'android_sdk_preview_license': 'android_sdk_preview_hash'
          }
      ),
  )
  yield api.test(
      'pull_request',
      api.buildbucket.ci_build(
          builder='Linux Host Engine',
          git_repo='https://github.com/flutter/engine',
          project='flutter'
      ),
      collect_build_output,
      api.runtime(is_experimental=True),
      api.properties(
          **{
              'clobber': False,
              'git_url': 'https://github.com/flutter/engine',
              'goma_jobs': '200',
              'git_ref': 'refs/pull/1/head',
              'fuchsia_ctl_version': 'version:0.0.2',
              'build_host': True,
              'build_fuchsia': True,
              'build_android_aot': True,
              'build_android_debug': True,
              'android_sdk_license': 'android_sdk_hash',
              'android_sdk_preview_license': 'android_sdk_preview_hash',
              'gclient_variables': {'upload_fuchsia_sdk': True, 'fuchsia_sdk_hash': 'thehash'},
          }
      ),
  )
  yield api.test(
      'Linux Fuchsia skips on duplicate',
      api.platform('linux', 64),
      api.buildbucket.ci_build(
          builder='Linux Engine',
          git_repo=GIT_REPO,
          project='flutter',
          revision='%s' % git_revision,
      ),
      api.step_data(
          'cipd search flutter/fuchsia git_revision:%s' % git_revision,
          api.cipd.example_search('flutter/fuchsia', instances=0)
      ),
      collect_build_output,
      api.properties(
          **{
              'clobber': False,
              'goma_jobs': '1024',
              'fuchsia_ctl_version': 'version:0.0.2',
              'build_host': False,
              'build_fuchsia': True,
              'build_android_aot': False,
              'build_android_jit_release': False,
              'build_android_debug': False,
              'no_maven': True,
              'upload_packages': True,
              'android_sdk_license': 'android_sdk_hash',
              'android_sdk_preview_license': 'android_sdk_preview_hash',
              'force_upload': False
          }
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
      api.properties.environ(EnvProperties(SKIP_ANDROID='TRUE')),
  )
  yield api.test(
      'Linux Fuchsia failing test',
      api.platform('linux', 64),
      api.buildbucket.ci_build(
          builder='Linux Engine', git_repo=GIT_REPO, project='flutter'
      ),
      api.step_data(
          'gn --fuchsia --fuchsia-cpu x64 --runtime-mode debug --no-lto',
          retcode=1
      ),
      api.properties(
          **{
              'clobber': False,
              'goma_jobs': '1024',
              'fuchsia_ctl_version': 'version:0.0.2',
              'build_host': False,
              'build_fuchsia': True,
              'build_android_aot': False,
              'build_android_debug': False,
              'no_maven': False,
              'upload_packages': True,
              'android_sdk_license': 'android_sdk_hash',
              'android_sdk_preview_license': 'android_sdk_preview_hash',
              'force_upload': True
          }
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
  )
  yield api.test(
      'fail_android_aot_sharded_builds',
      # 64 bit linux machine
      api.platform('linux', 64),
      api.buildbucket.ci_build(
          builder='Linux Engine', git_repo=GIT_REPO, project='flutter'
      ),
      api.step_data(
          'Build and test arm64 profile.gn --runtime-mode profile --android --android-cpu arm64',
          retcode=1
      ),
      api.properties(
          **{
              'clobber': False,
              'goma_jobs': '1024',
              'fuchsia_ctl_version': 'version:0.0.2',
              'build_host': False,
              'build_fuchsia': False,
              'build_android_aot': True,
              'build_android_debug': False,
              'dependencies': [
                {
                    'dependency': 'open_jdk',
                    'version': 'version:11',
                }
              ],
              'no_maven': False,
              'upload_packages': True,
              'android_sdk_license': 'android_sdk_hash',
              'android_sdk_preview_license': 'android_sdk_preview_hash',
              'force_upload': True
          }
      ),
      api.properties.environ(EnvProperties(SWARMING_TASK_ID='deadbeef')),
  )

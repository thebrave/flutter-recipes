# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager

from PB.recipes.flutter.engine import InputProperties
from PB.recipes.flutter.engine import EnvProperties

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from google.protobuf import struct_pb2

DEPS = [
    'depot_tools/bot_update',
    'depot_tools/depot_tools',
    'depot_tools/gclient',
    'depot_tools/git',
    'depot_tools/gsutil',
    'flutter/bucket_util',
    'flutter/flutter_deps',
    'flutter/logs_util',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/repo_util',
    'flutter/retry',
    'flutter/test_utils',
    'flutter/zip',
    'fuchsia/display_util',
    'fuchsia/gcloud',
    'fuchsia/goma',
    'recipe_engine/buildbucket',
    'recipe_engine/cas',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/futures',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/python',
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
    'https://chromium.googlesource.com/external/github.com/flutter/engine'
)

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties


def BuildFontSubset(api):
  return api.properties.get('build_font_subset', True)

def UploadFontSubset(api, platform):
  if not BuildFontSubset(api):
    return
  font_subset_path = GetCheckoutPath(api).join(
      'out',
      'host_release',
      'zip_archives',
      'font-subset.zip'
  )
  api.bucket_util.safe_upload(
      font_subset_path,
      GetCloudPath(api, '%s/font-subset.zip' % platform)
  )


def GetCheckoutPath(api):
  return api.path['cache'].join('builder', 'src')


def GetGitHash(api):
  with api.context(cwd=GetCheckoutPath(api)):
    return api.step(
        "Retrieve git hash",
        ["git", "rev-parse", "HEAD"],
        stdout=api.raw_io.output(),
        infra_step=True,
    ).stdout.strip()


def GetCloudPath(api, path):
  git_hash = api.buildbucket.gitiles_commit.id
  if api.runtime.is_experimental:
    return 'flutter/experimental/%s/%s' % (git_hash, path)
  return 'flutter/%s/%s' % (git_hash, path)


def Build(api, config, *targets):
  checkout = GetCheckoutPath(api)
  build_dir = checkout.join('out/%s' % config)
  goma_jobs = api.properties['goma_jobs']
  ninja_args = [api.depot_tools.ninja_path, '-j', goma_jobs, '-C', build_dir]
  ninja_args.extend(targets)
  with api.goma.build_with_goma(), api.depot_tools.on_path():
    name = 'build %s' % ' '.join([config] + list(targets))
    api.step(name, ninja_args)


def AutoninjaBuild(api, config, *targets):
  checkout = GetCheckoutPath(api)
  build_dir = checkout.join('out/%s' % config)
  ninja_args = [api.depot_tools.autoninja_path, '-C', build_dir]
  ninja_args.extend(targets)
  api.step('build %s' % ' '.join([config] + list(targets)), ninja_args)


def RunTests(api, out_dir, android_out_dir=None, types='all'):
  script_path = GetCheckoutPath(api).join('flutter', 'testing', 'run_tests.py')
  # TODO(godofredoc): use .vpython from engine when file are available.
  venv_path = api.depot_tools.root.join('.vpython')
  args = ['--variant', out_dir, '--type', types, '--engine-capture-core-dump']
  if android_out_dir:
    args.extend(['--android-variant', android_out_dir])

  def run_test():
    return api.python(
        api.test_utils.test_step_name('Host Tests for %s' % out_dir),
        script_path,
        args,
        venv=venv_path
    )

  # Rerun test step 3 times by default if failing.
  # TODO(keyonghan): notify tree gardener for test failures/flakes:
  # https://github.com/flutter/flutter/issues/89308
  api.retry.wrap(run_test)


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
      priority=25
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
      '--no-lto'
  )
  Build(api, 'fuchsia_debug_x64', *GetFlutterFuchsiaBuildTargets(False, True))

  fuchsia_package_cmd = [
      'python', build_script, '--engine-version', git_rev, '--skip-build',
      '--archs', 'x64', '--runtime-mode', 'debug'
  ]

  if api.platform.is_linux:
    api.step('Package Fuchsia Artifacts', fuchsia_package_cmd)

  RunGN(
      api, '--fuchsia', '--fuchsia-cpu', 'arm64', '--runtime-mode', 'debug',
      '--no-lto'
  )
  Build(api, 'fuchsia_debug_arm64', *GetFlutterFuchsiaBuildTargets(False, True))


def RunGN(api, *args):
  checkout = GetCheckoutPath(api)
  gn_cmd = ['python', checkout.join('flutter/tools/gn'), '--goma']
  if api.properties.get('no_lto', False) and '--no-lto' not in args:
    args += ('--no-lto',)
  gn_cmd.extend(args)
  api.step('gn %s' % ' '.join(args), gn_cmd)


def NotifyPubsub(
    api,
    buildername,
    bucket,
    topic='projects/flutter-dashboard/topics/luci-builds-prod'
):
  """Sends a pubsub message to the topic specified with buildername and githash, identifying
  the completed build.

  Args:
    api: luci api object.
    buildername(str): The name of builder.
    bucket(str): The name of the bucket.
    topic(str): (optional) gcloud topic to publish message to.
  """
  githash = GetGitHash(api)
  cmd = [
      'pubsub', 'topics', 'publish', topic,
      '--message={"buildername" : "%s", "bucket" : "%s", "githash" : "%s"}' %
      (buildername, bucket, githash)
  ]
  api.gcloud(*cmd, infra_step=True)


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
    api.bucket_util.safe_upload(local_zip, remote_zip)


# Takes an artifact filename such as `flutter_embedding_release.jar`
# and returns `io/flutter/flutter_embedding_release/1.0.0-<hash>/
# flutter_embedding_release-1.0.0-<hash>.jar`.
def GetCloudMavenPath(api, artifact_filename, swarming_task_id):
  if api.runtime.is_experimental:
    # If this is not somewhat unique then led tasks will fail with
    # a missing delete permission.
    engine_git_hash = 'experimental-%s' % swarming_task_id
  else:
    engine_git_hash = api.buildbucket.gitiles_commit.id or 'testing'

  artifact_id, artifact_extension = artifact_filename.split('.', 2)

  # Source artifacts
  if artifact_id.endswith('-sources'):
    filename_pattern = '%s-1.0.0-%s-sources.%s'
  else:
    filename_pattern = '%s-1.0.0-%s.%s'

  artifact_id = artifact_id.replace('-sources', '')
  filename = filename_pattern % (
      artifact_id, engine_git_hash, artifact_extension
  )

  return 'io/flutter/%s/1.0.0-%s/%s' % (artifact_id, engine_git_hash, filename)


# Uploads the local Maven artifact.
def UploadMavenArtifacts(api, artifacts, swarming_task_id):
  checkout = GetCheckoutPath(api)

  for local_artifact in artifacts:
    filename = api.path.basename(local_artifact)
    remote_artifact = GetCloudMavenPath(api, filename, swarming_task_id)

    api.bucket_util.safe_upload(
        checkout.join(local_artifact),
        remote_artifact,
        bucket_name=MAVEN_BUCKET_NAME,
        dry_run=api.properties.get('no_maven', False),
    )


def UploadDartPackage(api, package_name):
  api.bucket_util.upload_folder(
      'UploadDartPackage %s' % package_name,
      'src/out/android_debug/dist/packages', package_name,
      "%s.zip" % package_name
  )


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
  UploadDartPackage(api, 'sky_engine')
  UploadSkyEngineToCIPD(api, 'sky_engine')


def UploadFlutterPatchedSdk(api):
  host_debug_path = GetCheckoutPath(api).join('out/host_debug')
  host_release_path = GetCheckoutPath(api).join('out/host_release')

  # These are large and unused by Flutter, see #77950
  api.file.rmglob(
      'remove *.dill.S files from flutter_patched_sdk',
      host_debug_path.join('flutter_patched_sdk'),
      '*.dill.S',
  )

  api.bucket_util.upload_folder(
      'Upload Flutter patched sdk', 'src/out/host_debug', 'flutter_patched_sdk',
      'flutter_patched_sdk.zip'
  )

  flutter_patched_sdk_product = host_release_path.join(
      'flutter_patched_sdk_product'
  )

  api.file.rmtree(
      'Remove stale flutter_patched_sdk_product', flutter_patched_sdk_product
  )
  api.file.move(
      'Move release flutter_patched_sdk to flutter_patched_sdk_product',
      host_release_path.join('flutter_patched_sdk'), flutter_patched_sdk_product
  )

  api.file.rmglob(
      'remove *.dill.S files from flutter_patched_sdk_product',
      host_release_path.join('flutter_patched_sdk_product'),
      '*.dill.S',
  )

  api.bucket_util.upload_folder(
      'Upload Product Flutter patched sdk', 'src/out/host_release',
      'flutter_patched_sdk_product', 'flutter_patched_sdk_product.zip'
  )


def UploadDartSdk(api, archive_name):
  api.bucket_util.upload_folder(
      'Upload Dart SDK', 'src/out/host_debug', 'dart-sdk', archive_name
  )


def UploadWebSdk(api, archive_name):
  api.bucket_util.upload_folder(
      'Upload Web SDK', 'src/out/host_debug', 'flutter_web_sdk', archive_name
  )


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
      self, android_cpu, out_dir, artifact_dir, clang_dir, android_triple, abi
  ):
    self.android_cpu = android_cpu
    self.out_dir = out_dir
    self.artifact_dir = artifact_dir
    self.clang_dir = clang_dir
    self.android_triple = android_triple
    self.abi = abi

  def GetBuildOutDir(self, runtime_mode):
    return self.out_dir % runtime_mode

  def GetUploadDir(self, runtime_mode):
    return self.artifact_dir % runtime_mode

  def GetFlutterJarPath(self):
    return 'flutter.jar'

  def GetMavenArtifacts(self, runtime_mode):
    return [
        '%s_%s.jar' % (self.abi, runtime_mode),
        '%s_%s.pom' % (self.abi, runtime_mode)
    ]

  def GetGenSnapshotPath(self):
    return '%s/gen_snapshot' % (self.clang_dir)

  def GetLibFlutterPath(self):
    return 'libflutter.so'

  def GetEmbeddingArtifacts(self, runtime_mode):
    return [
        'flutter_embedding_%s.jar' % runtime_mode,
        'flutter_embedding_%s.pom' % runtime_mode,
        'flutter_embedding_%s-sources.jar' % runtime_mode,
    ]

  def GetGNArgs(self, runtime_mode):
    return [
        '--android', '--runtime-mode', runtime_mode, '--android-cpu',
        self.android_cpu
    ]

  def GetNinjaTargets(self):
    return ['default', '%s/gen_snapshot' % self.clang_dir]

  def GetOutputFiles(self, runtime_mode):
    return [
        self.GetFlutterJarPath(),
        self.GetGenSnapshotPath(),
        self.GetLibFlutterPath()
    ] + self.GetMavenArtifacts(runtime_mode
                              ) + self.GetEmbeddingArtifacts(runtime_mode)


# This variant is built on the scheduling bot to run firebase tests.
def BuildLinuxAndroidAOTArm64Profile(api, swarming_task_id, aot_variant):
  checkout = GetCheckoutPath(api)
  build_output_dir = aot_variant.GetBuildOutDir('profile')

  RunGN(api, *aot_variant.GetGNArgs('profile'))
  Build(api, build_output_dir, *aot_variant.GetNinjaTargets())

  with api.context(cwd=checkout):
    args = [
        '--variant', build_output_dir,
        '--build-id', swarming_task_id,
    ]

    def firebase_func():
      api.python(
          api.test_utils.test_step_name('Android Firebase Test'),
          './flutter/ci/firebase_testlab.py', args
      )

    api.retry.wrap(firebase_func, retriable_codes=(1, 15, 20))


def BuildLinuxAndroidAOT(api, swarming_task_id):
  # Build and upload engines for the runtime modes that use AOT compilation.
  # Do arm64 first because we have more tests for that one, and can bail out
  # earlier if they fail.
  aot_variants = [
      AndroidAotVariant(
          'arm64', 'android_%s_arm64', 'android-arm64-%s', 'clang_x64',
          'aarch64-linux-android', 'arm64_v8a'
      ),
      AndroidAotVariant(
          'arm', 'android_%s', 'android-arm-%s', 'clang_x64',
          'arm-linux-androideabi', 'armeabi_v7a'
      ),
      AndroidAotVariant(
          'x64', 'android_%s_x64', 'android-x64-%s', 'clang_x64',
          'x86_64-linux-android', 'x86_64'
      ),
  ]

  builds = []
  for aot_variant in aot_variants:
    for runtime_mode in ['profile', 'release']:
      if runtime_mode == 'profile' and aot_variant.android_cpu == 'arm64':
        # This variant will be executed on the current shard to facilitate,
        # running firebase tests. See: BuildLinuxAndroidAOTArm64Profile
        continue

      build_out_dir = aot_variant.GetBuildOutDir(runtime_mode)
      props = {
          'builds': [{
              'gn_args': aot_variant.GetGNArgs(runtime_mode),
              'dir': build_out_dir,
              'targets': aot_variant.GetNinjaTargets(),
              'output_files': aot_variant.GetOutputFiles(runtime_mode),
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

  embedding_artifacts_uploaded = 0
  for aot_variant in aot_variants:
    for runtime_mode in ['profile', 'release']:
      upload_dir = aot_variant.GetUploadDir(runtime_mode)
      with api.step.nest('Upload artifacts %s' % upload_dir):
        # Paths in AndroidAotVariant do not prefix build_dir
        # that is expected when uploading artifacts.
        def prefix_build_dir(path):
          build_dir = aot_variant.GetBuildOutDir(runtime_mode)
          return 'out/%s/%s' % (build_dir, path)

        def prefix_build_dir_lst(lst):
          return [prefix_build_dir(path) for path in lst]

        # TODO(egarciad): Don't upload flutter.jar once the migration to Maven
        # is completed.
        UploadArtifacts(
            api, upload_dir,
            [prefix_build_dir(aot_variant.GetFlutterJarPath())]
        )

        # Upload the Maven artifacts.
        UploadMavenArtifacts(
            api,
            prefix_build_dir_lst(aot_variant.GetMavenArtifacts(runtime_mode)),
            swarming_task_id
        )

        # Upload artifacts used for AOT compilation on Linux hosts.
        UploadArtifacts(
            api,
            upload_dir, [prefix_build_dir(aot_variant.GetGenSnapshotPath())],
            archive_name='linux-x64.zip'
        )

        unstripped_lib_flutter_path = prefix_build_dir(
            aot_variant.GetLibFlutterPath()
        )
        UploadArtifacts(
            api,
            upload_dir, [unstripped_lib_flutter_path],
            archive_name='symbols.zip'
        )

        if runtime_mode == 'release' and aot_variant.android_cpu != 'x64':
          triple = aot_variant.android_triple
          UploadTreeMap(api, upload_dir, unstripped_lib_flutter_path, triple)

        # Upload the embedding artifacts, we only need this once per
        # runtime mode.
        if embedding_artifacts_uploaded < 2:
          embedding_artifacts_uploaded += 1
          UploadMavenArtifacts(
              api,
              prefix_build_dir_lst(
                  aot_variant.GetEmbeddingArtifacts(runtime_mode)
              ), swarming_task_id
          )


def BuildLinuxAndroid(api, swarming_task_id):
  if api.properties.get('build_android_jit_release', True):
    jit_release_variants = [
        (
            'x86', 'android_jit_release_x86', 'android-x86-jit-release', True,
            'x86'
        ),
    ]
    for android_cpu, out_dir, artifact_dir, \
            run_tests, abi in jit_release_variants:
      RunGN(
          api, '--android', '--android-cpu=%s' % android_cpu,
          '--runtime-mode=jit_release'
      )
      Build(api, out_dir)
      if run_tests:
        RunGN(api, '--android', '--unoptimized', '--runtime-mode=debug', '--no-lto')
        Build(api, out_dir, 'flutter/shell/platform/android:robolectric_tests')
        RunTests(api, out_dir, android_out_dir=out_dir, types='java')
      artifacts = ['out/%s/flutter.jar' % out_dir]
      UploadArtifacts(api, artifact_dir, artifacts)

  if api.properties.get('build_android_debug', True):
    debug_variants = [
        ('arm', 'android_debug', 'android-arm', True, 'armeabi_v7a'),
        ('arm64', 'android_debug_arm64', 'android-arm64', False, 'arm64_v8a'),
        ('x86', 'android_debug_x86', 'android-x86', False, 'x86'),
        ('x64', 'android_debug_x64', 'android-x64', False, 'x86_64'),
    ]
    for android_cpu, out_dir, artifact_dir, run_tests, abi in debug_variants:
      RunGN(api, '--android', '--android-cpu=%s' % android_cpu, '--no-lto')
      Build(api, out_dir)
      if run_tests:
        RunGN(api, '--android', '--unoptimized', '--runtime-mode=debug', '--no-lto')
        Build(api, out_dir, 'flutter/shell/platform/android:robolectric_tests')
        RunTests(api, out_dir, android_out_dir=out_dir, types='java')
      artifacts = ['out/%s/flutter.jar' % out_dir]
      if android_cpu in ['x86', 'x64']:
        artifacts.append('out/%s/lib.stripped/libflutter.so' % out_dir)
      UploadArtifacts(api, artifact_dir, artifacts)
      UploadArtifacts(
          api,
          artifact_dir, ['out/%s/libflutter.so' % out_dir],
          archive_name='symbols.zip'
      )

      # Upload the Maven artifacts.
      engine_filename = '%s_debug' % abi
      UploadMavenArtifacts(
          api, [
              'out/%s/%s.jar' % (out_dir, engine_filename),
              'out/%s/%s.pom' % (out_dir, engine_filename),
          ], swarming_task_id
      )

    # Upload the embedding
    UploadMavenArtifacts(
        api, [
            'out/android_debug/flutter_embedding_debug.jar',
            'out/android_debug/flutter_embedding_debug.pom',
            'out/android_debug/flutter_embedding_debug-sources.jar',
        ], swarming_task_id
    )

    Build(api, 'android_debug', ':dist')
    UploadSkyEngineDartPackage(api)
    UploadJavadoc(api, 'android_debug')

  if api.properties.get('build_android_aot', True):
    BuildLinuxAndroidAOT(api, swarming_task_id)


def PackageLinuxDesktopVariant(api, label, bucket_name):
  artifacts = [
      'libflutter_linux_gtk.so',
  ]
  if bucket_name.endswith('profile') or bucket_name.endswith('release'):
    artifacts.append('gen_snapshot')
  # Headers for the library are in the flutter_linux folder.
  api.bucket_util.upload_folder_and_files(
      'Upload linux-x64 Flutter GTK artifacts',
      'src/out/%s' % label,
      'flutter_linux',
      'linux-x64-flutter-gtk.zip',
      platform=bucket_name,
      file_paths=artifacts
  )


def BuildLinux(api):
  RunGN(api, '--runtime-mode', 'debug', '--full-dart-sdk', '--prebuilt-dart-sdk')
  RunGN(api, '--runtime-mode', 'debug', '--unoptimized', '--prebuilt-dart-sdk')
  RunGN(api, '--runtime-mode', 'profile', '--no-lto', '--prebuilt-dart-sdk')
  RunGN(api, '--runtime-mode', 'release', '--prebuilt-dart-sdk')
  # flutter/sky/packages from host_debug_unopt is needed for RunTests 'dart'
  # type.
  Build(api, 'host_debug_unopt', 'flutter/sky/packages')
  Build(
      api, 'host_debug_unopt',
      'flutter/lib/spirv/test/exception_shaders:spirv_compile_exception_shaders'
  )
  Build(api, 'host_debug')
  Build(api, 'host_profile')
  RunTests(api, 'host_profile', types='engine')
  Build(api, 'host_release')
  api.file.listdir(
      'host_release zips',
      GetCheckoutPath(api).join('out', 'host_release', 'zip_archives'))
  RunTests(api, 'host_release', types='dart,engine,benchmarks')
  UploadArtifacts(
      api, 'linux-x64', [
          ICU_DATA_PATH,
          'out/host_debug/flutter_tester',
          'out/host_debug/gen/flutter/lib/snapshot/isolate_snapshot.bin',
          'out/host_debug/gen/flutter/lib/snapshot/vm_isolate_snapshot.bin',
          'out/host_debug/gen/frontend_server.dart.snapshot',
      ]
  )
  UploadArtifacts(
      api,
      'linux-x64', [
          'out/host_debug/flutter_embedder.h',
          'out/host_debug/libflutter_engine.so',
      ],
      archive_name='linux-x64-embedder'
  )

  UploadFontSubset(api, 'linux-x64')
  UploadFlutterPatchedSdk(api)
  UploadDartSdk(api, archive_name='dart-sdk-linux-x64.zip')
  UploadWebSdk(api, archive_name='flutter-web-sdk-linux-x64.zip')

  # Rebuild with fontconfig support enabled for the desktop embedding, since it
  # should be on for libflutter_linux_gtk.so, but not libflutter_engine.so.
  RunGN(api, '--runtime-mode', 'debug', '--enable-fontconfig', '--prebuilt-dart-sdk')
  RunGN(api, '--runtime-mode', 'profile', '--no-lto', '--enable-fontconfig', '--prebuilt-dart-sdk')
  RunGN(api, '--runtime-mode', 'release', '--enable-fontconfig', '--prebuilt-dart-sdk')

  Build(api, 'host_debug')
  Build(api, 'host_profile')
  Build(api, 'host_release')

  PackageLinuxDesktopVariant(api, 'host_debug', 'linux-x64-debug')
  PackageLinuxDesktopVariant(api, 'host_profile', 'linux-x64-profile')
  PackageLinuxDesktopVariant(api, 'host_release', 'linux-x64-release')
  # Legacy; remove once Flutter tooling is updated to use the -debug location.
  PackageLinuxDesktopVariant(api, 'host_debug', 'linux-x64')


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
        'python', dbg_symbols_script, '--engine-version', git_rev
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
      base_dir = 'fuchsia_%s_%s' % (mode, arch)
      symbol_dir = checkout.join('out', base_dir, '.build-id')
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


def BuildFuchsia(api):
  """
  This schedules release and profile builds for x64 and arm64 on other bots,
  and then builds the x64 and arm64 runners (which do not require LTO and thus
  are faster to build). On Linux, we also run tests for the runner against x64,
  and if they fail we cancel the scheduled builds.
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
      'python',
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


def BuildMac(api):
  if api.properties.get('build_host', True):
    RunGN(api, '--runtime-mode', 'debug', '--no-lto', '--full-dart-sdk', '--prebuilt-dart-sdk')
    RunGN(api, '--runtime-mode', 'profile', '--no-lto', '--prebuilt-dart-sdk')
    RunGN(api, '--runtime-mode', 'release', '--no-lto', '--prebuilt-dart-sdk')

    Build(api, 'host_debug')
    Build(api, 'host_profile')
    RunTests(api, 'host_profile', types='engine')
    Build(api, 'host_release')
    api.file.listdir(
        'host_release zips',
        GetCheckoutPath(api).join('out', 'host_release', 'zip_archives'))

    host_debug_path = GetCheckoutPath(api).join('out', 'host_debug')
    host_profile_path = GetCheckoutPath(api).join('out', 'host_profile')
    host_release_path = GetCheckoutPath(api).join('out', 'host_release')

    api.zip.directory(
        'Archive FlutterEmbedder.framework',
        host_debug_path.join('FlutterEmbedder.framework'),
        host_debug_path.join('FlutterEmbedder.framework.zip')
    )

    api.zip.directory(
        'Archive FlutterMacOS.framework',
        host_debug_path.join('FlutterMacOS.framework'),
        host_debug_path.join('FlutterMacOS.framework.zip')
    )
    api.zip.directory(
        'Archive FlutterMacOS.framework profile',
        host_profile_path.join('FlutterMacOS.framework'),
        host_profile_path.join('FlutterMacOS.framework.zip')
    )
    api.zip.directory(
        'Archive FlutterMacOS.framework release',
        host_release_path.join('FlutterMacOS.framework'),
        host_release_path.join('FlutterMacOS.framework.zip')
    )

    UploadArtifacts(
        api, 'darwin-x64', [
            ICU_DATA_PATH,
            'out/host_debug/flutter_tester',
            'out/host_debug/gen/flutter/lib/snapshot/isolate_snapshot.bin',
            'out/host_debug/gen/flutter/lib/snapshot/vm_isolate_snapshot.bin',
            'out/host_debug/gen/frontend_server.dart.snapshot',
            'out/host_debug/gen_snapshot',
        ]
    )
    UploadArtifacts(
        api, 'darwin-x64-profile', [
            'out/host_profile/gen_snapshot',
        ]
    )
    UploadArtifacts(
        api, 'darwin-x64-release', [
            'out/host_release/gen_snapshot',
        ]
    )

    UploadArtifacts(
        api,
        'darwin-x64', ['out/host_debug/FlutterEmbedder.framework.zip'],
        archive_name='FlutterEmbedder.framework.zip'
    )

    flutter_podspec = \
        'flutter/shell/platform/darwin/macos/framework/FlutterMacOS.podspec'
    UploadArtifacts(
        api,
        'darwin-x64-debug', [
            'out/host_debug/FlutterMacOS.framework.zip',
            flutter_podspec,
        ],
        archive_name='FlutterMacOS.framework.zip'
    )
    UploadArtifacts(
        api,
        'darwin-x64-profile', [
            'out/host_profile/FlutterMacOS.framework.zip',
            flutter_podspec,
        ],
        archive_name='FlutterMacOS.framework.zip'
    )
    UploadArtifacts(
        api,
        'darwin-x64-release', [
            'out/host_release/FlutterMacOS.framework.zip',
            flutter_podspec,
        ],
        archive_name='FlutterMacOS.framework.zip'
    )
    UploadFontSubset(api, 'darwin-x64')
    # Legacy; remove once Flutter tooling is updated to use the -debug location.
    UploadArtifacts(
        api,
        'darwin-x64', [
            'out/host_debug/FlutterMacOS.framework.zip',
            flutter_podspec,
        ],
        archive_name='FlutterMacOS.framework.zip'
    )

    UploadDartSdk(api, archive_name='dart-sdk-darwin-x64.zip')
    UploadWebSdk(api, archive_name='flutter-web-sdk-darwin-x64.zip')

  if api.properties.get('build_android_aot', True):
    RunGN(api, '--runtime-mode', 'profile', '--android')
    RunGN(api, '--runtime-mode', 'profile', '--android', '--android-cpu=arm64')
    RunGN(api, '--runtime-mode', 'profile', '--android', '--android-cpu=x64')
    RunGN(api, '--runtime-mode', 'release', '--android')
    RunGN(api, '--runtime-mode', 'release', '--android', '--android-cpu=arm64')
    RunGN(api, '--runtime-mode', 'release', '--android', '--android-cpu=x64')

    Build(api, 'android_profile', 'flutter/lib/snapshot')
    Build(api, 'android_profile_arm64', 'flutter/lib/snapshot')
    Build(api, 'android_profile_x64', 'flutter/lib/snapshot')
    Build(api, 'android_release', 'flutter/lib/snapshot')
    Build(api, 'android_release_arm64', 'flutter/lib/snapshot')
    Build(api, 'android_release_x64', 'flutter/lib/snapshot')

    UploadArtifacts(
        api,
        "android-arm-profile", [
            'out/android_profile/clang_x64/gen_snapshot',
        ],
        archive_name='darwin-x64.zip'
    )
    UploadArtifacts(
        api,
        "android-arm64-profile", [
            'out/android_profile_arm64/clang_x64/gen_snapshot',
        ],
        archive_name='darwin-x64.zip'
    )
    UploadArtifacts(
        api,
        "android-x64-profile", [
            'out/android_profile_x64/clang_x64/gen_snapshot',
        ],
        archive_name='darwin-x64.zip'
    )
    UploadArtifacts(
        api,
        "android-arm-release", [
            'out/android_release/clang_x64/gen_snapshot',
        ],
        archive_name='darwin-x64.zip'
    )
    UploadArtifacts(
        api,
        "android-arm64-release", [
            'out/android_release_arm64/clang_x64/gen_snapshot',
        ],
        archive_name='darwin-x64.zip'
    )
    UploadArtifacts(
        api,
        "android-x64-release", [
            'out/android_release_x64/clang_x64/gen_snapshot',
        ],
        archive_name='darwin-x64.zip'
    )


def PackageIOSVariant(
    api,
    label,
    arm64_out,
    armv7_out,
    sim_x64_out,
    sim_arm64_out,
    bucket_name,
    strip_bitcode=False
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
      '--armv7-out-dir',
      api.path.join(out_dir, armv7_out),
      '--simulator-x64-out-dir',
      api.path.join(out_dir, sim_x64_out),
      '--simulator-arm64-out-dir',
      api.path.join(out_dir, sim_arm64_out),
  ]

  if strip_bitcode:
    create_ios_framework_cmd.append('--strip-bitcode')

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
      '--armv7-out-dir',
      api.path.join(out_dir, armv7_out),
  ]

  with api.context(cwd=checkout):
    api.step(
        'Create macOS %s gen_snapshot' % label, create_macos_gen_snapshot_cmd
    )

  label_root = checkout.join('out', label)
  api.file.copy(
      'Copy podspec for %s' % label,
      checkout
      .join('flutter/shell/platform/darwin/ios/framework/Flutter.podspec'),
      label_root,
  )

  # Upload the artifacts to cloud storage.
  file_artifacts = [
      'Flutter.podspec',
      'gen_snapshot_armv7',
      'gen_snapshot_arm64',
  ]
  directory_artifacts = [
      'Flutter.xcframework',
  ]

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


def BuildIOS(api):
  # Simulator doesn't use bitcode.
  # Simulator binary is needed in all runtime modes.
  RunGN(api, '--ios', '--runtime-mode', 'debug', '--simulator', '--no-lto')
  RunGN(api, '--ios', '--runtime-mode', 'debug', '--simulator', '--simulator-cpu=arm64', '--no-lto', '--no-goma')
  Build(api, 'ios_debug_sim')
  Build(api, 'ios_debug_sim_arm64')

  if api.properties.get('ios_debug', True):
    RunGN(api, '--ios', '--runtime-mode', 'debug', '--bitcode')
    RunGN(api, '--ios', '--runtime-mode', 'debug', '--bitcode', '--ios-cpu=arm')

    Build(api, 'ios_debug')
    Build(api, 'ios_debug_arm')

    BuildObjcDoc(api)

    PackageIOSVariant(
        api, 'debug', 'ios_debug', 'ios_debug_arm', 'ios_debug_sim',
        'ios_debug_sim_arm64', 'ios'
    )

  if api.properties.get('ios_profile', True):
    RunGN(api, '--ios', '--runtime-mode', 'profile', '--bitcode')
    RunGN(
        api, '--ios', '--runtime-mode', 'profile', '--bitcode', '--ios-cpu=arm'
    )
    Build(api, 'ios_profile')
    Build(api, 'ios_profile_arm')
    PackageIOSVariant(
        api, 'profile', 'ios_profile', 'ios_profile_arm', 'ios_debug_sim',
        'ios_debug_sim_arm64', 'ios-profile'
    )

  if api.properties.get('ios_release', True):
    RunGN(api, '--ios', '--runtime-mode', 'release', '--bitcode', '--no-goma')
    RunGN(
        api, '--ios', '--runtime-mode', 'release', '--bitcode', '--no-goma',
        '--ios-cpu=arm'
    )
    x64_release = api.futures.spawn(AutoninjaBuild, api, 'ios_release')
    arm64_release = api.futures.spawn(AutoninjaBuild, api, 'ios_release_arm')
    for rel_future in api.futures.iwait([x64_release, arm64_release]):
      rel_future.result()
    PackageIOSVariant(
        api, 'release', 'ios_release', 'ios_release_arm', 'ios_debug_sim',
        'ios_debug_sim_arm64', 'ios-release'
    )

    # Create a bitcode-stripped version. This will help customers who do not
    # need bitcode, which significantly increases download size. This should
    # be removed when bitcode is enabled by default in Flutter.
    PackageIOSVariant(
        api, 'release', 'ios_release', 'ios_release_arm', 'ios_debug_sim',
        'ios_debug_sim_arm64', 'ios-release-nobitcode', True
    )


def PackageWindowsDesktopVariant(api, label, bucket_name):
  artifacts = [
      'out/%s/flutter_export.h' % label,
      'out/%s/flutter_windows.h' % label,
      'out/%s/flutter_messenger.h' % label,
      'out/%s/flutter_plugin_registrar.h' % label,
      'out/%s/flutter_texture_registrar.h' % label,
      'out/%s/flutter_windows.dll' % label,
      'out/%s/flutter_windows.dll.exp' % label,
      'out/%s/flutter_windows.dll.lib' % label,
      'out/%s/flutter_windows.dll.pdb' % label,
  ]
  if bucket_name.endswith('profile') or bucket_name.endswith('release'):
    artifacts.append('out/%s/gen_snapshot.exe' % label)
  UploadArtifacts(
      api, bucket_name, artifacts, archive_name='windows-x64-flutter.zip'
  )


def PackageWindowsUwpDesktopVariant(api, label, bucket_name):
  artifacts = [
      'out/%s/flutter_export.h' % label,
      'out/%s/flutter_windows.h' % label,
      'out/%s/flutter_messenger.h' % label,
      'out/%s/flutter_plugin_registrar.h' % label,
      'out/%s/flutter_texture_registrar.h' % label,
      'out/%s/flutter_windows_winuwp.dll' % label,
      'out/%s/flutter_windows_winuwp.dll.exp' % label,
      'out/%s/flutter_windows_winuwp.dll.lib' % label,
      'out/%s/flutter_windows_winuwp.dll.pdb' % label,
      'out/%s/uwptool.exe' % label,
  ]
  if bucket_name.endswith('profile') or bucket_name.endswith('release'):
    artifacts.append('out/%s/gen_snapshot.exe' % label)
  UploadArtifacts(
      api, bucket_name, artifacts, archive_name='windows-uwp-x64-flutter.zip'
  )


def BuildWindows(api):
  if api.properties.get('build_host', True):
    RunGN(api, '--runtime-mode', 'debug', '--full-dart-sdk', '--no-lto', '--prebuilt-dart-sdk')
    Build(api, 'host_debug')
    RunTests(api, 'host_debug', types='engine')
    RunGN(api, '--runtime-mode', 'profile', '--no-lto', '--prebuilt-dart-sdk')
    Build(api, 'host_profile', 'windows', 'gen_snapshot')
    RunGN(api, '--runtime-mode', 'release', '--no-lto', '--prebuilt-dart-sdk')
    Build(api, 'host_release', 'windows', 'gen_snapshot')
    if BuildFontSubset(api):
      Build(api, 'host_release', 'flutter/tools/font-subset')

    api.file.listdir(
        'host_release zips',
        GetCheckoutPath(api).join('out', 'host_release', 'zip_archives'))

    UploadArtifacts(
        api, 'windows-x64', [
            ICU_DATA_PATH,
            'out/host_debug/flutter_tester.exe',
            'out/host_debug/gen/flutter/lib/snapshot/isolate_snapshot.bin',
            'out/host_debug/gen/flutter/lib/snapshot/vm_isolate_snapshot.bin',
            'out/host_debug/gen/frontend_server.dart.snapshot',
        ]
    )

    UploadArtifacts(
        api,
        'windows-x64', [
            'out/host_debug/flutter_embedder.h',
            'out/host_debug/flutter_engine.dll',
            'out/host_debug/flutter_engine.dll.exp',
            'out/host_debug/flutter_engine.dll.lib',
            'out/host_debug/flutter_engine.dll.pdb',
        ],
        archive_name='windows-x64-embedder.zip'
    )

    PackageWindowsDesktopVariant(api, 'host_debug', 'windows-x64-debug')
    PackageWindowsDesktopVariant(api, 'host_profile', 'windows-x64-profile')
    PackageWindowsDesktopVariant(api, 'host_release', 'windows-x64-release')
    api.bucket_util.upload_folder(
        'Upload windows-x64 Flutter library C++ wrapper',
        'src/out/host_debug',
        'cpp_client_wrapper',
        'flutter-cpp-client-wrapper.zip',
        platform='windows-x64'
    )
    # Legacy; remove once Flutter tooling is updated to use the -debug location.
    PackageWindowsDesktopVariant(api, 'host_debug', 'windows-x64')

    UploadFontSubset(api, 'windows-x64')
    UploadDartSdk(api, archive_name='dart-sdk-windows-x64.zip')
    UploadWebSdk(api, archive_name='flutter-web-sdk-windows-x64.zip')

  if api.properties.get('build_windows_uwp', True):
    RunGN(api, '--runtime-mode', 'debug', '--winuwp', '--no-lto', '--prebuilt-dart-sdk')
    RunGN(api, '--runtime-mode', 'profile', '--winuwp', '--prebuilt-dart-sdk')
    RunGN(api, '--runtime-mode', 'release', '--winuwp', '--prebuilt-dart-sdk')
    Build(api, 'winuwp_debug')
    PackageWindowsUwpDesktopVariant(api, 'winuwp_debug', 'windows-x64-debug')
    Build(api, 'winuwp_profile')
    PackageWindowsUwpDesktopVariant(
        api, 'winuwp_profile', 'windows-x64-profile'
    )
    Build(api, 'winuwp_release')
    PackageWindowsUwpDesktopVariant(
        api, 'winuwp_release', 'windows-x64-release'
    )

  if api.properties.get('build_android_aot', True):
    RunGN(api, '--runtime-mode', 'profile', '--android')
    RunGN(api, '--runtime-mode', 'profile', '--android', '--android-cpu=arm64')
    RunGN(api, '--runtime-mode', 'profile', '--android', '--android-cpu=x64')
    RunGN(api, '--runtime-mode', 'release', '--android')
    RunGN(api, '--runtime-mode', 'release', '--android', '--android-cpu=arm64')
    RunGN(api, '--runtime-mode', 'release', '--android', '--android-cpu=x64')
    Build(api, 'android_profile', 'gen_snapshot')
    Build(api, 'android_profile_arm64', 'gen_snapshot')
    Build(api, 'android_profile_x64', 'gen_snapshot')
    Build(api, 'android_release', 'gen_snapshot')
    Build(api, 'android_release_arm64', 'gen_snapshot')
    Build(api, 'android_release_x64', 'gen_snapshot')
    UploadArtifacts(
        api,
        "android-arm-profile", [
            'out/android_profile/gen_snapshot.exe',
        ],
        archive_name='windows-x64.zip'
    )
    UploadArtifacts(
        api,
        "android-arm64-profile", [
            'out/android_profile_arm64/gen_snapshot.exe',
        ],
        archive_name='windows-x64.zip'
    )
    UploadArtifacts(
        api,
        "android-x64-profile", [
            'out/android_profile_x64/gen_snapshot.exe',
        ],
        archive_name='windows-x64.zip'
    )
    UploadArtifacts(
        api,
        "android-arm-release", [
            'out/android_release/gen_snapshot.exe',
        ],
        archive_name='windows-x64.zip'
    )
    UploadArtifacts(
        api,
        "android-arm64-release", [
            'out/android_release_arm64/gen_snapshot.exe',
        ],
        archive_name='windows-x64.zip'
    )
    UploadArtifacts(
        api,
        "android-x64-release", ['out/android_release_x64/gen_snapshot.exe'],
        archive_name='windows-x64.zip'
    )


def UploadJavadoc(api, variant):
  checkout = GetCheckoutPath(api)
  api.bucket_util.safe_upload(
      checkout.join('out/%s/zip_archives/android-javadoc.zip' % variant),
      GetCloudPath(api, 'android-javadoc.zip')
  )


@contextmanager
def InstallGems(api):
  gem_dir = api.path['start_dir'].join('gems')
  api.file.ensure_directory('mkdir gems', gem_dir)

  with api.context(cwd=gem_dir):
    api.step(
        'install jazzy', [
            'gem', 'install', 'jazzy:' + api.properties['jazzy_version'],
            '--install-dir', '.'
        ]
    )
  with api.context(env={"GEM_HOME": gem_dir},
                   env_prefixes={'PATH': [gem_dir.join('bin')]}):
    yield


def BuildObjcDoc(api):
  """Builds documentation for the Objective-C variant of engine."""
  checkout = GetCheckoutPath(api)
  with api.os_utils.make_temp_directory('BuildObjcDoc') as temp_dir:
    objcdoc_cmd = [checkout.join('flutter/tools/gen_objcdoc.sh'), temp_dir]
    with api.context(cwd=checkout.join('flutter')):
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
  api.goma.ensure()
  dart_bin = checkout.join(
      'third_party', 'dart', 'tools', 'sdks', 'dart-sdk', 'bin'
  )

  android_home = checkout.join('third_party', 'android_tools', 'sdk')

  env = {
    'GOMA_DIR': api.goma.goma_dir,
    'ANDROID_HOME': str(android_home),
  }

  use_prebuilt_dart = (api.properties.get('build_host', True) or
                       api.properties.get('build_windows_uwp', True) or
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

  clobber = api.properties.get('clobber', True)
  api.repo_util.engine_checkout(cache_root, env, env_prefixes, clobber)

  # Delete derived data on mac. This is a noop for other platforms.
  api.os_utils.clean_derived_data()

  # Ensure required deps are installed
  api.flutter_deps.required_deps(
      env, env_prefixes, api.properties.get('dependencies', [])
  )

  # Various scripts we run assume access to depot_tools on path for `ninja`.
  with api.context(cwd=cache_root, env=env,
                   env_prefixes=env_prefixes), api.depot_tools.on_path():

    api.gclient.runhooks()

    try:
      if api.platform.is_linux:
        if api.properties.get('build_host', True):
          BuildLinux(api)
        if env_properties.SKIP_ANDROID != 'TRUE':
          BuildLinuxAndroid(api, env_properties.SWARMING_TASK_ID)
        if api.properties.get('build_fuchsia', True):
          BuildFuchsia(api)
        VerifyExportedSymbols(api)

      if api.platform.is_mac:
        with SetupXcode(api):
          BuildMac(api)
          if api.properties.get('build_ios', True):
            with InstallGems(api):
              BuildIOS(api)
          if api.properties.get('build_fuchsia', True):
            BuildFuchsia(api)
          VerifyExportedSymbols(api)

      if api.platform.is_win:
        BuildWindows(api)
    finally:
      api.logs_util.upload_logs('engine')
      # This is to clean up leaked processes.
      api.os_utils.kill_processes()

  # Notifies of build completion
  # TODO(crbug.com/843720): replace this when user defined notifications is implemented.
  NotifyPubsub(
      api, api.buildbucket.builder_name, api.buildbucket.build.builder.bucket
  )

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
              if maven and platform in ['mac', 'win']:
                continue
              test = api.test(
                  '%s%s%s%s%s%s' % (
                      platform, '_upload' if should_upload else '',
                      '_maven' if maven else '', '_publish_cipd'
                      if should_publish_cipd else '', '_no_lto' if no_lto else '',
                      '_font_subset' if font_subset else ''
                  ),
                  api.platform(platform, 64),
                  api.buildbucket.ci_build(
                      builder='%s Engine' % platform.capitalize(),
                      git_repo=GIT_REPO,
                      project='flutter',
                      revision='%s' % git_revision,
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
                          'build_windows_uwp': True,
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
              'android_sdk_preview_license': 'android_sdk_preview_hash'
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
      'first_bot_update_failed',
      api.buildbucket.ci_build(
          builder='Linux Host Engine',
          git_repo='https://github.com/flutter/engine',
          project='flutter'
      ),
      # Next line force a fail condition for the bot update
      # first execution.
      api.step_data("Checkout source code.bot_update", retcode=1),
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
              'android_sdk_preview_license': 'android_sdk_preview_hash'
          }
      ),
  )
  yield api.test(
      'gcloud_pubsub_failure',
      api.buildbucket.ci_build(
          builder='Linux Host Engine',
          git_repo='https://github.com/flutter/engine',
          project='flutter'
      ),
      # Next line force a fail condition for the bot update
      # first execution.
      api.step_data('gcloud pubsub', retcode=1),
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
              'android_sdk_preview_license': 'android_sdk_preview_hash'
          }
      ),
  )
  yield api.test(
      'fail_android_aot_sharded_builds',
      # 64 bit linux machine
      api.platform('linux', 64),
      api.buildbucket.ci_build(
          builder='Linux Engine', git_repo=GIT_REPO, project='flutter'
      ),
      api.step_data(
          'Build and test arm64 profile.gn --android --runtime-mode profile --android-cpu arm64',
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
                    'version': 'version:1.8.0u202-b08',
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

# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager

from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from google.protobuf import struct_pb2

DEPS = [
    'depot_tools/depot_tools',
    'depot_tools/gclient',
    'flutter/bucket_util',
    'flutter/flutter_bcid',
    'flutter/goma',
    'flutter/os_utils',
    'flutter/repo_util',
    'flutter/zip',
    'fuchsia/gcloud',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/runtime',
    'recipe_engine/step',
]

# Account for ~1 hour queue time when there is a high number of commits.
DRONE_TIMEOUT_SECS = 7200

BUCKET_NAME = 'flutter_infra_release'
MAVEN_BUCKET_NAME = 'download.flutter.io'
ICU_DATA_PATH = 'third_party/icu/flutter/icudtl.dat'
GIT_REPO = ('https://flutter.googlesource.com/mirrors/engine')
IMPELLERC_SHADER_LIB_PATH = 'shader_lib'

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties


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


def RunGN(api, *args):
  checkout = GetCheckoutPath(api)
  gn_cmd = ['python3', checkout.join('flutter/tools/gn'), '--goma']
  gn_cmd.extend(args)
  # Run goma with a context having goma_dir.
  env = {'GOMA_DIR': api.goma.goma_dir}
  with api.context(env=env):
    api.step('gn %s' % ' '.join(args), gn_cmd)


def UploadArtifact(api, config, platform, artifact_name):
  path = GetCheckoutPath(api).join(
      'out', config, 'zip_archives', platform, artifact_name
  )
  api.path.mock_add_file(path)
  assert api.path.exists(path), '%s does not exist' % str(path)
  if not api.flutter_bcid.is_prod_build():
    return
  dst = '%s/%s' % (platform, artifact_name) if platform else artifact_name
  api.bucket_util.safe_upload(path, GetCloudPath(api, dst))


def BuildLinux(api):
  RunGN(
      api, '--runtime-mode', 'debug', '--target-os=linux', '--linux-cpu=arm64',
      '--prebuilt-dart-sdk'
  )
  Build(
      api, 'linux_debug_arm64', 'flutter/build/archives:artifacts',
      'flutter/build/archives:dart_sdk_archive', 'flutter/tools/font-subset',
      'flutter/shell/platform/linux:flutter_gtk'
  )

  RunGN(
      api, '--runtime-mode', 'profile', '--no-lto', '--target-os=linux',
      '--linux-cpu=arm64', '--prebuilt-dart-sdk'
  )
  Build(api, 'linux_profile_arm64', 'flutter/shell/platform/linux:flutter_gtk')

  RunGN(
      api, '--runtime-mode', 'release', '--target-os=linux',
      '--linux-cpu=arm64', '--prebuilt-dart-sdk'
  )
  Build(api, 'linux_release_arm64', 'flutter/shell/platform/linux:flutter_gtk')

  # linux_debug_arm64
  UploadArtifact(
      api,
      config='linux_debug_arm64',
      platform='linux-arm64',
      artifact_name='artifacts.zip'
  )
  UploadArtifact(
      api,
      config='linux_debug_arm64',
      platform='linux-arm64',
      artifact_name='font-subset.zip'
  )
  UploadArtifact(
      api,
      config='linux_debug_arm64',
      platform='',
      artifact_name='dart-sdk-linux-arm64.zip'
  )

  # Desktop embedding.
  UploadArtifact(
      api,
      config='linux_debug_arm64',
      platform='linux-arm64-debug',
      artifact_name='linux-arm64-flutter-gtk.zip'
  )
  UploadArtifact(
      api,
      config='linux_profile_arm64',
      platform='linux-arm64-profile',
      artifact_name='linux-arm64-flutter-gtk.zip'
  )
  UploadArtifact(
      api,
      config='linux_release_arm64',
      platform='linux-arm64-release',
      artifact_name='linux-arm64-flutter-gtk.zip'
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
      'FLUTTER_PREBUILT_DART_SDK': 'True',
  }
  env_prefixes = {}

  api.repo_util.engine_checkout(cache_root, env, env_prefixes)

  # Delete derived data on mac. This is a noop for other platforms.
  api.os_utils.clean_derived_data()

  # Various scripts we run assume access to depot_tools on path for `ninja`.
  with api.context(cwd=cache_root, env=env,
                   env_prefixes=env_prefixes), api.depot_tools.on_path():

    api.gclient.runhooks()

    if api.platform.is_linux:
      if api.properties.get('build_host', True):
        BuildLinux(api)

    if api.platform.is_mac:
      # no-op
      raise api.step.StepFailure('Mac Arm host builds not supported yet.')
    if api.platform.is_win:
      raise api.step.StepFailure('Windows Arm host builds not supported yet.')

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
  for platform in ('mac', 'linux', 'win'):
    for should_upload in (True, False):
      for bucket in (
          'prod',
          'staging',
      ):
        for experimental in (
            True,
            False,
        ):
          test = api.test(
              '%s%s_%s_%s' % (
                  platform, '_upload' if should_upload else '', bucket,
                  experimental
              ),
              api.platform(platform, 64),
              api.buildbucket.ci_build(
                  builder='%s Engine' % platform.capitalize(),
                  git_repo=GIT_REPO,
                  project='flutter',
                  revision='%s' % git_revision,
                  bucket=bucket,
              ),
              api.runtime(is_experimental=experimental),
              api.properties(
                  InputProperties(
                      clobber=False,
                      goma_jobs='1024',
                      fuchsia_ctl_version='version:0.0.2',
                      build_host=True,
                      build_fuchsia=True,
                      build_android_aot=True,
                      build_android_debug=True,
                      upload_packages=should_upload,
                      force_upload=True,
                  ),
              ),
              api.properties.environ(
                  EnvProperties(SWARMING_TASK_ID='deadbeef')
              ),
              status='FAILURE' if platform in ['mac', 'win'] else 'SUCCESS'
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
        api.runtime(is_experimental=True),
        api.properties(
            InputProperties(
                goma_jobs='1024',
                fuchsia_ctl_version='version:0.0.2',
                android_sdk_license='android_sdk_hash',
                android_sdk_preview_license='android_sdk_preview_hash',
                upload_packages=should_upload,
            )
        ),
    )
  yield api.test(
      'clobber',
      api.buildbucket.ci_build(
          builder='Linux Host Engine',
          git_repo='https://github.com/flutter/engine',
          project='flutter'
      ),
      api.runtime(is_experimental=True),
      api.properties(
          InputProperties(
              clobber=True,
              git_url='https://github.com/flutter/engine',
              goma_jobs='200',
              git_ref='refs/pull/1/head',
              fuchsia_ctl_version='version:0.0.2',
              build_host=True,
              build_fuchsia=True,
              build_android_aot=True,
              build_android_debug=True,
              android_sdk_license='android_sdk_hash',
              android_sdk_preview_license='android_sdk_preview_hash'
          )
      ),
  )
  yield api.test(
      'pull_request',
      api.buildbucket.ci_build(
          builder='Linux Host Engine',
          git_repo='https://github.com/flutter/engine',
          project='flutter'
      ),
      api.runtime(is_experimental=True),
      api.properties(
          InputProperties(
              clobber=False,
              git_url='https://github.com/flutter/engine',
              goma_jobs='200',
              git_ref='refs/pull/1/head',
              fuchsia_ctl_version='version:0.0.2',
              build_host=True,
              build_fuchsia=True,
              build_android_aot=True,
              build_android_debug=True,
              android_sdk_license='android_sdk_hash',
              android_sdk_preview_license='android_sdk_preview_hash'
          )
      ),
  )

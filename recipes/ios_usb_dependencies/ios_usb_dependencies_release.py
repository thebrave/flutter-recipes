# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager
import re

DEPS = [
    'depot_tools/gsutil',
    'flutter/flutter_bcid',
    'flutter/osx_sdk',
    'flutter/signing',
    'flutter/zip',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/runtime',
    'recipe_engine/step',
]

BUCKET_NAME = 'flutter_infra_release'


def DownloadAndCodesignPackage(api, package_name):
  temp_dir = api.path.mkdtemp('tmp')

  # Download the version file which contains the SHA for the last unsigned uploaded build
  version_file = temp_dir / 'latest_unsigned.version'
  remote_version_file = 'ios-usb-dependencies/unsigned/%s/latest_unsigned.version' % package_name
  api.gsutil.download(
      BUCKET_NAME,
      remote_version_file,
      version_file,
      name="download latest_unsigned.version"
  )
  if not api.path.exists(version_file):
    api.step.empty(
        'Failed to get latest_unsigned.version for %s' % package_name,
        status=api.step.INFRA_FAILURE,
    )
  latest_unsigned_version = api.file.read_text(
      'Read latest_unsigned.version',
      version_file,
  ).strip()

  # Download the package zip for the corresponding SHA
  package_zip_file = temp_dir / f'{package_name}.zip'
  remote_zip_file = GetCloudPath(api, package_name, latest_unsigned_version)
  api.gsutil.download(
      BUCKET_NAME,
      remote_zip_file,
      package_zip_file,
      name="download %s" % package_zip_file
  )
  if not api.path.exists(package_zip_file):
    api.step.empty(
        'Failed to get %s' % package_zip_file,
        status=api.step.INFRA_FAILURE,
    )

  # Codesign the zip and upload the signed version
  api.signing.code_sign([package_zip_file])
  api.gsutil.upload(
      package_zip_file,
      BUCKET_NAME,
      GetCloudPath(api, package_name, latest_unsigned_version, signed=True),
      link_name='%s.zip' % package_name,
      name='upload of %s.zip' % package_name,
  )


def GetCloudPath(api, package_name, commit_sha, signed=False):
  """Location of cloud bucket for unsigned binaries"""
  version_namespace = 'led' if api.runtime.is_experimental else commit_sha
  if not signed:
    return 'ios-usb-dependencies/unsigned/%s/%s/%s.zip' % (
        package_name, version_namespace, package_name
    )
  return 'ios-usb-dependencies/%s/%s/%s.zip' % (
      package_name, version_namespace, package_name
  )


def RunSteps(api):
  # If on macOS, reset Xcode in case a previous build failed to do so.
  api.osx_sdk.reset_xcode()
  # Only codesign if running in dart-internal
  if api.flutter_bcid.is_official_build():
    with api.osx_sdk('ios', devicelab=False):
      DownloadAndCodesignPackage(api, 'ios-deploy')
      DownloadAndCodesignPackage(api, 'libimobiledeviceglue')
      DownloadAndCodesignPackage(api, 'libusbmuxd')
      DownloadAndCodesignPackage(api, 'openssl')
      DownloadAndCodesignPackage(api, 'libimobiledevice')


def GenTests(api):
  yield api.test('noop_on_non_dart_internal',)
  yield api.test(
      'with_codesigning',
      api.platform.name('mac'),
      api.buildbucket.ci_build(
          project='dart-internal',
          bucket='flutter',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main'
      ),
      api.path.exists(
          api.path.cleanup_dir / 'tmp_tmp_1/latest_unsigned.version',
          api.path.cleanup_dir / 'tmp_tmp_1/ios-deploy.zip',
          api.path.cleanup_dir / 'tmp_tmp_3/latest_unsigned.version',
          api.path.cleanup_dir / 'tmp_tmp_3/libimobiledeviceglue.zip',
          api.path.cleanup_dir / 'tmp_tmp_4/latest_unsigned.version',
          api.path.cleanup_dir / 'tmp_tmp_4/libusbmuxd.zip',
          api.path.cleanup_dir / 'tmp_tmp_5/latest_unsigned.version',
          api.path.cleanup_dir / 'tmp_tmp_5/openssl.zip',
          api.path.cleanup_dir / 'tmp_tmp_6/latest_unsigned.version',
          api.path.cleanup_dir / 'tmp_tmp_6/libimobiledevice.zip',
      ),
      api.step_data(
          'Read latest_unsigned.version',
          api.file.read_text(text_content=('  123456  \n\n'))
      ),
  )
  yield api.test(
      'missing_latest_unsigned',
      api.platform.name('mac'),
      api.buildbucket.ci_build(
          project='dart-internal',
          bucket='flutter',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main'
      ),
      status='INFRA_FAILURE'
  )
  yield api.test(
      'missing_downloaded_zip',
      api.platform.name('mac'),
      api.buildbucket.ci_build(
          project='dart-internal',
          bucket='flutter',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main'
      ),
      api.path.exists(
          api.path.cleanup_dir / 'tmp_tmp_1/latest_unsigned.version',
      ),
      status='INFRA_FAILURE'
  )

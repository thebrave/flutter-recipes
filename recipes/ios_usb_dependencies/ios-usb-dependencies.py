# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager
import re

DEPS = [
    'depot_tools/gsutil',
    'flutter/osx_sdk',
    'flutter/zip',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/runtime',
    'recipe_engine/step',
]

BUCKET_NAME = 'flutter_infra_release'

# These regex are used to detect lib paths that need to be patched.
LIBUSBMUXD_PATTERN = r'^\t?(.*(libusbmuxd.*\.dylib)).*'
LIBPLIST_PATTERN = r'^\t?(.*(libplist.*\.dylib)).*'
LIBSSL_PATTERN = r'^\t?(.*(libssl.*\.dylib)).*'
LIBCRYPTO_PATTERN = r'^\t?(.*(libcrypto.*\.dylib)).*'
LIBIMOBILEDEVICE_PATTERN = r'^\t?(.*(libimobiledevice.*\.dylib)).*'
LIBIMOBILEDEVICEGLUE_PATTERN = r'^\t?(.*(libimobiledevice-glue.*\.dylib)).*'

DIRNAME_PATTERN_DICT = {
    'libusbmuxd': LIBUSBMUXD_PATTERN, 'libplist': LIBPLIST_PATTERN,
    'libssl': LIBSSL_PATTERN, 'libcrypto': LIBCRYPTO_PATTERN,
    'libimobiledevice': LIBIMOBILEDEVICE_PATTERN,
    'libimobiledeviceglue': LIBIMOBILEDEVICEGLUE_PATTERN
}

# Map between package and its artifacts that need path patch.
BIANRY_ARTIFACT_MAP = {
    'libusbmuxd': ['iproxy'], 'openssl': ['libcrypto.3.dylib'],
    'libimobiledevice': ['idevicescreenshot', 'idevicesyslog']
}


def ParseOtoolPath(input_string):
  '''Parse paths that need to be patched to relative paths via otool.'''
  input_lines = input_string.split('\n')
  output = {}
  for input_line in input_lines:
    for dirname, pattern in DIRNAME_PATTERN_DICT.items():
      # re.match searches from beginning of string
      match = re.match(pattern, input_line)
      if match:
        old_path = match.group(1)
        new_path = '@loader_path/../%s' % match.group(2)
        output[old_path] = new_path
  return output


def PatchLoadPath(api, ouput_path, package_name):
  '''Update dynamically linked paths in a binary'''
  if package_name not in BIANRY_ARTIFACT_MAP:
    return
  artifacts = BIANRY_ARTIFACT_MAP[package_name]
  for artifact in artifacts:
    artifact_path = ouput_path / artifact
    otool_step_data = api.step(
        'Get linked paths from %s before patch' % artifact,
        ['otool', '-L', artifact_path],
        stdout=api.raw_io.output_text()
    )
    old_paths_to_new_paths = ParseOtoolPath(otool_step_data.stdout.rstrip())
    for old_path in old_paths_to_new_paths:
      new_path = old_paths_to_new_paths[old_path]
      api.step(
          'Patch %s with install_name_tool' % artifact_path,
          ['install_name_tool', '-change', old_path, new_path, artifact_path],
      )
    api.step(
        'Get linked paths from %s after patch' % artifact_path,
        ['otool', '-L', artifact_path]
    )


def GetCloudPath(api, package_name, commit_sha):
  """Location of cloud bucket for unsigned binaries"""
  version_namespace = 'led' if api.runtime.is_experimental else commit_sha
  return 'ios-usb-dependencies/unsigned/%s/%s/%s.zip' % (
      package_name, version_namespace, package_name
  )


def UpdateEnv(
    api, env, env_prefixes, package_name, package_install_dir, update_path,
    update_library_path, update_pkg_config_path
):
  """Updates environment variables based on requirments.

  Args:

      env(dict): current environment variables.
      env_prefixes(dict):  current environment prefixes variables.
      package_name(str): the name of the package to be built.
      package_install_dir(path): path to the package install dir.
      upload(bool): a flag indicating whether there are artifacts to upload.
      update_path(bool): a flag indicating whether there are PATH updates.
      update_library_path(bool): a flag indicating whether there are LIBRARY_PATH updates.
      update_pkg_config_path(bool): a flag indicating whether there are PKG_CONFIG_PATH updates.
  """
  if package_name == 'libimobiledeviceglue':
    env['CPATH'] = '%s/include' % package_install_dir
  if update_path:
    paths = env_prefixes.get('PATH', [])
    paths.append('%s/bin' % package_install_dir)
    env_prefixes['PATH'] = paths
  if update_library_path:
    library_path = env_prefixes.get('LIBRARY_PATH', [])
    library_path.append('%s/lib' % package_install_dir)
    env_prefixes['LIBRARY_PATH'] = library_path
  if update_pkg_config_path:
    pkg_config_path = env_prefixes.get('PKG_CONFIG_PATH', [])
    pkg_config_path.append('%s/lib/pkgconfig' % package_install_dir)
    env_prefixes['PKG_CONFIG_PATH'] = pkg_config_path


def GetDylibFilenames(api, dir, package_name):
  """Returns a list of file names that matches dylib file regex in given directory.

  A package_name maps to a regex pattern based on DIRNAME_PATTERN_DICT(dict). All
  file names in the current dir that matches this regex pattern are returned.

  Args:

      dir(Path): The directory in which to search for dylib files.
      package_name(str): Name of the ios usb dependency passed in.
  """
  directory_paths = api.file.listdir(
      "checking dylib file inside: %s" % dir,
      dir,
      test_data=[
          dir / "libimobiledevice-1.0.6.dylib", dir / "libplist-2.0.3.dylib"
      ]
  )
  directory_string_paths = [('%s' % path) for path in directory_paths]
  matched_dylib_names = []

  pattern = DIRNAME_PATTERN_DICT[package_name]
  for dylib_path in directory_string_paths:
    # re.match searches from beginning of string
    match = re.match(pattern, dylib_path)
    if match:
      matched_dylib_names.append(dylib_path.split("/")[-1])
  return matched_dylib_names


def EmbedCodesignConfiguration(api, package_out_dir, package_name):
  """Embed metadata file for Mac code signing into ios usb dependency artifacts.

  Two files are embedded into the generated artifact.
  entitlements.txt: The list of binaries that need to be code signed with entitlements.
  without_entitlements.txt: Filenames of binaries in artifacts that should be code signed, but not with entitlements.

  Args:

      package_out_dir(Path): The directory in which ios usb dependency artifact is generated.
      package_name(str): Name of the ios usb dependency passed in.
  """
  entitlement_file_contents = []
  without_entitlement_file_contents = []
  if package_name == "ios-deploy":
    entitlement_file_contents = ["ios-deploy"]
  elif package_name == "libimobiledevice":
    entitlement_file_contents = [
        "idevicescreenshot",
        "idevicesyslog",
    ]
    without_entitlement_file_contents = GetDylibFilenames(
        api, package_out_dir, package_name
    )
  elif package_name == "libplist":
    without_entitlement_file_contents = GetDylibFilenames(
        api, package_out_dir, package_name
    )
  elif package_name == "libusbmuxd":
    entitlement_file_contents = [
        "iproxy",
    ]
    without_entitlement_file_contents = GetDylibFilenames(
        api, package_out_dir, package_name
    )
  elif package_name == "openssl":
    without_entitlement_file_contents = GetDylibFilenames(
        api, package_out_dir, "libssl"
    ) + GetDylibFilenames(api, package_out_dir, "libcrypto")
  elif package_name == "libimobiledeviceglue":
    without_entitlement_file_contents = GetDylibFilenames(
        api, package_out_dir, package_name
    )

  api.file.write_text(
      "writing entitlements codesign list for %s" % package_name,
      package_out_dir / "entitlements.txt",
      '\n'.join(entitlement_file_contents) + '\n'
  )
  api.file.write_text(
      "writing the list of files to be codesigned without entitlements for %s" %
      package_name, package_out_dir / "without_entitlements.txt",
      '\n'.join(without_entitlement_file_contents) + '\n'
  )


def UploadPackage(
    api, package_name, work_dir, package_out_dir, upload, commit_sha
):
  """Upload package artifacts to GCS.

  Args:

      package_name(str): the name of the package to be built.
      work_dir(path): path to work dir.
      package_out_dir(bool): path to the artifacts location.
      upload(bool): a flag indicating whether there are artifacts to upload.
      commit_sha(str): commit sha of current build.
  """
  if not upload:
    return
  EmbedCodesignConfiguration(api, package_out_dir, package_name)
  package_zip_file = work_dir / f'{package_name}.zip'
  api.zip.directory(
      'zipping %s dir' % package_name, package_out_dir, package_zip_file
  )
  api.gsutil.upload(
      package_zip_file,
      BUCKET_NAME,
      GetCloudPath(api, package_name, commit_sha),
      link_name='%s.zip' % package_name,
      name='upload of %s.zip' % package_name,
  )


def BuildPackage(
    api,
    env,
    env_prefixes,
    package_name,
    upload=False,
    update_path=False,
    update_library_path=False,
    update_pkg_config_path=False
):
  """Builds packages and and upload artifacts to GCS.

  Args:

      env(dict): current environment variables.
      env_prefixes(dict):  current environment prefixes variables.
      package_name(str): the name of the package to be built.
      upload(bool): a flag indicating whether there are artifacts to upload.
      update_path(bool): a flag indicating whether there are PATH updates.
      update_library_path(bool): a flag indicating whether there are LIBRARY_PATH updates.
      update_pkg_config_path(bool): a flag indicating whether there are PKG_CONFIG_PATH updates.
  """
  work_dir = api.path.start_dir
  src_dir = work_dir / 'src'
  package_src_dir = src_dir / package_name
  package_install_dir = src_dir / f'{package_name}_install'
  package_out_dir = src_dir / f'{package_name}_output'
  api.file.ensure_directory('mkdir %s' % package_src_dir, package_src_dir)
  api.file.ensure_directory(
      'mkdir %s' % package_install_dir, package_install_dir
  )
  api.file.ensure_directory('mkdir %s' % package_out_dir, package_out_dir)

  build_script = api.resource('%s.sh' % package_name)
  api.step('make %s executable' % build_script, ['chmod', '777', build_script])
  with api.context(env=env, env_prefixes=env_prefixes):
    api.step(
        'install %s' % package_name,
        [build_script, package_src_dir, package_install_dir, package_out_dir]
    )
  commit_sha_file = package_src_dir / 'commit_sha.txt'
  commit_sha = None
  if api.path.exists(commit_sha_file):
    commit_sha = api.file.read_text(
        'read commit_sha.txt for %s' % package_name, commit_sha_file
    ).strip()
  UpdateEnv(
      api, env, env_prefixes, package_name, package_install_dir, update_path,
      update_library_path, update_pkg_config_path
  )
  PatchLoadPath(api, package_out_dir, package_name)
  UploadPackage(
      api, package_name, work_dir, package_out_dir, upload, commit_sha
  )


def RunSteps(api):
  # If on macOS, reset Xcode in case a previous build failed to do so.
  api.osx_sdk.reset_xcode()

  with api.osx_sdk('ios', devicelab=False):
    env_prefixes = {'PATH': [], 'LIBRARY_PATH': []}
    env = {}
    BuildPackage(api, env, env_prefixes, 'ios-deploy', upload=True)
    BuildPackage(
        api, env, env_prefixes, 'libplist', upload=True, update_path=True
    )
    BuildPackage(api, env, env_prefixes, 'bison', update_path=True)
    BuildPackage(api, env, env_prefixes, 'libtasn1', update_path=True)
    BuildPackage(api, env, env_prefixes, 'libusb', update_library_path=True)
    BuildPackage(
        api,
        env,
        env_prefixes,
        'libimobiledeviceglue',
        upload=True,
        update_library_path=True,
        update_pkg_config_path=True
    )
    BuildPackage(
        api,
        env,
        env_prefixes,
        'libusbmuxd',
        upload=True,
        update_path=True,
        update_pkg_config_path=True
    )
    BuildPackage(
        api,
        env,
        env_prefixes,
        'openssl',
        upload=True,
        update_path=True,
        update_library_path=True,
        update_pkg_config_path=True
    )
    BuildPackage(api, env, env_prefixes, 'libimobiledevice', upload=True)


def GenTests(api):
  yield api.test(
      'basic',
      api.path.exists(api.path.start_dir / 'src/ios-deploy/commit_sha.txt',),
      api.step_data(
          'Get linked paths from iproxy before patch',
          stdout=api.raw_io.output_text(
              '\t/opt/s/w/ir/x/w/src/libusbmuxd_install/lib/libusbmuxd-2.0.6.dylib (compatibility version 7.0.0, current version 7.0.0)'
          ),
          retcode=0
      )
  )

# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager
from RECIPE_MODULES.flutter.flutter_bcid.api import BcidStage
import re

DEPS = [
    'depot_tools/depot_tools',
    'depot_tools/git',
    'flutter/archives',
    'flutter/flutter_bcid',
    'flutter/flutter_deps',
    'flutter/repo_util',
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/runtime',
    'recipe_engine/step',
]

PACKAGED_REF_RE = re.compile(r'^refs/heads/(.+)$')

PLATFORMS_MAP = {
    'win': 'windows',
    'mac': 'macos',
    'linux': 'linux'
}


@contextmanager
def Install7za(api):
  if api.platform.is_win:
    sevenzip_cache_dir = api.path['cache'].join('builder', '7za')
    api.cipd.ensure(
        sevenzip_cache_dir,
        api.cipd.EnsureFile().add_package(
            'flutter_internal/tools/7za/${platform}', 'version:19.00'
        )
    )
    with api.context(env_prefixes={'PATH': [sevenzip_cache_dir]}):
      yield
  else:
    yield


def CreateAndUploadFlutterPackage(api, git_hash, branch, packaging_script):
  """Prepares, builds, and uploads an all-inclusive archive package.

    Args:
      git_hash(str): Hash corresponding to git commit.
      branch(str): Name of the flutter branch.
      packaging_script(str): Script that will prepare, create and publish a flutter archive.
  """
  flutter_executable = 'flutter' if not api.platform.is_win else 'flutter.bat'
  dart_executable = 'dart' if not api.platform.is_win else 'dart.exe'
  work_dir = api.path['start_dir'].join('archive')
  api.step('flutter doctor', [flutter_executable, 'doctor'])
  api.step('download dependencies', [flutter_executable, 'update-packages'])
  api.flutter_bcid.report_stage(BcidStage.COMPILE.value)
  api.file.rmtree('clean archive work directory', work_dir)
  api.file.ensure_directory('(re)create archive work directory', work_dir)
  with Install7za(api):
    with api.context(cwd=api.path['start_dir']):
      step_args = [
          dart_executable, packaging_script,
          '--temp_dir=%s' % work_dir,
          '--revision=%s' % git_hash,
          '--branch=%s' % branch
      ]
      api.step('prepare and create a flutter archive', step_args)

      flutter_pkg_absolute_path = GetFlutterPackageAbsolutePath(api, work_dir)
      file_name = api.path.basename(flutter_pkg_absolute_path)
      platform_name = PLATFORMS_MAP[api.platform.name]
      dest_archive = '/%s/%s' % (branch, platform_name)
      dest_gs = 'gs://flutter_infra_release/releases%s' % dest_archive
      api.flutter_bcid.report_stage(BcidStage.UPLOAD.value)
      if branch in ('beta', 'stable'):
        # only publish using upload_artifact if is branch is beta or stable
        # publish both package and metadata which has been updated
        # by the packaging_script
        pkg_gs_path = '%s/%s' % (dest_gs, file_name)
        metadata_absolute_path = GetFlutterMetadataAbsolutePath(api, work_dir)
        metadata_filename = api.path.basename(metadata_absolute_path)
        metadata_gs_path = "%s/%s" % (dest_gs, metadata_filename)
        api.archives.upload_artifact(metadata_absolute_path, metadata_gs_path)
      else:
        # add experimental subpath if branch is not beta or stable
        pkg_gs_path = '%s/%s/%s' % (dest_gs, 'experimental', file_name)
      api.archives.upload_artifact(flutter_pkg_absolute_path, pkg_gs_path)
      api.flutter_bcid.upload_provenance(flutter_pkg_absolute_path, pkg_gs_path)
      api.flutter_bcid.report_stage(BcidStage.UPLOAD_COMPLETE.value)


def GetFlutterPackageAbsolutePath(api, work_dir):
  """Gets full flutter package directory if it exists.

  Args:
    work_dir(str): Path to working directory.

  Returns:
    str: Fully qualified path to flutter package directory.
  """
  suffix = 'tar.xz' if api.platform.is_linux else 'zip'
  files = api.file.glob_paths('get flutter archive file name', work_dir,
                              '*flutter*.%s' % suffix, test_data=['flutter-archive-package.%s' % suffix])
  return files[0] if len(files) == 1 else None

def GetFlutterMetadataAbsolutePath(api, work_dir):
  """Gets local metadata absolute path.

  Returns:
    str: Path to the metadata file which contains a platform suffix.
  """
  metadata_filename = "releases_"
  if api.platform.is_linux:
    metadata_filename += "linux.json"
  elif api.platform.is_mac:
    metadata_filename += "macos.json"
  elif api.platform.is_win:
    metadata_filename += "windows.json"
  files = api.file.glob_paths('get flutter archive file name', work_dir,
                            metadata_filename, test_data=['releases_linux.json'])
  return files[0] if len(files) == 1 else None

def RunSteps(api):
  api.flutter_bcid.report_stage(BcidStage.START.value)
  git_ref = api.properties.get('git_ref') or api.buildbucket.gitiles_commit.ref
  assert git_ref

  api.flutter_bcid.report_stage(BcidStage.FETCH.value)
  checkout_path = api.path['start_dir'].join('flutter')
  git_url = api.properties.get('git_url') or 'https://flutter.googlesource.com/mirrors/flutter'
  # Call this just to obtain release_git_hash so the script knows which commit
  # to release
  with api.step.nest('determine release revision'):
    release_git_hash = api.repo_util.checkout(
        'flutter',
        checkout_path=checkout_path,
        url=git_url,
        ref=git_ref,
    )
  # For creating the packages, we need to have the master branch version of the
  # script.
  with api.step.nest('checkout framework from master'):
    api.repo_util.checkout(
        'flutter',
        checkout_path=checkout_path,
        url=git_url,
        ref='master',
    )
  env, env_prefixes = api.repo_util.flutter_environment(checkout_path)

  api.flutter_deps.required_deps(
      env, env_prefixes, api.properties.get('dependencies', [])
  )

  packaging_script = checkout_path.join(
      'dev', 'bots', 'prepare_package.dart'
  )
  with api.context(env=env, env_prefixes=env_prefixes):
    with api.depot_tools.on_path():
      match = PACKAGED_REF_RE.match(git_ref)
      if match:
        branch = match.group(1)
        CreateAndUploadFlutterPackage(api, release_git_hash, branch, packaging_script)
        # Nothing left to do on a packaging branch.
        return
      raise api.step.StepFailure(
          'could not determine the release branch: "git_ref"'
          'property should be set when manually triggering builds'
      )


def GenTests(api):
  for experimental in (True, False):
    for should_upload in (True, False):
      for platform in ('mac', 'linux', 'win'):
        for branch in ('master', 'beta', 'stable', 'flutter-release-test'):
            for bucket in ('prod', 'staging'):
              for git_ref in ('refs/heads/' + branch,
                'invalid' + branch):
                  test = api.test(
                      '%s_%s%s%s_%s' % (
                          platform,
                          git_ref,
                          '_experimental' if experimental else '',
                          '_upload' if should_upload else '',
                          bucket
                      ), api.platform(platform, 64),
                      api.buildbucket.ci_build(
                          git_ref=git_ref,
                          revision=None,
                          bucket=bucket
                      ), api.properties(
                          shard='tests',
                          fuchsia_ctl_version='version:0.0.2',
                          upload_packages=should_upload,
                          gold_tryjob=not should_upload,
                      ), api.runtime(is_experimental=experimental),
                      api.repo_util.flutter_environment_data()
                  )
                  yield test

# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager
import re

DEPS = [
    'depot_tools/depot_tools',
    'depot_tools/git',
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

PACKAGED_REF_RE = re.compile(r'^refs/heads/(beta|stable)$')


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
  """Prepares, builds, and uploads an all-inclusive archive package."""
  flutter_executable = 'flutter' if not api.platform.is_win else 'flutter.bat'
  dart_executable = 'dart' if not api.platform.is_win else 'dart.exe'
  work_dir = api.path['start_dir'].join('archive')
  api.step('flutter doctor', [flutter_executable, 'doctor'])
  api.step('download dependencies', [flutter_executable, 'update-packages'])
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
      if not api.runtime.is_experimental:
        step_args.append('--publish')
      api.step('prepare, create and publish a flutter archive', step_args)
      if api.properties.get('upload_with_cosign') is True:
        flutter_package_absolute_path = GetFlutterPackageAbsolutePath(api, work_dir)
        UploadAndSignFlutterPackage(api, flutter_package_absolute_path, git_hash, branch)


def GetFlutterPackageAbsolutePath(api, work_dir):
  """Gets full flutter package directory if it exists."""
  files = api.file.glob_paths('get flutter archive file name', work_dir, '*flutter*.tar.xz', test_data=['flutter-archive-package.tar.xz'])
  return files[0] if len(files) == 1 else None


def UploadAndSignFlutterPackage(api, flutter_path, git_hash, branch):
  """Uploads flutter package to the artifact registry, then signs it using a KMS key.
  This is all done using the package cosign.
  """
  bucket = api.buildbucket.build.builder.bucket
  if not api.runtime.is_experimental and bucket == 'prod':
    base_artifact_registry_url = 'us-docker.pkg.dev/flutter-infra/flutter-artifacts'
  else:
    base_artifact_registry_url = 'us-docker.pkg.dev/flutter-infra-staging/flutter-artifacts'

  artifact_registry_url = '%s/%s/%s/%s' % (base_artifact_registry_url, branch, git_hash, api.path.basename(flutter_path))

  gcloud_docker_config_args = [
      'gcloud',
      'auth',
      'configure-docker',
      'us-docker.pkg.dev'
  ]

  cosign_upload_args = [
      'cosign',
      'upload',
      'blob',
      '-f',
      flutter_path,
      artifact_registry_url
  ]

  ## The force parameter bypasses the confirmation prompt from cosign
  cosign_sign_args = [
      'cosign',
      'sign',
      artifact_registry_url,
      '--force'
  ]
  api.step('configure docker registry', gcloud_docker_config_args)
  api.step('upload through cosign', cosign_upload_args)
  api.step('sign flutter artifact', cosign_sign_args)


def RunSteps(api):
  git_ref = api.properties.get('git_ref') or api.buildbucket.gitiles_commit.ref
  assert git_ref
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

  # TODO(drewroen): Remove this once cosign supports keyless signing without enabling
  # experimental features.
  if api.properties.get('upload_with_cosign') is True:
    env['COSIGN_EXPERIMENTAL'] = 'true'

  api.flutter_deps.required_deps(
      env, env_prefixes, api.properties.get('dependencies', [])
  )
  release_ref = api.properties.get('release_ref') or git_ref

  packaging_script = checkout_path.join(
      'dev', 'bots', 'prepare_package.dart'
  )
  with api.context(env=env, env_prefixes=env_prefixes):
    with api.depot_tools.on_path():
      if release_ref:
        match = PACKAGED_REF_RE.match(release_ref)
        if match:
          branch = match.group(1)
          CreateAndUploadFlutterPackage(api, release_git_hash, branch, packaging_script)
          # Nothing left to do on a packaging branch.
          return
      raise api.step.StepFailure(
          'could not determine the release branch: either "release_ref" or "git_ref" properties should be set when manually triggering builds'
      )


def GenTests(api):
  for experimental in (True, False):
    for should_upload in (True, False):
      for platform in ('mac', 'linux', 'win'):
        for branch in ('master', 'beta', 'stable'):
          for upload_with_cosign in (True, False):
            for bucket in ('prod', 'staging'):
              git_ref = 'refs/heads/' + branch
              test = api.test(
                  '%s_%s%s%s%s_%s' % (
                      platform,
                      branch,
                      '_experimental' if experimental else '',
                      '_upload' if should_upload else '',
                      '_cosign' if upload_with_cosign else '',
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
                      upload_with_cosign=upload_with_cosign
                  ), api.runtime(is_experimental=experimental),
                  api.repo_util.flutter_environment_data()
              )
              yield test

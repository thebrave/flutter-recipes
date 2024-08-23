# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Recipe to run build and deploy api documentation.

from RECIPE_MODULES.flutter.flutter_bcid.api import BcidStage

DEPS = [
    'flutter/archives',
    'flutter/firebase',
    'flutter/flutter_bcid',
    'flutter/flutter_deps',
    'flutter/logs_util',
    'flutter/os_utils',
    'flutter/repo_util',
    'flutter/retry',
    'flutter/test_utils',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/defer',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]


def PrepareDocs(api, env, env_prefixes, checkout_path):
  api.flutter_bcid.report_stage(BcidStage.COMPILE.value)
  validation = api.properties.get('validation')
  # Command to postprocess documentation already archived.
  cmd_deploy_docs = ['dart', './dev/bots/post_process_docs.dart']
  # Command to build documentation.
  cmd_docs = [
      './dev/bots/docs.sh', '--output', 'dev/docs/api_docs.zip',
      '--keep-staging', '--staging-dir', 'dev/docs'
  ]
  with api.context(env=env, env_prefixes=env_prefixes, cwd=checkout_path):
    if validation == 'docs':
      api.step('Build documentation', cmd_docs)
    if validation == 'docs_deploy':
      api.step('Post process documentation', cmd_deploy_docs)
    api.logs_util.show_logs_stdout(checkout_path.join('error.log'))


def SetEnv(api, env, checkout_path):
  git_ref = api.properties.get(
      'release_ref'
  ) or api.buildbucket.gitiles_commit.ref
  # Post-processing of docs require LUCI_BRANCH to be set when running from dart-internal.
  env['LUCI_BRANCH'] = git_ref.replace('refs/heads/', '')
  # Override LUCI_BRANCH for docs and release candidate branches. Docs built from
  # release candidate branches need to be build as stable to ensure they are processed
  # correctly.
  checkout_path = api.repo_util.sdk_checkout_path()
  validation = api.properties.get('validation')
  if (validation
      == 'docs') and api.repo_util.is_release_candidate_branch(checkout_path):
    env['LUCI_BRANCH'] = 'stable'
    env['LUCI_CI'] = True


def UploadOrDeploy(api, env, env_prefixes, checkout_path):
  validation = api.properties.get('validation')
  git_ref = api.properties.get(
      'release_ref'
  ) or api.buildbucket.gitiles_commit.ref
  with api.context(env=env, env_prefixes=env_prefixes):
    if (validation in ('docs', 'docs_deploy') and api.properties.get('firebase_project')):
      docs_path = checkout_path.join('dev', 'docs')
      # Do not upload on docs_deploy.
      if not validation == 'docs_deploy':
        api.flutter_bcid.report_stage(BcidStage.UPLOAD.value)
        src = docs_path.join('api_docs.zip')
        commit = api.repo_util.get_commit(checkout_path)
        dst = 'gs://flutter_infra_release/flutter/%s/api_docs.zip' % commit
        api.archives.upload_artifact(src, dst)
        api.flutter_bcid.upload_provenance(src, dst)
        api.flutter_bcid.report_stage(BcidStage.UPLOAD_COMPLETE.value)
      project = api.properties.get('firebase_project')
      # Only deploy to firebase directly if this is master or main.
      if ((api.properties.get('git_branch') in ['master', 'main']) or
          (git_ref == 'refs/heads/stable')):
        sha = api.buildbucket.gitiles_commit.id
        gcs_location = 'flutter/%s/api_docs.zip' % sha
        api.flutter_bcid.download_and_verify_provenance(
            'api_docs.zip', 'flutter_infra_release', gcs_location
        )
        api.firebase.deploy_docs(
            env=env,
            env_prefixes=env_prefixes,
            docs_path=docs_path,
            project=project
        )


def RunSteps(api):
  api.flutter_bcid.report_stage(BcidStage.START.value)
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()

  checkout_path = api.path.start_dir.join('flutter')
  api.flutter_bcid.report_stage(BcidStage.FETCH.value)
  api.repo_util.checkout(
      'flutter',
      checkout_path=checkout_path,
      url=api.properties.get('git_url'),
      ref=api.properties.get('git_ref')
  )

  env, env_prefixes = api.repo_util.flutter_environment(checkout_path)
  deps = api.properties.get('dependencies', [])
  api.flutter_deps.required_deps(env, env_prefixes, deps)

  with api.context(env=env, env_prefixes=env_prefixes, cwd=checkout_path):
    api.retry.step(
        'download dependencies', ['flutter', 'update-packages', '-v'],
        max_attempts=2,
        infra_step=True
    )
    deferred = []
    deferred.append(
        api.defer(
            api.step,
            'flutter doctor',
            ['flutter', 'doctor', '-v'],
        )
    )
    deferred.append(api.defer(SetEnv, api, env, checkout_path))
    deferred.append(
        api.defer(PrepareDocs, api, env, env_prefixes, checkout_path)
    )
    deferred.append(
        api.defer(UploadOrDeploy, api, env, env_prefixes, checkout_path)
    )
    # This is to clean up leaked processes.
    deferred.append(api.defer(api.os_utils.kill_processes))
    # Collect memory/cpu/process after task execution.
    deferred.append(api.defer(api.os_utils.collect_os_info))
    api.defer.collect(deferred)


def GenTests(api):
  yield api.test(
      'docs',
      api.repo_util.flutter_environment_data(),
      api.properties(validation='docs'),
  )
  fake_bcid_response_success = '{"allowed": true, "verificationSummary": "This artifact is definitely legitimate!"}'
  yield api.test(
      'docs_upload_on_stable_branch', api.repo_util.flutter_environment_data(),
      api.properties(validation='docs', firebase_project='myproject'),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='flutter',
          git_repo='https://flutter.googlesource.com/mirrors/flutter',
          git_ref='refs/heads/stable',
          revision='abcd' * 10,
          build_number=123,
      ),
      api.step_data(
          'Verify api_docs.zip provenance.verify api_docs.zip provenance',
          stdout=api.raw_io.output_text(fake_bcid_response_success)
      )
  )
  # Test release candidate branch.
  yield api.test(
      'docs_generated_but_not_uploaded_on_release_candidate_branch',
      api.repo_util.flutter_environment_data(),
      api.properties(validation='docs', firebase_project='myproject'),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='flutter',
          git_repo='https://flutter.googlesource.com/mirrors/flutter',
          git_ref='refs/heads/flutter-3.2-candidate.5',
          revision='abcd' * 10,
          build_number=123,
      ),
  )
  yield api.test(
      'docs_deploy_main',
      api.repo_util.flutter_environment_data(),
      api.properties(
          validation='docs_deploy',
          firebase_project='myproject',
          git_branch='main'
      ),
  )

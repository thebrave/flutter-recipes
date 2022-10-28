# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/flutter_deps',
    'recipe_engine/context',
    'recipe_engine/futures',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/step',
]

def RunSteps(api):
  if not api.platform.is_mac:
    pass

  # Installing dependencies for code sign.
  env = {}
  env_prefixes = {}
  with api.step.nest('Dependencies'):
    codesign_deps = api.properties.get('dependencies')
    api.flutter_deps.required_deps(env, env_prefixes, codesign_deps)

  # The list is iterated running one signer tool command per file. This can be
  # optimized using the multiprocessing API.
  final_list = api.properties.get('signing_file_list', [])
  signer_builds = []
  for gcsPath in final_list:
    signer_builds.append(
        api.futures.spawn(RunSignerToolCommand, api, env, env_prefixes, gcsPath, gcsPath)
    )
  futures = api.futures.wait(signer_builds)
  for future in futures:
    future.result()


def RunSignerToolCommand(api, env, env_prefixes, gcsDownloadPath, gcsUploadPath):
  with api.context(env=env, env_prefixes=env_prefixes):
    api.step(
        'codesign Apple engine binaries',
        [
          'codesign',
          '--gcs-download-path',
          gcsDownloadPath,
          '--gcs-upload-path',
          gcsUploadPath,
        ],
    )


def GenTests(api):

  yield api.test(
      'config_from_file',
      api.properties(
          dependencies=[{
              'dependency': 'codesign',
              'version': 'latest',
          }],
          signing_file_list = ["gs://a/b/c/artifact.zip"]
      )
  )


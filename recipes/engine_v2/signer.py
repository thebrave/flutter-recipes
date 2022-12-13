# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Recipe that executes apple code signing on a code signing bot. A code
# signing bot is a machine with flutter certificates and signing related
# set ups.
#
# This recipe receives as properties the list of google cloud bucket paths
# of engine artifacts, and reads code sign related passwords from
# kms securely. The engine artifact bucket paths and codesign credentials
# are then supplied to a codesign standalone app, which communicates with
# Apple notary server to finish code signing. The codesign standalone app
# is run as a cipd package, and the codesigned artifacts are uploaded back
# to the same google cloud bucket path.

DEPS = [
    'depot_tools/gsutil',
    'flutter/archives',
    'flutter/flutter_deps',
    'recipe_engine/context',
    'recipe_engine/futures',
    'flutter/kms',
    'flutter/osx_sdk',
    'recipe_engine/file',
    'recipe_engine/path',
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
    codesign_path = api.flutter_deps.codesign(env, env_prefixes)

  # The list is iterated running one signer tool command per file. This can be
  # optimized using the multiprocessing API.
  final_sources_list = api.properties.get('signing_file_list', [])
  signer_builds = []
  codesign_dir = api.path.mkdtemp()
  app_specific_password_filepath = codesign_dir.join(
      'codesign_app_specific_password.encrypted'
  )
  appstore_id_filepath = codesign_dir.join('codesign_app_store_id.encrypted')
  team_id_filepath = codesign_dir.join('codesign_team_id.encrypted')
  api.kms.get_secret('codesign_team_id.encrypted', team_id_filepath)
  api.kms.get_secret(
      'codesign_app_specific_password.encrypted', app_specific_password_filepath
  )
  api.kms.get_secret('codesign_app_store_id.encrypted', appstore_id_filepath)

  # unlock keychain
  with api.context(env=env, env_prefixes=env_prefixes):
    resource_name = api.resource('runner.sh')
    api.step('Set execute permission', ['chmod', '755', resource_name])
    cmd = ['bash', resource_name]
    api.step('unlock keychain', cmd)

  # keep track of the output zip files in separate temp folders to avoid name conflicts
  output_zips = {}

  codesign_string_path = "%s" % codesign_path
  with api.osx_sdk('ios'):
    for source_path in final_sources_list:
      input_tmp_folder = api.path.mkdtemp()
      _, artifact_base_name = api.path.split(source_path) 
      local_zip_path = input_tmp_folder.join('unsigned_%s' % artifact_base_name)
      local_zip_string_path = str(local_zip_path)

      output_zip_path = input_tmp_folder.join(artifact_base_name)
      output_zip_string_path = str(output_zip_path)
      output_zips[source_path] = output_zip_string_path
      api.archives.download(source_path, local_zip_path)
      signer_builds.append(
          api.futures.spawn(
              RunSignerToolCommand, api, env, env_prefixes,
              local_zip_string_path, output_zip_string_path,
              app_specific_password_filepath, appstore_id_filepath,
              team_id_filepath, codesign_string_path
          )
      )

    futures = api.futures.wait(signer_builds)
    for future in futures:
      future.result()

  for source_path, output_zip_path in output_zips.items():
    api.archives.upload_artifact(src=output_zip_path, dst=source_path)

def RunSignerToolCommand(
    api, env, env_prefixes, input_zip_string_path, output_zip_string_path,
    app_specific_password_filepath, appstore_id_filepath, team_id_filepath,
    codesign_string_path
):
  """Runs code sign standalone app.

  Args:
      input_zip_string_path (str): path of the unsigned artifact in the file system.
      output_zip_string_path (str): path of the signed artifact in the file system.
      app_specific_password_filepath (str) : path of app specific password, one of
      the code sign credentials.
      appstore_id_filepath (str) : path of apple store id, one of the codesign
      credentials.
      team_id_filepath (str) : path of flutter team id used for codesign, one of the
      codesign credentials.
      codesign_string_path (str): the absolute path of the codesign standalone app
      cipd package. This is to differentiate codesign cipd from mac system codesign.
  """
  flutter_certificate_name = 'FLUTTER.IO LLC'
  with api.context(env=env, env_prefixes=env_prefixes):
    api.step(
        'codesign Apple engine binaries',
        [
            codesign_string_path,
            '--codesign-cert-name',
            flutter_certificate_name,
            '--no-dryrun',
            '--app-specific-password-file-path',
            app_specific_password_filepath,
            '--codesign-appstore-id-file-path',
            appstore_id_filepath,
            '--codesign-team-id-file-path',
            team_id_filepath,
            '--input-zip-file-path',
            input_zip_string_path,
            '--output-zip-file-path',
            output_zip_string_path,
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
          signing_file_list=["gs://a/b/c/artifact.zip"]
      )
  )

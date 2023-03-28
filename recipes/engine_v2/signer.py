# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Recipe that executes apple code signing on a mac bot.
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
    'recipe_engine/raw_io',
    'recipe_engine/step',
]


def RunSteps(api):
  if not api.platform.is_mac:
    pass

  # Install dependencies for code sign.
  env = {}
  env_prefixes = {}
  with api.step.nest('Dependencies'):
    codesign_path = api.flutter_deps.codesign(env, env_prefixes)

  secrets_dict = {
      'FLUTTER_P12': 'flutter_p12.encrypted',
      'FLUTTER_P12_PASSWORD': 'p12_password.encrypted',
      'CODESIGN_TEAM_ID': 'codesign_team_id.encrypted',
      'CODESIGN_APP_SPECIFIC_PASSWORD':
        'codesign_app_specific_password.encrypted',
      'CODESIGN_APP_STORE_ID': 'codesign_app_store_id.encrypted'
  }

  api.kms.decrypt_secrets(env, secrets_dict)

  env['CODESIGN_PATH'] = codesign_path

  try:
    KeychainSetup(api, env, env_prefixes)

    SignerBuilds(
        api, codesign_path, env, env_prefixes
    )

  finally:
    KeychainCleanup(api)


def KeychainSetup(api, env, env_prefixes):
  """KeychainSetup adds flutter .p12 to a temporary keychain named 'build'.

  Args:
      codesign_path (str): path of codesign cipd package.
      p12_filepath (str) : path of the .p12 file that has flutter credentials.
      p12_password_raw (str) : the password to decode the .p12 flutter file.
  """
  api.step(
      'delete previous keychain',
      ['security', 'delete-keychain', 'build.keychain'],
      ok_ret='any'
  )
  api.step(
      'create keychain',
      ['security', 'create-keychain', '-p', '', 'build.keychain']
  )
  api.step(
      'default keychain',
      ['security', 'default-keychain', '-s', 'build.keychain']
  )
  api.step(
      'unlock build keychain',
      ['security', 'unlock-keychain', '-p', '', 'build.keychain']
  )
  ImportCertificate(api, env, env_prefixes)
  api.step(
      'set key partition list', [
          'security', 'set-key-partition-list', '-S',
          'apple-tool:,apple:,codesign:', '-s', '-k', '', 'build.keychain'
      ]
  )
  show_identities_step = api.step(
      'show-identities', ['security', 'find-identity', '-v'],
      ok_ret='any',
      stdout=api.raw_io.output_text(),
      stderr=api.raw_io.output_text()
  )
  flutter_identity_name = 'FLUTTER.IO LLC'
  if flutter_identity_name not in show_identities_step.stdout:
    raise ValueError(
        'identities are %s, does not include flutter identity' %
        (show_identities_step.stdout)
    )


def ImportCertificate(api, env, env_prefixes):
  """Import flutter codesign identity into keychain.

  This function triggers a shell script that supplies p12 password,
  and grants codesign cipd and system codesign the correct access controls.
  The p12 password is hidden from stdout.

  Args:
      env (dict): environment variables.
      env_prefixes (dict) : environment paths.
  """
  resource_name = api.resource('import_certificate.sh')
  api.step(
      'Set execute permission',
      ['chmod', '755', resource_name],
      infra_step=True,
  )
  # Only filepath with a .p12 suffix will be recognized.
  p12_suffix_filepath = api.path['cleanup'].join('flutter.p12')
  env['P12_SUFFIX_FILEPATH'] = p12_suffix_filepath
  with api.context(env=env, env_prefixes=env_prefixes):
    api.step('import certificate', [resource_name])


def SignerBuilds(
    api, codesign_path, env, env_prefixes
):
  """Concurrently creates jobs to codesign each binary.

  Args:
      codesign_path (str): path of codesign cipd package.
      env (dict): environment variables.
      env_prefixes (dict) : environment paths.
  """
  # The list is iterated running one signer tool command per file. This can be
  # optimized using the multiprocessing API.
  final_sources_list = api.properties.get('signing_file_list', [])

  # keep track of the output zip files in separate temp folders to avoid name
  # conflicts
  output_zips = {}

  codesign_string_path = "%s" % codesign_path
  app_specific_password_filepath = env['CODESIGN_APP_SPECIFIC_PASSWORD']
  appstore_id_filepath = env['CODESIGN_APP_STORE_ID']
  team_id_filepath = env['CODESIGN_TEAM_ID']
  signer_builds = []
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
  api.step(
      'unlock build keychain',
      ['security', 'unlock-keychain', '-p', '', 'build.keychain']
  )
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


def KeychainCleanup(api):
  """Clean up temporary keychain used in codesign process."""
  api.step('delete keychain', ['security', 'delete-keychain', 'build.keychain'])
  api.step(
      'restore default keychain',
      ['security', 'default-keychain', '-s', 'login.keychain']
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
      ),
      api.step_data(
          'show-identities',
          stdout=api.raw_io.output_text(
              '1) ABCD "Developer ID Application: FLUTTER.IO LLC (ABCD)"'
          )
      ),
  )

  yield api.test(
      'import_flutter_identity_failure',
      api.properties(
          dependencies=[{
              'dependency': 'codesign',
              'version': 'latest',
          }],
          signing_file_list=["gs://a/b/c/artifact.zip"]
      ),
      api.expect_exception('ValueError'),
  )

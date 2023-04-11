# Copyright 2023 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

#import zipfile
from recipe_engine import recipe_api


# File name inside artifacts that require signing with entitlements.
ENTITLEMENTS_FILENAME = 'entitlements.txt'
# File name inside artifacts that require signing without entitlements.
WITHOUT_ENTITLEMENTS_FILENAME = 'without_entitlements.txt'


class CodeSignApi(recipe_api.RecipeApi):
  """Provides utilities to code sign binaries in mac."""

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._initialized = False
    self._codesign_binary_path = None


  def requires_signing(self, artifact_path):
    """Validates if a file needs to be codesigned.

    Args:
      artifact_path: (str) the path to the zip file artifact
        to validate if code signing is required.

    Returns:
      True if code sign is required, False if it is not.
    """
    if not self.m.platform.is_mac:
      return False
    file_list = self.m.zip.namelist('namelist', artifact_path)
    return (
        ENTITLEMENTS_FILENAME in file_list or
        WITHOUT_ENTITLEMENTS_FILENAME in file_list)

  @property
  def codesign_binary(self):
    """Property pointing to the signing tool location."""
    self._ensure()
    return self._codesign_binary_path

  def _start(self, env, env_prefixes):
    self._ensure()
    self._codesign_environment(env, env_prefixes)
    self._keychain_setup(env, env_prefixes)


  def _stop(self):
    self._keychain_cleanup()


  def _ensure(self):
    if not self._codesign_binary_path:
      with self.m.step.nest('Codesign Dependencies'):
        self._codesign_binary_path = self.m.flutter_deps.codesign({},{})

  def code_sign(self, files_to_sign):
    if not self.m.platform.is_mac:
      return
    env = {}
    env_prefixes = {}
    self._start(env, env_prefixes)
    try:
      self._signer_tasks(env, env_prefixes, files_to_sign)
    finally:
      if not self.m.runtime.in_global_shutdown:
        self._stop()


  def _codesign_environment(self, env, env_prefixes):
    with self.m.step.nest('Setup codesign environment'):
      secrets_dict = {
          'FLUTTER_P12': 'flutter_p12.encrypted',
          'FLUTTER_P12_PASSWORD': 'p12_password.encrypted',
          'CODESIGN_TEAM_ID': 'codesign_team_id.encrypted',
          'CODESIGN_APP_SPECIFIC_PASSWORD':
              'codesign_app_specific_password.encrypted',
          'CODESIGN_APP_STORE_ID': 'codesign_app_store_id.encrypted'
      }
      self.m.kms.decrypt_secrets(env, secrets_dict)
      env['CODESIGN_PATH'] = self.codesign_binary



  def _keychain_setup(self, env, env_prefixes):
    """KeychainSetup adds flutter .p12 to a temporary keychain named 'build'.

    Args:
      env (dict): environment variables.
      env_prefixes (dict) : environment paths.
    """
    with self.m.step.nest('Setup keychain'):
      # Delete build.keychain if exists.
      self.m.step(
          'delete previous keychain',
          ['security', 'delete-keychain', 'build.keychain'],
          ok_ret='any'
      )
      # Create build.keychain.
      self.m.step(
          'create keychain',
          ['security', 'create-keychain', '-p', '', 'build.keychain']
      )
      # Set build.keychain as default.
      self.m.step(
          'default keychain',
          ['security', 'default-keychain', '-s', 'build.keychain']
      )
      # Unlock build.keychain to allow sign commands to use its secrets.
      self.m.step(
          'unlock build keychain',
          ['security', 'unlock-keychain', '-p', '', 'build.keychain']
      )
      # Import flutter's certificate to the keychain.
      self._import_certificate(env, env_prefixes)
      # Sets a partition list to identify the app signatures allowed to use the key.
      self.m.step(
          'set key partition list', [
              'security', 'set-key-partition-list', '-S',
              'apple-tool:,apple:,codesign:', '-s', '-k', '', 'build.keychain'
          ]
      )
      # Grabs existing identities to find out if we are ready to sign with flutter's
      # identity.
      show_identities_step = self.m.step(
          'show-identities', ['security', 'find-identity', '-v'],
          ok_ret='any',
          stdout=self.m.raw_io.output_text(),
          stderr=self.m.raw_io.output_text()
      )
      flutter_identity_name = 'FLUTTER.IO LLC'
      if flutter_identity_name not in show_identities_step.stdout:
        raise ValueError(
           'identities are %s, does not include flutter identity' %
           (show_identities_step.stdout)
        )

  def _import_certificate(self, env, env_prefixes):
    """Import flutter codesign identity into keychain.

    This function triggers a shell script that supplies p12 password,
    and grants codesign cipd and system codesign the correct access controls.
    The p12 password is hidden from stdout.

    Args:
      env (dict): environment variables.
      env_prefixes (dict) : environment paths.
    """
    resource_name = self.resource('import_certificate.sh')
    self.m.step(
        'Set execute permission',
        ['chmod', '755', resource_name],
        infra_step=True,
    )
    # Only filepath with a .p12 suffix will be recognized.
    p12_suffix_filepath = self.m.path['cleanup'].join('flutter.p12')
    env['P12_SUFFIX_FILEPATH'] = p12_suffix_filepath
    with self.m.context(env=env, env_prefixes=env_prefixes):
      self.m.step('import certificate', [resource_name])


  def _signer_tasks(self, env, env_prefixes, files_to_sign):
    """Concurrently creates jobs to codesign each binary.

    Args:
      env (dict): environment variables.
      env_prefixes (dict) : environment paths.
    """
    signer_builds = []
    for source_path in files_to_sign:
      signer_builds.append(
        self.m.futures.spawn(
            self._run_signer_tool_command,
            env,
            env_prefixes,
            source_path,
        )
      )

    futures = self.m.futures.wait(signer_builds)
    for future in futures:
      future.result()

  def _run_signer_tool_command(
      self,
      env,
      env_prefixes,
      source_path,
  ):
    """Runs code sign standalone app.

    Args:
      env (dict): environment variables.
      env_prefixes (dict) : environment paths.
      source_path (Path): path of the artifact to sign.
    """
    app_specific_password_filepath = env['CODESIGN_APP_SPECIFIC_PASSWORD']
    appstore_id_filepath = env['CODESIGN_APP_STORE_ID']
    team_id_filepath = env['CODESIGN_TEAM_ID']
    path, base_name = self.m.path.split(source_path)
    unsigned_path = self.m.path.join(path, 'unsigned_%s' % base_name)
    self.m.file.move(
        'Move %s' % str(source_path),
        source_path,
        unsigned_path
    )
    with self.m.step.nest('Codesign %s' % str(unsigned_path)):
      flutter_certificate_name = 'FLUTTER.IO LLC'
      self.m.step(
          'unlock build keychain',
          ['security', 'unlock-keychain', '-p', '', 'build.keychain']
      )
      with self.m.context(env=env, env_prefixes=env_prefixes):
        self.m.step(
            'codesign Apple engine binaries',
            [
                self.codesign_binary,
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
                str(unsigned_path),
                '--output-zip-file-path',
                str(source_path),
            ],
        )

  def _keychain_cleanup(self):
    """Clean up temporary keychain used in codesign process."""
    with self.m.step.nest('Keychain cleanup'):
      self.m.step('delete keychain', ['security', 'delete-keychain', 'build.keychain'])
      self.m.step(
         'Cleanup keychain.restore default keychain',
         ['security', 'default-keychain', '-s', 'login.keychain']
      )


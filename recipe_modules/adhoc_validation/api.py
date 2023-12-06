# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class AddhocValidationApi(recipe_api.RecipeApi):
  """Wrapper api to run bash scripts as validation in LUCI builder steps.

  This api expects all the bash or bat scripts to exist in its resources
  directory and also expects the validation name to be listed in
  available_validations method.
  """

  def available_validations(self):
    """Returns the list of accepted validations."""
    return ['verify_binaries_codesigned']

  def run(self, name, validation, env, env_prefixes, secrets=None):
    """Runs a validation as a recipe step.

    Args:
      name(str): The step group name.
      validation(str): The name of a validation to run. This has to correlate
        to a <validation>.sh for linux/mac or <validation>.bat for windows.
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      secrets(dict): The key is the name of the secret and value is the path to kms.
    """
    if validation not in self.available_validations():
      msg = str(validation) + ' is not listed in available_validations.'
      raise AssertionError(msg)
    secrets = secrets or {}
    with self.m.step.nest(name):
      resource_name = ''
      self.m.kms.decrypt_secrets(env, secrets)
      resource_name = self.resource('%s.sh' % validation)
      self.m.step(
          'Set execute permission',
          ['chmod', '755', resource_name],
          infra_step=True,
      )
      if self.m.properties.get('$flutter/osx_sdk'):
        with self.m.osx_sdk('ios'):
          with self.m.context(env=env, env_prefixes=env_prefixes):
            self.m.file.read_text(
                "print script %s" % self.m.path.basename(resource_name),
                resource_name,
            )
            self.m.test_utils.run_test(
                validation,
                [resource_name],
                timeout_secs=4500  # 75 minutes
            )

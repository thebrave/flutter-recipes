# Copyright 2020 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import attr

from recipe_engine import recipe_api
from recipe_engine.config_types import Path

_SSH_CONFIG_TEMPLATE = """
Host *
  CheckHostIP no
  StrictHostKeyChecking no
  ForwardAgent no
  ForwardX11 no
  UserKnownHostsFile /dev/null
  User fuchsia
  IdentitiesOnly yes
  IdentityFile {identity}
  ServerAliveInterval 2
  ServerAliveCountMax 5
  ControlMaster auto
  ControlPersist 1m
  ControlPath /tmp/ssh-%r@%h:%p
  ConnectTimeout 5
"""


@attr.s
class SSHFilePaths(object):
  """Required files to setup SSH on FEMU."""

  # Recipe API, required
  _api = attr.ib(type=recipe_api.RecipeApi)

  # Files for SSH
  host_private = attr.ib(type=Path, default=None)
  host_public = attr.ib(type=Path, default=None)

  id_private = attr.ib(type=Path, default=None)
  id_public = attr.ib(type=Path, default=None)

  def _exists(self, p):
    return p and self._api.path.exists(p)

  def _exist(self):
    return all([
        self._exists(self.host_private),
        self._exists(self.host_public),
        self._exists(self.id_private),
        self._exists(self.id_public),
    ])

  def _report_missing(self):
    result = []
    if not self._exists(self.host_private):
      result.append(self.host_private)
    if not self._exists(self.host_public):
      result.append(self.host_public)
    if not self._exists(self.id_private):
      result.append(self.id_private)
    if not self._exists(self.id_public):
      result.append(self.id_public)
    return result


class SSHApi(recipe_api.RecipeApi):

  def __init__(self, *args, **kwargs):
    super(SSHApi, self).__init__(*args, **kwargs)
    self._ssh_paths = None

  def _create_ssh_keys(self, timeout_secs=10 * 60):
    """Generate private, public key-pairs for Host side and Device side ssh keys."""
    self.m.file.ensure_directory('init ssh cache', self.ssh_cache_root)
    if not self._ssh_paths:
      self._ssh_paths = SSHFilePaths(
          api=self.m,
          host_private=self.ssh_cache_root / 'ssh_host_key',
          host_public=self.ssh_cache_root / 'ssh_host_key.pub',
          id_private=self.ssh_cache_root / 'id_ed25519',
          id_public=self.ssh_cache_root / 'id_ed25519.pub',
      )

    if not self.m.file.listdir(name='check ssh cache content',
                               source=self.ssh_cache_root, test_data=()):
      self.m.step(
          'ssh-keygen host',
          [
              'ssh-keygen',
              '-t',
              'ed25519',
              '-h',
              '-f',
              self._ssh_paths.host_private,
              '-P',
              '',
              '-N',
              '',
          ],
          infra_step=True,
          timeout=timeout_secs,
      )
      self.m.step(
          'ssh-keygen device',
          [
              'ssh-keygen',
              '-t',
              'ed25519',
              '-f',
              self._ssh_paths.id_private,
              '-P',
              '',
              '-N',
              '',
          ],
          infra_step=True,
          timeout=timeout_secs,
      )
    return self._ssh_paths

  def generate_ssh_config(self, private_key_path, dest):
    """Generates and sets the private_key_path in ssh_config file."""
    self.m.file.write_text(
        name='generate ssh_config at %s' % dest,
        dest=dest,
        text_data=_SSH_CONFIG_TEMPLATE.format(identity=private_key_path),
    )

  @property
  def ssh_paths(self):
    """Generate SSH keys.

    Raises:
      StepFailure: When ssh key file paths do not exist.
    """
    self._create_ssh_keys()
    if not self._ssh_paths._exist():
      missing = self._ssh_paths._report_missing()
      ex = self.m.step.StepFailure(
          'SSH paths do not exist. {missing_paths}'.format(
              missing_paths=missing
          )
      )
      ex.missing_paths = missing
      raise ex
    return self._ssh_paths

  @property
  def ssh_cache_root(self):
    return self.m.buildbucket.builder_cache_path / 'ssh'

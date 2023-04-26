# Copyright 2020 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/ssh',
    'recipe_engine/path',
]


def RunSteps(api):
  ssh_paths = api.ssh.ssh_paths
  api.ssh.generate_ssh_config(
      private_key_path=ssh_paths.id_private, dest=api.path['cache']
  )


def GenTests(api):
  yield api.test(
      'ssh_paths',
      api.path.exists(
          api.path['cache'].join('builder/ssh/id_ed25519.pub'),
          api.path['cache'].join('builder/ssh/id_ed25519'),
          api.path['cache'].join('builder/ssh/ssh_host_key.pub'),
          api.path['cache'].join('builder/ssh/ssh_host_key'),
      )
   )

  yield api.test('ssh_paths_missing', status='FAILURE')

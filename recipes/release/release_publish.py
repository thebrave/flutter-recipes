# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re
from recipe_engine import post_process

DEPS = [
    'flutter/flutter_deps',
    'flutter/kms',
    'flutter/repo_util',
    'fuchsia/git',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/runtime',
    'recipe_engine/step',
]

stableTagRegex = r'^(\d+)\.(\d+)\.(\d+)$'
betaTagRegex = r'^(\d+)\.(\d+)\.(\d+)-(\d+)\.(\d+)\.pre$'

def isValidTag(tag):
  stable = re.search(stableTagRegex, tag)
  development = re.search(betaTagRegex, tag)
  return stable or development

"""
This recipe executes the tag and publishing stages of a flutter release.
To trigger this recipe, tool proxy must be invoked with multi-party approval.
Tool proxy information can be found at go/tool-proxy.
Because of this configuration, the recipe is triggered manually during the
release process.

It is expected that a valid release git branch, tag, and release_channel are passed
to the recipe.

The recipe will tag and push to github unless triggered
from an experimental run.
"""
def RunSteps(api):
  git_branch = api.properties.get('git_branch')
  tag = api.properties.get('tag')
  release_channel = api.properties.get('release_channel')
  # default to True dry run
  dry_run = api.runtime.is_experimental or api.properties.get('dry_run')=='True'
  assert git_branch and tag and release_channel

  checkout_path = api.path['start_dir'].join('flutter')
  git_url = 'https://github.com/flutter/flutter'

  # Validate the given tag is correctly formatted for either stable or latest
  assert isValidTag(tag)

  # This recipe should only be executed on linux or mac machines to
  # guard against Windows git issues
  assert api.platform.is_linux or api.platform.is_mac

  with api.step.nest('checkout release branch'):
    release_git_hash = api.repo_util.checkout(
        'flutter',
        checkout_path=checkout_path,
        url=git_url,
        ref="refs/heads/%s" % git_branch,
    )

  env, env_prefixes = api.repo_util.flutter_environment(checkout_path)
  api.flutter_deps.required_deps(
      env,
      env_prefixes,
      api.properties.get('dependencies', []),
  )

  # install gh cli
  api.flutter_deps.gh_cli(env, env_prefixes, 'latest')

  with api.context(env=env, env_prefixes=env_prefixes, cwd=checkout_path):
    token_decrypted = api.path['cleanup'].join('token.txt')
    api.kms.get_secret('flutter-release-github-token.encrypted', token_decrypted)

    token_txt = api.file.read_text('Read token', token_decrypted, include_log=False)
    api.step(
        'authenticating using gh cli',
        ['gh', 'auth', 'login', '--hostname', 'github.com', '--git-protocol',
         'https','--with-token'],
        stdin=api.raw_io.input_text(data=token_txt))

    # configure gh to allow next authenticated git actions
    api.step(
      'configure gh for git auth',
      ['gh', 'auth', 'setup-git'])

    tag_command = ['tag', tag, release_git_hash]
    if dry_run:
      tag_command.insert(0, 'echo')
      api.step('Dry-run tag release command', tag_command)
    else:
      api.git('tag release', *tag_command)

    # output tag for debug clarity & testing
    api.git('find commit',
      'rev-list',
      '-n',
      '1',
      f'origin/{git_branch}',
      stdout=api.raw_io.output_text(add_output_log=True)).stdout.rstrip()

    # push tag
    push_tag_args = ['push', 'origin', tag]
    if dry_run:
      push_tag_args.insert(0, 'echo')
      api.step('Dry-run push tag command', push_tag_args)
    else:
      api.git('push tag', *push_tag_args)

    # push refs to release channel
    push_ref_args = ['push', 'origin', 'HEAD:%s' % release_channel]
    if dry_run:
      push_ref_args.insert(0, 'echo')
      api.step('Dry-run push ref command', push_ref_args)
    else:
      push_ref_msg = 'push refs to release branch %s' % release_channel
      api.git(push_ref_msg, *push_ref_args)


def GenTests(api):
    for tag in ('1.2.3-4.5.pre', '1.2.3'):
      for release_channel in ('stable', 'beta'):
        for dry_run in ('True', 'False'):
          test = api.test(
              '%s_%s_%s%s' % (
                  'flutter-2.8-candidate.9',
                  tag,
                  release_channel,
                  '_dry_run' if dry_run=='True' else ''
              ), api.platform('mac', 64),
              api.properties(
                  git_branch='flutter-2.8-candidate.9',
                  tag=tag,
                  release_channel=release_channel,
                  dry_run=dry_run
              ), api.repo_util.flutter_environment_data(),
                    api.step_data('find commit', stdout=api.raw_io.output_text(
                '82735b8904e82fd8b273cb1ae16cccd77ccf4248\n')),
              api.post_process(post_process.MustRun,
                'authenticating using gh cli'),
              api.post_process(post_process.MustRunRE, r'.*tag release.*'),
              api.post_process(post_process.MustRunRE, r'.*push tag.*'),
              api.post_process(post_process.StatusSuccess),
          )
          yield test

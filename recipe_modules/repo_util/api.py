# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

REPOS = {
    'cocoon': 'https://flutter.googlesource.com/mirrors/cocoon',
    'engine': 'https://flutter.googlesource.com/mirrors/engine',
    'flutter': 'https://flutter.googlesource.com/mirrors/flutter',
    'infra': 'https://flutter.googlesource.com/infra',
    'mirrors/engine': 'https://flutter.googlesource.com/mirrors/engine',
    'mirrors/flutter': 'https://flutter.googlesource.com/mirrors/flutter',
    'monorepo': 'https://dart.googlesource.com/monorepo',
    'openpay': 'https://dash-internal.googlesource.com/openpay',
    'packages': 'https://flutter.googlesource.com/mirrors/packages',
}

# TODO(keyonghan): deprecate when all repos are migrated to main.
REPO_BRANCHES = {
    'cocoon': 'main',
    'engine': 'main',
    'flutter': 'master',
    'infra': 'main',
    'mirrors/engine': 'main',
    'mirrors/flutter': 'main',
    'monorepo': 'main',
    'openpay': 'main',
    'packages': 'main',
}

import copy
import re
from recipe_engine import recipe_api

# Buildbucket bucket for official builds.
OFFICIAL_BUILD_BUCKET = 'flutter'


class RepoUtilApi(recipe_api.RecipeApi):
  """Provides utilities to work with flutter repos."""

  def _setup_win_toolchain(self, env):
    """Setups local win toolchain if available."""
    if self.m.platform.is_win:
      toolchain_metadata_src = self.m.path['cache'].join(
          'builder', 'vs_toolchain_root', 'data.json'
      )
      self.m.path.mock_add_paths(toolchain_metadata_src)
      if self.m.path.exists(toolchain_metadata_src):
        toolchain_metadata_dst = self.m.path['cache'].join(
            'builder', 'src', 'build', 'win_toolchain.json'
        )
        self.m.file.copy(
            'copy win_toolchain_metadata', toolchain_metadata_src,
            toolchain_metadata_dst
        )
        data_file = self.m.path['cache'].join(
            'builder', 'vs_toolchain_root', 'data.json'
        )
        metadata = self.m.file.read_json(
            'read win toolchain metadata',
            data_file,
            test_data={'version': '2022'}
        )
        env['GYP_MSVS_VERSION'] = metadata['version']

  def engine_checkout(self, checkout_path, env, env_prefixes):
    """Checkout code using gclient.

    Args:
      checkout_path(Path): The path to checkout source code and dependencies.
      env(dict): A dictionary with the environment variables to set.
      env_prefixes(dict): A dictionary with the paths to be added to environment variables.
    """
    # Set vs_toolchain env to cache it.
    if self.m.platform.is_win:
      # Set win toolchain root to a directory inside cache/builder to cache it.
      env['DEPOT_TOOLS_WIN_TOOLCHAIN_ROOT'] = self.m.path['cache'].join(
          'builder', 'vs_toolchain_root'
      )
      env['DEPOT_TOOLS_WIN_TOOLCHAIN'] = 1

    bucket = self.m.buildbucket.build.builder.bucket
    # Calculate if we need to clean the source code cache.
    clobber = self.m.properties.get('clobber', False)

    # Calculate if we need to mount the cache and mount it if required.
    mount_git = self.m.cache.should_force_mount(
        self.m.path['cache'].join('git')
    )
    mount_builder = self.m.cache.should_force_mount(
        self.m.path['cache'].join('builder')
    )
    if (not clobber) and (mount_git or
                          mount_builder) and (bucket != OFFICIAL_BUILD_BUCKET):
      self.m.cache.mount_cache('builder', force=True)
    self._setup_win_toolchain(env)
    # Grab any gclient custom variables passed as properties.
    local_custom_vars = self.m.shard_util_v2.unfreeze_dict(
        self.m.properties.get('gclient_variables', {})
    )
    # Pass a special gclient variable to identify release candidate branch checkouts. This
    # is required to prevent trying to download experimental dependencies on release candidate
    # branches.
    branch = self.m.properties.get('git_branch',
                                   '') or self.get_branch(checkout_path)
    if branch.startswith('flutter-') or branch in [
        'beta', 'stable'
    ] or bucket == OFFICIAL_BUILD_BUCKET:
      local_custom_vars['release_candidate'] = True
    git_url = REPOS['engine']
    git_id = self.m.buildbucket.gitiles_commit.id
    git_ref = self.m.buildbucket.gitiles_commit.ref
    if 'git_url' in self.m.properties and 'git_ref' in self.m.properties:
      git_url = self.m.properties['git_url']
      git_id = self.m.properties['git_ref']
      git_ref = self.m.properties['git_ref']
    # Inner function to clobber the cache
    def _ClobberCache():
      # Ensure depot tools is in the path to prevent problems with vpython not
      # being found after a failure.
      with self.m.depot_tools.on_path():
        if self.m.path.exists(checkout_path):
          self.m.file.rmcontents('Clobber cache', checkout_path)
        git_cache_path = self.m.path['cache'].join('git')
        self.m.path.mock_add_directory(git_cache_path)
        if self.m.path.exists(git_cache_path):
          self.m.file.rmtree('Clobber git cache', git_cache_path)
        self.m.file.ensure_directory('Ensure checkout cache', checkout_path)

    # Inner function to execute code a second time in case of failure.
    def _InnerCheckout():
      with self.m.step.nest('Checkout source code'):
        if clobber:
          _ClobberCache()
        with self.m.context(env=env, env_prefixes=env_prefixes,
                            cwd=checkout_path), self.m.depot_tools.on_path():
          try:
            src_cfg = self.m.gclient.make_config()
            soln = src_cfg.solutions.add()
            soln.name = 'src/flutter'
            soln.url = git_url
            soln.revision = git_id
            soln.managed = False
            soln.custom_vars = local_custom_vars
            src_cfg.parent_got_revision_mapping['parent_got_revision'
                                               ] = 'got_revision'
            src_cfg.repo_path_map[git_url] = (
                'src/flutter', git_ref or
                'refs/heads/%s' % REPO_BRANCHES['engine']
            )
            self.m.gclient.c = src_cfg
            self.m.gclient.c.got_revision_mapping['src/flutter'
                                                 ] = 'got_engine_revision'
            # Timeout the checkout at 15 mins to fail fast in slow checkouts so we can
            # retry.
            TIMEOUT_SECS = 15 * 60  # 15 mins.
            step_result = self.m.bot_update.ensure_checkout(
                timeout=TIMEOUT_SECS
            )
            if ('got_revision' in step_result.presentation.properties and
                step_result.presentation.properties['got_revision']
                == 'BOT_UPDATE_NO_REV_FOUND'):
              raise self.m.step.StepFailure('BOT_UPDATE_NO_REV_FOUND')
            self.m.gclient.runhooks()
            # if win copy toolchain metadata to the expected location.
            self._setup_win_toolchain(env)
          except:
            # On any exception, clean up the cache and raise
            _ClobberCache()
            raise

    # Some outlier GoB mirror jobs can take >250secs.
    self.m.retry.basic_wrap(
        _InnerCheckout,
        step_name='Checkout source',
        sleep=2.0,
        backoff_factor=5,
        max_attempts=2
    )

  def monorepo_checkout(self, checkout_path, env, env_prefixes):
    """Checkout code using gclient.

    Args:
      checkout_path(Path): The path to checkout source code and dependencies.
      env(dict): A dictionary with the environment variables to set.
      env_prefixes(dict): A dictionary with the paths to be added to environment variables.
      clobber(bool): A boolean indicating whether the checkout folder should be cleaned.
      custom_vars(dict): A dictionary with custom variable definitions for gclient solution.
    """
    # Calculate if we need to clean the source code cache.
    clobber = self.m.properties.get('clobber', False)

    # Pass a special gclient variable to identify release candidate branch checkouts. This
    # is required to prevent trying to download experimental dependencies on release candidate
    # branches.
    local_custom_vars = self.m.shard_util_v2.unfreeze_dict(
        self.m.properties.get('gclient_variables', {})
    )
    if (self.m.properties.get('git_branch', '').startswith('flutter-') or
        self.m.properties.get('git_branch', '') in ['beta', 'stable']):
      local_custom_vars['release_candidate'] = True
    git_url = REPOS['monorepo']
    commit = self.m.buildbucket.gitiles_commit
    # Commit will have empty fields if this is a try build.
    git_id = commit.id or 'refs/heads/main'
    git_ref = commit.ref or 'refs/heads/main'
    if commit.project and (commit.host != 'dart.googlesource.com' or
                           commit.project != 'monorepo'):
      raise ValueError(
          'Input reference is not on dart.googlesource.com/monorepo'
      )
    # Inner function to clobber the cache
    def _ClobberCache():
      # Ensure depot tools is in the path to prevent problems with vpython not
      # being found after a failure.
      with self.m.depot_tools.on_path():
        if self.m.path.exists(checkout_path):
          self.m.file.rmcontents('Clobber cache', checkout_path)
        git_cache_path = self.m.path['cache'].join('git')
        self.m.path.mock_add_directory(git_cache_path)
        if self.m.path.exists(git_cache_path):
          self.m.file.rmtree('Clobber git cache', git_cache_path)
        self.m.file.ensure_directory('Ensure checkout cache', checkout_path)

    # Inner function to execute code a second time in case of failure.
    def _InnerCheckout():
      with self.m.step.nest('Checkout source code'):
        if clobber:
          _ClobberCache()
        with self.m.context(env=env, env_prefixes=env_prefixes,
                            cwd=checkout_path), self.m.depot_tools.on_path():
          try:
            src_cfg = self.m.gclient.make_config()
            soln = src_cfg.solutions.add()
            soln.name = 'monorepo'
            soln.url = git_url
            soln.revision = git_id
            soln.managed = False
            soln.custom_vars = local_custom_vars
            #src_cfg.parent_got_revision_mapping['parent_got_revision'
            #] = 'got_revision'
            src_cfg.repo_path_map[git_url] = ('monorepo', git_ref)
            self.m.gclient.c = src_cfg
            self.m.gclient.c.got_revision_mapping['monorepo'
                                                 ] = 'got_monorepo_revision'
            self.m.gclient.c.got_revision_mapping['engine/src'
                                                 ] = 'got_buildroot_revision'
            self.m.gclient.c.got_revision_mapping['engine/src/flutter'
                                                 ] = 'got_engine_revision'
            self.m.gclient.c.got_revision_mapping['engine/src/third_party/dart'
                                                 ] = 'got_dart_revision'
            self.m.gclient.c.got_revision_mapping['flutter'
                                                 ] = 'got_flutter_revision'
            self.m.bot_update.ensure_checkout()
            self.m.gclient.runhooks()
          except:
            # On any exception, clean up the cache and raise
            _ClobberCache()
            raise

    # Some outlier GoB mirror jobs can take >250secs.
    self.m.retry.basic_wrap(
        _InnerCheckout,
        step_name='Checkout source',
        sleep=2.0,
        backoff_factor=5,
        max_attempts=2
    )

  def checkout(
      self, name, checkout_path, url=None, ref=None, override_sha=False
  ):
    """Checks out a repo and returns sha1 of checked out revision.

    The supported repository names and their urls are defined in the global
    REPOS variable.

    Args:
      name (str): name of the supported repository.
      checkout_path (Path): directory to clone into.
      url (str): optional url overwrite of the remote repo.
      ref (str): optional ref overwrite to fetch and check out.
      override_sha (bool): flag to override the commit sha and used the passed in ref.
    """
    if name not in REPOS:
      raise ValueError('Unsupported repo: %s' % name)
    with self.m.step.nest('Checkout flutter/%s' % name):
      git_url = url or REPOS[name]
      # gitiles_commit.id is more specific than gitiles_commit.ref, which is
      # branch
      # if this a release build, self.m.buildbucket.gitiles_commit.id should have more priority than
      # ref since it is more specific, and we don't want to default to refs/heads/<REPO_BRANCHES[name]>
      if ref in ['refs/heads/beta', 'refs/heads/stable']:
        # When we currently perform a checkout of cocoon and flutter we get the cocoon sha from the
        # build. We checkout that version of cocoon and then when we go to checkout flutter we end
        # up using that sha so then the flutter checkout fails since that commit in cocoon is not in
        # the flutter repo. This just allows us to override that and use the original ref which for
        # the coming change is just the tot master branch.
        git_ref = ref if override_sha else (
            self.m.buildbucket.gitiles_commit.id or
            self.m.buildbucket.gitiles_commit.ref or ref
        )
      else:
        git_ref = (
            ref or self.m.buildbucket.gitiles_commit.id or
            self.m.buildbucket.gitiles_commit.ref or
            'refs/heads/%s' % REPO_BRANCHES[name]
        )

      def do_checkout():
        return self.m.git.checkout(
            git_url,
            dir_path=checkout_path,
            ref=git_ref,
            recursive=True,
            set_got_revision=True,
            tags=True
        )

      # Some outlier GoB mirror jobs can take >250secs.
      return self.m.utils.retry(
          do_checkout, sleep=10.0, backoff_factor=5, max_attempts=4
      )

  def in_release_and_main(self, checkout_path):
    """Determine if a commit was already tested on main branch.

    This is used to skip build in release branches to avoid consuming all the capacity
    testing commits in release branches that were already tested on main.
    """
    if self.m.properties.get('git_branch', '') in ['beta', 'stable']:
      branches = self.current_commit_branches(checkout_path)
      return len(branches) > 1
    # We assume the commit is not duplicated if it is not comming from beta or stable.
    return False

  def get_commit(self, checkout_path):
    with self.m.context(cwd=checkout_path):
      step_test_data = lambda: self.m.raw_io.test_api.stream_output_text(
          '12345abcde12345abcde12345abcde12345abcde\n'
      )
      commit = self.m.git(
          'rev-parse',
          'HEAD',
          stdout=self.m.raw_io.output_text(),
          step_test_data=step_test_data
      ).stdout.strip()
      return commit

  def get_env_ref(self):
    '''Get the ref of the current build from env.'''
    gitiles_commit = self.m.buildbucket.gitiles_commit.id
    if gitiles_commit:
      return gitiles_commit
    return self.m.properties.get('git_ref', 'led')

  def current_commit_branches(self, checkout_path):
    """Gets the list of branches for the current commit."""
    with self.m.step.nest('Identify branches'):
      with self.m.context(cwd=checkout_path):
        commit = self.get_commit(checkout_path)
        branches = self.m.git(
            'branch',
            '-a',
            '--contains',
            commit,
            stdout=self.m.raw_io.output_text()
        ).stdout.splitlines()
        # Discard local branches as we are interested only in remote branches.
        branches = [
            b.strip()
            for b in branches
            if b.strip().startswith('remotes/origin/')
        ]
        return [b.replace('remotes/origin/', '') for b in branches] or []

  def get_branch(self, checkout_path):
    """Get git branch for beta and stable channels.

    Post submit tests for release candidate branches pass the channel stable|beta in
    the git_branch property. As the commits are being tested before they are publised
    is not possible to use the channels to checkout the correct versions of dependencies
    from other repositories, furthermore the channels are only applicable to
    flutter/flutter repository. For tests with dependencies on other repositories we are
    using the release candidate branch to check out the equivalent to the commit under test.
    E.g. if the current commit comes from flutter@flutter-2.8-candiddate.16 then we checkout
    plugins@flutter-2.8-candiddate.16.

    To guess the branch name we get the current commit from the checkout and then we find
    all the different branches the commit exist on, if there is a branch that starts with
    flutter- then we assume that's the release candidate branch under test.
    """
    if self.m.properties.get('git_branch', '') in ['beta', 'stable']:
      branches = self.current_commit_branches(checkout_path)
      branches = [b for b in branches if b.startswith('flutter')]
      return branches[0] if len(branches) > 0 else self.m.properties.get(
          'git_branch', ''
      )
    return self.m.properties.get('git_branch', '')

  def flutter_environment(self, checkout_path):
    """Returns env and env_prefixes of an flutter/dart command environment."""
    dart_bin = checkout_path.join('bin', 'cache', 'dart-sdk', 'bin')
    flutter_bin = checkout_path.join('bin')
    # Fail if flutter bin folder does not exist. dart-sdk/bin folder will be
    # available only after running "flutter doctor" and it needs to be run as
    # the first command on the context using the environment.
    if not self.m.path.exists(flutter_bin):
      msg = (
          'flutter bin folders do not exist,'
          'did you forget to checkout flutter repo?'
      )
      self.m.step.empty(
          'Flutter Environment', status=self.m.step.FAILURE, step_text=msg
      )
    git_ref = self.m.properties.get('git_ref', '')
    pub_cache_path = self.m.path['start_dir'].join('.pub-cache')
    env = {
        # Setup our own pub_cache to not affect other slaves on this machine,
        # and so that the pre-populated pub cache is contained in the package.
        'PUB_CACHE':
            pub_cache_path,
        # https://github.com/flutter/flutter/wiki/Plugins-and-Packages-repository-structure#gradle-structure
        # go/artifact-hub
        'ARTIFACT_HUB_REPOSITORY':
            'artifactregistry://us-maven.pkg.dev/artifact-foundry-prod/maven-3p',
        # Windows Packaging script assumes this is set.
        'DEPOT_TOOLS':
            str(self.m.depot_tools.root),
        'SDK_CHECKOUT_PATH':
            checkout_path,
        'LUCI_CI':
            True,
        'LUCI_PR':
            re.sub('refs\/pull\/|\/head', '', git_ref),
        'LUCI_BRANCH':
            self.m.properties.get('release_ref', '').replace('refs/heads/', ''),
        'GIT_BRANCH':
            self.get_branch(checkout_path),
        'OS':
            'linux' if self.m.platform.name == 'linux' else
            ('darwin' if self.m.platform.name == 'mac' else 'win'),
        'REVISION':
            self.get_commit(checkout_path)
    }
    channel = self.m.properties.get('channel', None)
    if channel:
      env['CHANNEL'] = channel
    package_sharding = self.m.properties.get('package_sharding', None)
    if package_sharding:
      env['PACKAGE_SHARDING'] = package_sharding
    if self.m.properties.get('gn_artifacts', False):
      env['FLUTTER_STORAGE_BASE_URL'
         ] = 'https://storage.googleapis.com/flutter_archives_v2'
    env_prefixes = {'PATH': ['%s' % str(flutter_bin), '%s' % str(dart_bin)]}
    return env, env_prefixes

  def engine_environment(self, checkout_path):
    """Returns env and env_prefixes of an flutter/dart command environment."""
    dart_bin = checkout_path.join(
        'src', 'third_party', 'dart', 'tools', 'sdks', 'dart-sdk', 'bin'
    )
    git_ref = self.m.properties.get('git_ref', '')
    android_home = checkout_path.join(
        'src', 'third_party', 'android_tools', 'sdk'
    )
    android_tmp = self.m.path.mkdtemp()
    env = {
        # Windows Packaging script assumes this is set.
        'DEPOT_TOOLS':
            str(self.m.depot_tools.root),
        'ENGINE_CHECKOUT_PATH':
            checkout_path,
        'ENGINE_PATH':
            checkout_path,
        'LUCI_CI':
            True,
        'LUCI_PR':
            re.sub('refs\/pull\/|\/head', '', git_ref),
        'LUCI_BRANCH':
            self.m.properties.get('release_ref', '').replace('refs/heads/', ''),
        'GIT_BRANCH':
            self.get_branch(checkout_path.join('flutter')),
        'OS':
            'linux' if self.m.platform.name == 'linux' else
            ('darwin' if self.m.platform.name == 'mac' else 'win'),
        'ANDROID_HOME':
            str(android_home),
        'ANDROID_SDK_HOME':
            str(android_tmp),
        'ANDROID_USER_HOME':
            str(android_tmp.join('.android')),
        'LUCI_WORKDIR':
            str(self.m.path['start_dir']),
        'REVISION':
            self.m.buildbucket.gitiles_commit.id or ''
    }
    env_prefixes = {'PATH': ['%s' % str(dart_bin)]}
    return env, env_prefixes

  def monorepo_environment(self, checkout_path):
    """Returns env and env_prefixes of a monorepo command environment."""
    dart_bin = checkout_path.join(
        'engine', 'src', 'third_party', 'dart', 'tools', 'sdks', 'dart-sdk',
        'bin'
    )
    git_ref = self.m.properties.get('git_ref', '')
    android_home = checkout_path.join(
        'engine', 'src', 'third_party', 'android_tools', 'sdk'
    )
    android_tmp = self.m.path.mkdtemp()
    env = {
        # Windows Packaging script assumes this is set.
        'DEPOT_TOOLS':
            str(self.m.depot_tools.root),
        'ENGINE_CHECKOUT_PATH':
            checkout_path.join('engine'),
        'ENGINE_PATH':
            checkout_path.join('engine'),
        'LUCI_CI':
            True,
        'LUCI_PR':
            re.sub('refs\/pull\/|\/head', '', git_ref),
        'LUCI_BRANCH':
            self.m.properties.get('release_ref', '').replace('refs/heads/', ''),
        'GIT_BRANCH':
            self.get_branch(checkout_path.join('flutter')),
        'OS':
            'linux' if self.m.platform.name == 'linux' else
            ('darwin' if self.m.platform.name == 'mac' else 'win'),
        'ANDROID_HOME':
            str(android_home),
        'ANDROID_SDK_HOME':
            str(android_tmp),
        'ANDROID_USER_HOME':
            str(android_tmp.join('.android')),
        'LUCI_WORKDIR':
            str(self.m.path['start_dir']),
        'REVISION':
            self.m.buildbucket.gitiles_commit.id or ''
    }
    env_prefixes = {'PATH': ['%s' % str(dart_bin)]}
    return env, env_prefixes

  def sdk_checkout_path(self):
    """Returns the checkoout path of the current flutter_environment.

    Returns(Path): A path object with the current checkout path.
    """
    checkout_path = self.m.context.env.get('SDK_CHECKOUT_PATH')
    assert checkout_path, 'Outside of a flutter_environment?'
    return self.m.path.abs_to_path(checkout_path)

  def is_release_candidate_branch(self, checkout_path):
    """Returns true if the branch starts with "flutter-"."""
    commit_branches = self.current_commit_branches(checkout_path)
    for branch in commit_branches:
      if branch.startswith('flutter-'):
        return True
    return False

  def release_candidate_branch(self, checkout_path):
    """Returns the first branch that starts with "flutter-"."""
    commit_branches = self.current_commit_branches(checkout_path)
    for branch in commit_branches:
      if branch.startswith('flutter-'):
        return branch

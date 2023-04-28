# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Code for testing recipes."""

import datetime
import fnmatch
import functools

from google.protobuf import json_format as jsonpb
from google.protobuf import timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (
    builds_service as builds_service_pb2,
)
from PB.recipe_modules.flutter.recipe_testing import properties as properties_pb2
from recipe_engine import recipe_api
from RECIPE_MODULES.fuchsia.swarming_retry import api as swarming_retry_api

# The maximum amount of builds to go back through in buildbucket to find
# a run that matches the current branch
MAX_BUILD_RESULTS = 25

# The default branch for a build if there is no branch set in a build found
# from searching buildbucket
DEFAULT_BRANCH = 'main'


class Build(swarming_retry_api.LedTask):
  # This warning is spurious because LedTask defines _led_data.
  # pylint: disable=attribute-defined-outside-init

  def include_cl(self, cl):
    self._led_data = self._led_data.then("edit-cr-cl", cl)

  def include_recipe_bundle(self):
    self._led_data = self._led_data.then("edit-recipe-bundle")

  def use_realms(self):
    self._led_data = self._led_data.then(
        "edit", "-experiment", "luci.use_realms=true"
    )

  def set_properties(self, properties):
    args = []
    for k, v in properties.items():
      args += ["-pa", "%s=%s" % (k, self._api.json.dumps(v))]
    self._led_data = self._led_data.then("edit", *args)


class RecipeTestingApi(recipe_api.RecipeApi):
  """API for running tests and processing test results."""

  def __init__(self, props, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._recipe_depth = props.recipe_depth
    self.enabled = props.enabled
    self.max_build_age_seconds = int(
        datetime.timedelta(days=28).total_seconds()
    )
    self.projects = ("flutter",)

  def _get_affected_recipes(self, recipes_path):
    """Collect affected recipes.

        For now assume we care about all recipes.
        """

    with self.m.step.nest("get_affected_recipes") as parent_step:
      recipes_dir = recipes_path.join("recipes")
      recipe_files = self.m.file.listdir(
          "ls-recipes", recipes_dir, recursive=True
      )

      all_recipes = []
      for recipe_file in recipe_files:
        path = self.m.path.relpath(
            self.m.path.realpath(recipe_file),
            self.m.path.realpath(recipes_dir)
        )
        # Files inside folders that end in ".resources" are never recipes.
        if self.m.path.dirname(path).endswith(".resources"):
          continue

        name, ext = self.m.path.splitext(path)
        if ext == ".py":
          all_recipes.append(name)

      parent_step.logs["all recipes"] = all_recipes

      with self.m.context(cwd=recipes_path):
        changed_files = self.m.git.get_changed_files(commit="HEAD")
      parent_step.logs["changed files (raw)"] = changed_files

      def is_expected_json(path):
        # We want to ignore expected JSON files--they won't affect how recipes
        # run. It's possible there are JSON files used as data for recipes
        # instead of as expected test outputs, so determine which files to
        # ignore very narrowly.
        return self.m.path.splitext(path)[
            1] == ".json" and self.m.path.dirname(path).endswith(".expected")

      def is_python_test_file(path):
        """Return True if this is a test file that we should ignore."""
        # We want to ignore test_api.py files--they won't affect how recipes
        # run in led, they only affect how recipes run in
        # './recipes test run', and we test that every time any recipe is
        # changed.
        if (self.m.path.basename(path) == "test_api.py" and
            self.m.path.dirname(self.m.path.dirname(path)) == "recipe_modules"):
          return True

        # Also ignore test definitions themselves. By convention these are
        # given the filename 'full.py' in Fuchsia, but there is no
        # guarantee this will remain the case.
        test_dir_names = ("tests", "examples")
        if (self.m.path.splitext(path)[1] == ".py" and
            self.m.path.basename(self.m.path.dirname(path)) in test_dir_names):
          return True

        return False

      def is_ignored_file(path):
        return is_expected_json(path) or is_python_test_file(path)

      filtered_changed_files = [
          x for x in changed_files if not is_ignored_file(x)
      ]
      parent_step.logs["changed files (filtered)"] = filtered_changed_files or [
          "no changed files"
      ]

      res = self.m.step(
          "recipes-analyze",
          [
              recipes_path.join("recipes.py"),
              "analyze",
              self.m.json.input({
                  "recipes": all_recipes, "files": filtered_changed_files
              }),
              self.m.json.output(),
          ],
      )

      affected_recipes = res.json.output["recipes"]

      def should_test_all_recipes(path):
        globs = (
            "infra/config/recipes.cfg",
            # We particularly care about running CQ for flutter.proto changes.
            "recipe_proto/*.proto",
        )
        return any(fnmatch.fnmatch(path, glob) for glob in globs)

      special_changed_files = [
          f for f in changed_files if should_test_all_recipes(f)
      ]
      if special_changed_files:
        step = self.m.step.empty("mark all recipes as affected")
        step.presentation.step_summary_text = (
            "because these files were changed:"
        )
        step.presentation.step_text = "\n" + "\n".join(special_changed_files)
        affected_recipes = all_recipes

      parent_step.logs["affected recipes"] = affected_recipes

      # Skip running recipes in the `recipes/contrib` directory, because
      # they are generally lower-priority and not worth running by default
      # in recipes CQ.
      return {r for r in affected_recipes if not r.startswith("contrib/")}

  def _get_last_green_build(self, builder, cl_branch='main'):
    """Returns the build proto for a builder's most recent successful build.

        If no build younger than `self.max_build_age_seconds` is found, returns
        None. Also ensures that was returned build was run on the same branch
        the current recipe is running on.

        Args:
          builder: builder protobuf object
        """
    project, bucket, builder = builder.split('/')
    predicate = builds_service_pb2.BuildPredicate()
    predicate.builder.project = project
    predicate.builder.bucket = bucket
    predicate.builder.builder = builder
    predicate.status = common_pb2.SUCCESS

    builds = self.m.buildbucket.search(predicate, limit=MAX_BUILD_RESULTS)

    def built_on_branch(build, branch):
      """Return True if build was built on the provided branch."""
      current_branch = \
          'refs/heads/%s' % (branch or DEFAULT_BRANCH)
      build_properties = \
          build.input.properties
      if 'exe_cipd_version' in build_properties.keys():
        build_branch = build_properties['exe_cipd_version']
      else:
        build_branch = 'refs/heads/%s' % DEFAULT_BRANCH
      # Some recipes do not specify the branch, so in the case where the
      # branch is None, ensure a match can still be found.
      return build_branch in [current_branch, None]

    builds_with_current_branch = \
        list(filter(
            lambda build: built_on_branch(build, cl_branch), builds
        ))

    builds_with_current_branch.sort(
        reverse=True, key=lambda build: build.start_time.seconds
    )

    if not builds_with_current_branch:
      return None

    build = builds_with_current_branch[0]
    age_seconds = self.m.time.time() - build.end_time.seconds
    if age_seconds > self.max_build_age_seconds:
      return None
    return build

  def _create_led_build(self, orig_build, selftest_cl):
    builder = orig_build.builder
    # By default the priority is increased by 10 (resulting in a "lower"
    # priority), but we want it to stay the same.
    led_data = self.m.led("get-build", "-adjust-priority", "0", orig_build.id)

    build = Build(api=self.m, name=builder.builder, led_data=led_data)

    if orig_build.input.properties["recipe"] == "recipes":
      build.include_cl(selftest_cl)
    elif orig_build.input.gerrit_changes:
      orig_cl = orig_build.input.gerrit_changes[0]
      cl_id, patchset = self._get_latest_cl(orig_cl.host, orig_cl.project)
      # Setting the CL to a more recent CL helps avoid rebase errors, but
      # if unable to find a recent CL, fall back to the original build's
      # triggering CL. It usually works.
      if not cl_id:
        cl_id = orig_cl.change
        patchset = orig_cl.patchset
      url = "https://%s/c/%s/+/%d/%d" % (
          orig_cl.host,
          orig_cl.project,
          cl_id,
          patchset,
      )
      build.include_cl(url)
    build.set_properties(self._tryjob_properties())
    build.use_realms()

    return build

  @functools.lru_cache(maxsize=None)
  def _get_latest_cl(self, gerrit_host, project):
    """Returns number and patchset for a project's most recently landed CL.

        Args:
          gerrit_host (str): E.g., flutter-review.googlesource.com
          project (str): The name of the project in gerrit, e.g. "flutter"

        Returns:
          A tuple of
          * The integer change number for the CL corresponding to the commit at
            the tip of the main branch.
          * The last patchset of that CL.
        """
    gitiles_host = gerrit_host.replace("-review", "")
    remote = "https://%s/%s" % (gitiles_host, project)
    ref = self.m.git.get_default_remote_branch(remote)
    log = self.m.gitiles.log(
        remote, ref, limit=10, step_name="log %s" % project
    )

    for log_entry in log:
      commit_hash = log_entry["id"]
      step = self.m.gerrit.change_details(
          "latest change details for %s" % project,
          commit_hash,
          query_params=("CURRENT_REVISION",),
          host=gerrit_host,
          test_data=self.m.json.test_api.output({
              "_number": 12345,
              "current_revision": "5" * 40,
              "revisions": {"5" * 40: {"_number": 6}},
          }),
          ok_ret=(0, 1),
      )
      # A commit that is committed directly without code review won't have a
      # corresponding Gerrit CL, so fetching it will fail (which is fine, we'll
      # just skip it and try the next one).
      if step.retcode == 0:
        cl_number = step.json.output["_number"]
        rev = step.json.output["current_revision"]
        ps_number = step.json.output["revisions"][rev]["_number"]
        return (cl_number, ps_number)
    return None, None

  def run_lint(self, recipes_path, allowlist=""):
    """Run lint on recipes.

        Args:
          recipes_path (Path): The path to the root of the recipes repo.
          allowlist (str): A regex of import names to allow.
        """
    args = ["lint"]
    if allowlist:
      args.extend(["--allowlist", allowlist])
    with self.m.context(cwd=recipes_path):
      self.m.step(
          "lint",
          cmd=[self.m.context.cwd.join("recipes.py")] + args,
      )

  def run_unit_tests(self, recipes_path):
    """Run the recipe unit tests."""
    with self.m.context(cwd=recipes_path):
      self.m.step(
          "test",
          cmd=[
              self.m.context.cwd.join("recipes.py"),
              "test",
              "run",
          ],
      )

  def run_tests(
      self,
      recipes_path,
      selftest_cl,
      config,
      selftest_builder=None,
  ):
    """Launch CQ builders.

        Args:
          recipes_path (Path): Path to recipes repo checkout.
          selftest_cl (str): The CL to use to test a recursive recipe testing
            invocation.
          config (RecipeTesting proto): Many options for led/bb tests.
            TODO(fxbug.dev/88439): Make this a formal proto under
            recipe_modules/recipe_testing.
          selftest_builder (str|None): Builder to use to guarantee that we
            exercise the scheduling codepath when `use_buildbucket` is True.
        """
    # When run against a change to the recipes recipe, this is what the
    # swarming task stack should look like:
    #
    # * recipes.py from current recipe bundle, run against current CL
    # * recipes.py from current CL, run against SELFTEST_CL
    # * cobalt.py from current CL, run against current CL
    #
    # This works, but in case something goes wrong we need to make sure we
    # don't enter infinite recursion. We should never get to a third call to
    # recipes.py, so if we do we should exit.
    if self._recipe_depth >= 2:
      raise self.m.step.InfraFailure("recursion limit reached")

    builders = set()
    for project in config.projects:
      project_builders = set(
          self.m.commit_queue.all_tryjobs(
              project=project.name,
              include_unrestricted=project.include_unrestricted,
              include_restricted=project.include_restricted,
              config_name=project.cq_config_name or "commit-queue.cfg",
          )
      )

      for excluded_bucket in project.excluded_buckets:
        excluded_builders = set()
        for builder in project_builders:
          # Retrieve "<bucket>" from "<project>/<bucket>/<builder>".
          bucket = builder.split("/")[1]
          if bucket == excluded_bucket:
            excluded_builders.add(builder)

        if excluded_builders:
          project_builders -= excluded_builders
          with self.m.step.nest(
              "excluding {} builders from bucket {}/{}".format(
                  len(excluded_builders),
                  project.name,
                  excluded_bucket,
              )) as pres:
            pres.step_summary_text = "\n".join(sorted(excluded_builders))

      builders.update(project_builders)

    builders = sorted(builders)

    affected_recipes = self._get_affected_recipes(recipes_path=recipes_path)
    if not affected_recipes:
      return

    cl_branch = self._get_current_merging_branch()

    if config.use_buildbucket:
      self._run_buildbucket_tests(
          selftest_builder, builders, affected_recipes, cl_branch
      )
    else:
      self._run_led_tests(
          recipes_path, selftest_cl, builders, affected_recipes, cl_branch
      )

  def _is_build_affected(self, orig_build, affected_recipes, presentation):
    if not orig_build:
      presentation.step_summary_text = "no recent builds found"
      return False

    recipe = orig_build.input.properties["recipe"]
    assert recipe

    is_recipe_affected = recipe in affected_recipes
    presentation.step_summary_text = "SELECTED" if is_recipe_affected else "skipped"
    presentation.logs["recipe_used"] = recipe
    return is_recipe_affected

  def _get_green_tryjobs(self, expiry_secs=24 * 60 * 60):
    """Return the set of tryjobs that are green on the current patchset.

        Args:
          expiry_secs (int): Do not return tryjobs which are older than this
            value in seconds.
        """
    builds = self.m.buildbucket.search(
        builds_service_pb2.BuildPredicate(
            gerrit_changes=list(self.m.buildbucket.build.input.gerrit_changes),
            status=common_pb2.SUCCESS,
            create_time=common_pb2.TimeRange(
                start_time=timestamp_pb2.Timestamp(
                    seconds=int(self.m.time.time()) - expiry_secs,
                ),
            ),
        ),
        fields=["builder"],
        step_name="get green tryjobs",
    )
    return {
        self.m.buildbucket_util.full_builder_name(b.builder) for b in builds
    }

  def _run_buildbucket_tests(
      self, selftest_builder, builders, affected_recipes, cl_branch
  ):
    affected_builders = []
    recipes_is_affected = False

    with self.m.step.nest("get builders"), self.m.context(infra_steps=True):
      green_tryjobs = self._get_green_tryjobs()
      builders = [b for b in builders if b not in green_tryjobs]
      for builder in builders:
        with self.m.step.nest(builder) as presentation:
          orig_build = self._get_last_green_build(builder, cl_branch)
          if self._is_build_affected(orig_build, affected_recipes,
                                     presentation):
            # With recipe versioning, the `recipes` recipe is
            # already tested in this invocation, so don't schedule
            # any more `recipes` builds.
            if orig_build.input.properties["recipe"] == "recipes":
              recipes_is_affected = True
              continue
            affected_builders.append(builder)

    # If `affected_builders` is empty, but the current recipe was affected,
    # then we should schedule one self-test builder so we can still exercise
    # the scheduling codepath.
    if not affected_builders and recipes_is_affected:
      affected_builders = [selftest_builder]

    with self.m.step.nest("launch builds") as presentation:
      builds = self.m.subbuild.launch(
          # TODO(atyfto): Fix subbuild.launch so it can accept builders
          # with `bucket`s and/or `project`s which don't necessarily match
          # the current build's.
          builder_names=[b.split("/")[-1] for b in affected_builders],
          extra_properties=self._tryjob_properties(),
          presentation=presentation,
          # Present tryjobs in Gerrit since they are effectively
          # top-level builds.
          hide_in_gerrit=False,
      )
    with self.m.step.nest("collect builds"):
      results = self.m.subbuild.collect(
          build_ids=[b.build_id for b in builds.values()],
      )
      self.m.buildbucket_util.display_builds(
          "check builds",
          [b.build_proto for b in results.values()],
          raise_on_failure=True,
      )

  def _run_led_tests(
      self, recipes_path, selftest_cl, builders, affected_recipes, cl_branch
  ):
    builds = []
    with self.m.step.nest("get builders") as nest, self.m.context(
        cwd=recipes_path, infra_steps=True):
      for builder in builders:
        with self.m.step.nest(builder) as presentation:
          orig_build = self._get_last_green_build(builder, cl_branch)
          if self._is_build_affected(orig_build, affected_recipes,
                                     presentation):
            build = self._create_led_build(orig_build, selftest_cl)
            build.include_recipe_bundle()
            builds.append(build)

      nest.step_summary_text = "selected {} builds".format(len(builds))

    if not builds:
      return
    self.m.swarming_retry.run_and_present_tasks(builds)

  def _tryjob_properties(self):
    """Properties that should be set on each launched tryjob."""
    props = properties_pb2.InputProperties(
        # Signal to the launched build that it's being tested by this module.
        enabled=True,
        # Increment the recipe depth. This only has an effect on builds that
        # use this module.
        recipe_depth=self._recipe_depth + 1,
    )
    return {
        "$flutter/recipe_testing":
            jsonpb.MessageToDict(props, preserving_proto_field_name=True)
    }

  def _get_current_merging_branch(self):
    """Returns the branch that the current CL is being merged into.

        If the buildset is not available in the recipe, then DEFAULT_BRANCH is
        used.
        """
    tags = self.m.buildbucket.build.tags
    buildset_tag = list(filter(lambda tag: tag.key == 'buildset', tags))
    buildset_property = self.m.properties.get('buildset')
    if not buildset_tag and not buildset_property:
      return DEFAULT_BRANCH
    else:
      buildset = buildset_tag[0].value if buildset_tag else buildset_property
      host, cl_number = buildset.split('/')[2:4]
      cl_information = \
          self.m.gerrit_util.get_gerrit_cl_details(host, cl_number)
      return cl_information.get('branch')

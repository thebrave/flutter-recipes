# Copyright 2020 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import attr

import collections
import datetime

from recipe_engine import recipe_api
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from RECIPE_MODULES.fuchsia.utils import pluralize

# As of 2021-10-19, the `api.buildbucket.collect()` timeout defaults to
# something too short. We never want subbuild collection to timeout; we'd rather
# the whole build time out.
COLLECT_TIMEOUT = datetime.timedelta(hours=24)

# We implicitly rely on a select few properties being passed through
# from the parent build to the subbuild.
# NOTE: Only dynamically computed properties should be passed through
# automatically. Any static properties (i.e. properties that don't change
# between builds) should be configured explicitly on the subbuild's builder
# rather than implicitly passing them through.
PASS_THROUGH_PROPERTIES = {
    # Used by toolchain recipes to pass custom toolchain info.
    "$fuchsia/build",
    # Used by toolchain recipes to pass commit info.
    "$fuchsia/checkout",
    # recipe_bootstrap may pass some properties to subbuilds via this field.
    "$fuchsia/recipe_bootstrap",
    # If a parent build is running under recipe testing, then the
    # subbuild is as well, and it should be made aware of that.
    "$fuchsia/recipe_testing",
    # Needed for subbuilds to determine how the parent was invoked in CQ
    # (e.g. whether it's a dry run or full run).
    "$recipe_engine/cq",
    # Set by recipe_bootstrap. A subbuild should inherit the same
    # integration base revision as its parent so the two builds use the same
    # version of recipes and properties.
    "integration_base_revision",
    # Set by `led edit-recipe-bundle -property-only` to point to the uploaded
    # recipe bundle. It's then up to recipe_bootstrap to download the recipe
    # bundle and execute it. A led subbuild should use the same recipe bundle
    # version as its parent.
    "led_cas_recipe_bundle",
    # Set by recipe_engine on buildbucket builds.
    "$recipe_engine/buildbucket",
}


@attr.s
class SubbuildResult:
  """Subbuild result metadata."""

  builder = attr.ib(type=str)
  build_id = attr.ib(type=str, converter=str)
  url = attr.ib(type=str, default=None)
  build_proto = attr.ib(type=build_pb2.Build, default=None)


@attr.s
class _SplitBuilder:
  """Project/bucket/name triplet."""

  project = attr.ib(type=str)
  bucket = attr.ib(type=str)
  name = attr.ib(type=str)


class SubbuildApi(recipe_api.RecipeApi):
  """API for launching subbuilds and collecting the results."""

  def launch(
      self,
      builder_names,
      presentation,
      extra_properties=None,
      set_swarming_parent_run_id=True,
      hide_in_gerrit=True,
      include_sub_invs=True,
  ):
    """Launches builds with buildbucket or led.

        If the current task was launched with led, then subbuilds will also be
        launched with led.

        Args:
          builder_names (list(str)): The names of the builders to launch.
          presentation (StepPresentation): The presentation to add logs to.
          extra_properties (dict): The extra set of properties to launch the
            builders with. These will override the parent properties that will be
            passed to the children by default.
          set_swarming_parent_run_id (bool): Whether to set swarming parent run
            ID on buildbucket builds.
          hide_in_gerrit (bool): Hide buildbucket subbuilds in the Gerrit UI.
          include_sub_invs (bool): Whether the parent should inherit ResultDB
            test results from the child builds.

        Returns:
          launched_builds (dict): The launched_builds is a map from builder name
          to the corresponding SubbuildResult.
        """
    parent_properties = self.m.properties.thaw()
    properties = {
        key: val
        for key, val in parent_properties.items()
        if key and key in PASS_THROUGH_PROPERTIES
    }
    if extra_properties:
      properties.update(extra_properties)

    # If this task was launched by led, we launch the child with led as well.
    # This lets us ensure that the parent and child use the same version of
    # the recipes code. That is a requirement for testing, as well as for
    # avoiding the need to do soft transitions when updating the interface
    # between the parent and child recipes.
    if self.m.led.launched_by_led:
      builds = self._launch_with_led(builder_names, properties)
    else:
      builds = self._launch_with_buildbucket(
          builder_names,
          properties,
          set_swarming_parent_run_id=set_swarming_parent_run_id,
          hide_in_gerrit=hide_in_gerrit,
          include_sub_invs=include_sub_invs,
      )
    for builder, build in builds.items():
      presentation.links[builder] = build.url
    return builds

  def split_builder(self, builder_name):
    """Split a builder name into parts, filling in from current build."""
    parent = self.m.buildbucket.build.builder

    *prefixes, name = builder_name.split("/")
    assert len(prefixes) <= 2, f"bad builder_name {builder_name}"
    if len(prefixes) == 2:
      project, bucket = prefixes
    elif len(prefixes) == 1:
      project = parent.project
      bucket = prefixes[0]
    else:
      project = parent.project
      bucket = parent.bucket

    return _SplitBuilder(project, bucket, name)

  def _launch_with_led(self, builder_names, properties):
    edit_args = []
    for k, v in sorted(properties.items()):
      edit_args.extend(["-p", f"{k}={self.m.json.dumps(v)}"])
    edit_cr_cl_arg = None
    bb_input = self.m.buildbucket.build_input
    if bb_input.gerrit_changes:
      gerrit_change = bb_input.gerrit_changes[0]
      edit_cr_cl_arg = f"https://{gerrit_change.host}/c/{gerrit_change.project}/+/{int(gerrit_change.change)}"

    builds = {}
    for builder_name in builder_names:
      builder = self.split_builder(builder_name)
      led_data = self.m.led(
          "get-builder",
          # By default, led reduces the priority of tasks from their
          # values in buildbucket which we do not want.
          "-adjust-priority",
          "0",
          f"{builder.project}/{builder.bucket}/{builder.name}",
      )
      led_data = led_data.then("edit", *edit_args)
      if edit_cr_cl_arg:
        led_data = led_data.then("edit-cr-cl", edit_cr_cl_arg)
      led_data = self.m.led.inject_input_recipes(led_data)
      launch_res = led_data.then("launch", "-modernize", "-real-build")
      task_id = launch_res.launch_result.task_id or launch_res.launch_result.build_id
      build_url_swarming = 'https://ci.chromium.org/swarming/task/%s?server=%s' % (
          task_id,
          launch_res.launch_result.swarming_hostname,
      )
      build_url_bb = 'https://%s/build/%s' % (
          launch_res.launch_result.buildbucket_hostname, task_id
      )
      build_url = build_url_swarming if launch_res.launch_result.task_id else build_url_bb
      builds[builder_name] = SubbuildResult(
          builder=builder_name, build_id=task_id, url=build_url
      )
    return builds

  def _launch_with_buildbucket(
      self,
      builder_names,
      properties,
      set_swarming_parent_run_id,
      hide_in_gerrit,
      include_sub_invs,
  ):
    reqs = []
    swarming_parent_run_id = (
        self.m.swarming.task_id if set_swarming_parent_run_id else None
    )
    bb_tags = {"skip-retry-in-gerrit": "subbuild"}
    if hide_in_gerrit:
      bb_tags["hide-in-gerrit"] = "subbuild"
    for builder_name in builder_names:
      builder = self.split_builder(builder_name)
      reqs.append(
          self.m.buildbucket.schedule_request(
              project=builder.project,
              bucket=builder.bucket,
              builder=builder.name,
              properties=properties,
              swarming_parent_run_id=swarming_parent_run_id,
              priority=None,  # Leave unset to avoid overriding priority from configs.
              tags=self.m.buildbucket.tags(**bb_tags),
          )
      )

    scheduled_builds = self.m.buildbucket.schedule(
        reqs, step_name="schedule", include_sub_invs=include_sub_invs
    )

    builds = {}
    for build in scheduled_builds:
      build_url = f"https://ci.chromium.org/b/{build.id}"
      builds[build.builder.builder] = SubbuildResult(
          builder=build.builder.builder, build_id=build.id, url=build_url
      )
    return builds

  def collect(self, build_ids, launched_by_led=None, extra_fields=frozenset()):
    """Collects builds with the provided build_ids.

        Args:
          build_ids (list(str)): The list of build ids to collect results for.
          presentation (StepPresentation): The presentation to add logs to.
          launched_by_led (bool|None): Whether the builds to collect were
              launched by led. If None, then this value will be determined by
              whether the current task was launched by led.
          extra_fields (set): Extra fields to include in the buildbucket
            response.

        Returns:
          A map from build IDs to the corresponding SubbuildResult.
        """
    if launched_by_led is None:
      launched_by_led = self.m.led.launched_by_led
    builds = self._collect_from_buildbucket(build_ids, extra_fields)
    return collections.OrderedDict(
        sorted(builds.items(), key=lambda item: (item[1].builder, item[0]))
    )

  def get_property(self, build_proto, property_name):
    """Retrieve an output property from a subbuild's Build proto.

        Ensures a clear and unified missing property error message across all
        builders that use this recipe module.
        """
    try:
      return build_proto.output.properties[property_name]
    except ValueError:
      raise self.m.step.InfraFailure(
          f"Subbuild did not set the {property_name!r} output property"
      )

  def _collect_from_buildbucket(self, build_ids, extra_fields):
    bb_fields = self.m.buildbucket.DEFAULT_FIELDS.union({
        "infra.swarming.task_id", "summary_markdown"
    }).union(extra_fields)

    builds = self.m.buildbucket.collect_builds(
        [int(build_id) for build_id in build_ids],
        interval=20,  # Lower from default of 60 b/c we're impatient.
        timeout=COLLECT_TIMEOUT,
        step_name="collect",
        fields=bb_fields,
    )

    failed_builds = [
        b for b in builds.values() if b.status != common_pb2.SUCCESS
    ]
    if failed_builds:
      task_ids = [b.infra.swarming.task_id for b in failed_builds]
      # Make sure task IDs are non-empty.
      assert all(task_ids), task_ids

      # Wait for the underlying Swarming tasks to complete. The Swarming
      # task for a Buildbucket build can take significantly longer to
      # complete than the build itself due to post-processing outside the
      # scope of the build's recipe (e.g. cache pruning). If the parent
      # build and its Swarming task both complete before the subbuild's
      # Swarming task finishes post-processing, then the subbuild's
      # Swarming task will be killed by Swarming due to the parent being
      # complete.
      #
      # That is actually working as intended. However, it's confusing for
      # a subbuild to be marked as killed when the recipe actually exited
      # normally; "killed" usually only happens for CQ builds, when a
      # build is canceled by CQ because a new patchset of the triggering
      # CL is uploaded. So it's convenient to have dashboards and queries
      # ignore "killed" tasks. We use this workaround to ensure that
      # failed subbuilds with long post-processing steps have time to
      # complete and exit cleanly with a plain old "COMPLETED (FAILURE)"
      # status.
      #
      # We only do this if the subbuild failed as a latency optimization.
      # If all subbuilds passed, the parent will go on to do some more
      # steps using the results of the subbuilds, leaving time for the
      # subbuilds' tasks to complete asynchronously, so we don't want to
      # block here while the tasks complete.
      self.m.swarming.collect(
          f"wait for {pluralize('task', task_ids)} to complete", task_ids
      )
    return {
        str(build.id): SubbuildResult(
            builder=build.builder.builder, build_id=build.id, build_proto=build
        ) for build in builds.values()
    }

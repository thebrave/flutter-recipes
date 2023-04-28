# Copyright 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import attr
import json
import collections

from google.protobuf import duration_pb2
from recipe_engine import recipe_api
from recipe_engine import engine_types
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from RECIPE_MODULES.fuchsia.utils import pluralize

DRONE_TIMEOUT_SECS = 3600 * 3  # 3 hours.

# Builder names use full platform name instead of short names. We need to
# map short names to full platform names to be able to identify the drone
# used to run the subshards.
PLATFORM_TO_NAME = {'win': 'Windows', 'linux': 'Linux', 'mac': 'Mac'}

# Internal properties that should be set for builds running on BuildBucket.
PROPERTIES_TO_REMOVE = [
    '$recipe_engine/buildbucket', 'buildername', '$recipe_engine/runtime',
    'is_experimental'
]

# Environments map to calculate the environment from the bucket.
ENVIRONMENTS_MAP = {
    'try': '', 'staging': 'Staging ', 'flutter': 'Production ',
    'prod': 'Production '
}


@attr.s
class SubbuildResult(object):
  """Subbuild result metadata."""
  # Task name for led and "<Platform> <Environment> Drone" for buildbucket.
  builder = attr.ib(type=str)
  build_id = attr.ib(type=str)
  # Task name for both led and buildbucket.
  build_name = attr.ib(type=str)
  url = attr.ib(type=str, default=None)
  build_proto = attr.ib(type=build_pb2.Build, default=None)


class ShardUtilApi(recipe_api.RecipeApi):
  """Utilities to shard tasks."""

  def unfreeze_dict(self, dictionary):
    """Creates a mutable dictionary out of a FrozenDict.

    FrozenDict example:
      FrozenDict([('dependency', 'open_jdk'), ('version', 'version:11')])
    , which is not a default python type.

    This refactors it to regular dict:
      {'dependency': 'open_jdk', 'version': 'version:11'}
    """
    result = collections.OrderedDict()
    for k, v in sorted(dictionary.items()):
      if isinstance(v, engine_types.FrozenDict):
        result[k] = self.unfreeze_dict(v)
      elif isinstance(v, (list, tuple)):
        result[k] = [
            self.unfreeze_dict(i)
            if isinstance(i, engine_types.FrozenDict) else i for i in v
        ]
      else:
        result[k] = v
    return result

  def pre_process_properties(self, target):
    """Converts json properties to dicts or lists.

   Dict or lists in ci_yaml are passed as json string to recipes and they
   need to be converted back to dict or lists before passing them to subbuilds.

   Args:
     target: A target dictionary as read from the yaml file.

   Returns:
     A copy of the original dictionary with the json properties decoded.
   """
    if target.get('properties'):
      properties = target.get('properties')
      new_props = {}
      for k, v in properties.items():
        if isinstance(v, str) and (v.startswith('[') or v.startswith('{')):
          new_props[k] = json.loads(v)
        else:
          new_props[k] = v
      target['properties'] = new_props
    return target

  def struct_to_dict(self, struct):
    """Transforms a proto structure to a dictionary.

    Args:
      struct: A proto structure.
    Returns:
      A dictionary representation of the proto structure.

    This is because the proto structures can not be passed to the BuildBucket or led
    requests.
    """
    return collections.OrderedDict((k, v) for k, v in struct.items())

  def schedule_builds(self, builds, presentation, branch='main'):
    """Schedule builds using the builds configurations.

    Args:
      builds(dict): The build configurations to be passed to BuildBucket or led.
      presentation(StepPresentation): The step object used to add links and/or logs.
      branch(String): The current branch name.
    Returns:
      A dictionary with a long build_id as key and SubbuildResult as value.
    """
    # Update build with default recipe.
    updated_builds = []
    for b in builds:
      build = self.unfreeze_dict(b)
      build['recipe'] = build.get('recipe') or 'engine_v2/builder'
      updated_builds.append(build)
    return self.schedule(updated_builds, presentation, branch=branch)

  def schedule_tests(self, tests, build_results, presentation):
    """Schedule tests using build_results for dependencies.

    Args:
      tests(dict): The test configurations to be passed to BuildBucket or led.
      build_results: A dictionary with a long build_id as key and SubbuildResult as value.
      presentation(StepPresentation): The step object used to add links and/or logs.
    Returns:
      A dictionary with a long build_id as key and SubbuildResult as value.
    """
    # Expand tests with result archives for dependencies.
    results_map = {b.build_name: b for k, b in build_results.items()}
    # build_results to map of builder name
    updated_tests = []
    for t in tests:
      test = self.unfreeze_dict(t)
      test['resolved_deps'] = []
      test['recipe'] = test.get('recipe') or 'engine_v2/tester'
      for dep in test.get('dependencies', []):
        dep_dict = self.struct_to_dict(
            results_map[dep].build_proto.output.properties['cas_output_hash']
        )
        test['resolved_deps'].append(dep_dict)
      updated_tests.append(test)
    return self.schedule(updated_tests, presentation)

  def schedule(self, builds, presentation, branch='main'):
    """Schedules one subbuild per build configuration.

    Args:
      builds(dict): The build/test configurations to be passed to BuildBucket or led.
      presentation(StepPresentation): The step object used to add links and/or logs.
      branch(String): The current branch name.
    Returns:
      A dictionary with a long build_id as key and SubbuildResult as value.
    """
    build_list = [self.unfreeze_dict(b) for b in builds]
    if self.m.led.launched_by_led:
      builds = self._schedule_with_led(build_list)
    else:
      builds = self._schedule_with_bb(build_list, branch=branch)
    return builds

  def _schedule_with_led(self, builds):
    """Schedules one subbuild per build using led.

    Args:
      builds(dict): The build/test configurations to be passed to BuildBucket or led.
    Returns:
      A dictionary with a long build_id as key and SubbuildResult as value.
    """
    # Dependencies get here as a frozen dict we need to force them back
    # to list of dicts.
    results = {}
    for build in builds:
      task_name = build.get('name')
      drone_properties = self.m.properties.thaw()
      # Do not propagate main build deps.
      drone_properties.pop('dependencies', None)
      drone_properties.update(build.get('properties', []))
      drone_properties['build'] = build
      drone_properties['gclient_variables'] = build.get('gclient_variables', {})
      drone_properties['task_name'] = task_name
      # Delete builds property if it exists.
      drone_properties.pop('builds', None)
      # Copy parent bot dimensions.
      drone_dimensions = build.get('drone_dimensions', [])
      # ci.yaml provided dimensions.
      ci_yaml_dimensions = build.get('dimensions', {})
      platform_name = build.get('platform') or PLATFORM_TO_NAME.get(
          self.m.platform.name
      )

      # Buildbucket properties are not propagated to sub-builds when running with
      # led. Copy the properties bb gitiles_commit to git_ref and git_url if not
      # set already.
      if not (drone_properties.get('git_ref') or
              drone_properties.get('git_url')):
        host = self.m.buildbucket.gitiles_commit.host
        project = self.m.buildbucket.gitiles_commit.project
        drone_properties['git_url'] = f'https://{host}/{project}'
        drone_properties['git_ref'] = self.m.buildbucket.gitiles_commit.id

      # Override recipe.
      drone_properties['recipe'] = build['recipe']
      bucket = self.m.buildbucket.build.builder.bucket
      environment = ENVIRONMENTS_MAP.get(bucket, '')
      builder_name = build.get(
          'drone_builder_name',
          '%s %sEngine Drone' % (platform_name, environment)
      )
      suffix = drone_properties.get('builder_name_suffix')
      if suffix:
        builder_name = '%s%s' % (builder_name, suffix)
      parent = self.m.buildbucket.build.builder
      led_data = self.m.led(
          'get-builder',
          '-real-build',
          '%s/%s/%s' % (parent.project, parent.bucket, builder_name),
      )
      edit_args = []
      for k, v in sorted(drone_properties.items()):
        if k in PROPERTIES_TO_REMOVE:
          continue
        edit_args.extend(['-p', '%s=%s' % (k, self.m.json.dumps(v))])
      # led reduces the priority of tasks by 10 from their values in
      # buildbucket which we do not want.
      # TODO(crbug.com/1138533) Add an option to led to handle this.
      led_data.result.buildbucket.bbagent_args.build.infra.swarming.priority -= 20
      led_data = led_data.then('edit', *edit_args)
      led_data = led_data.then('edit', '-name', task_name)
      led_data = led_data.then('edit', '-r', build['recipe'])
      for d in drone_dimensions:
        led_data = led_data.then('edit', '-d', d)
      for k, v in ci_yaml_dimensions.items():
        led_data = led_data.then('edit', "-d", '%s=%s' % (k, v))
      led_data = self.m.led.inject_input_recipes(led_data)
      launch_res = led_data.then('launch', '-modernize', '-real-build')
      # real-build is being used and only build_id is being populated
      task_id = launch_res.launch_result.task_id or launch_res.launch_result.build_id
      build_url_swarming = 'https://ci.chromium.org/swarming/task/%s?server=%s' % (
          task_id,
          launch_res.launch_result.swarming_hostname,
      )
      build_url_bb = 'https://%s/build/%s' % (
          launch_res.launch_result.buildbucket_hostname, task_id
      )
      build_url = build_url_swarming if launch_res.launch_result.task_id else build_url_bb
      results[task_name] = SubbuildResult(
          builder=task_name,
          build_id=task_id,
          url=build_url,
          build_name=task_name
      )
    return results

  def _schedule_with_bb(self, builds, branch='main'):
    """Schedules builds using builbbucket.

    Args:
      builds(dict): The build/test configurations to be passed to BuildBucket or led.
      branch(String): The current branch name.
    Returns:
      A dictionary with a long build_id as key and SubbuildResult as value.
    """
    swarming_parent_run_id = self.m.swarming.task_id
    reqs = []
    task_names = []
    for build in builds:
      task_name = build.get('name')
      drone_properties = self.m.properties.thaw()
      # Do not propagate main build deps.
      drone_properties.pop('dependencies', None)
      drone_properties.update(build.get('properties', []))
      drone_properties['build'] = build
      drone_properties['gclient_variables'] = build.get('gclient_variables', {})
      # Copy parent bot dimensions.
      drone_dimensions = build.get('drone_dimensions', [])
      # ci.yaml provided dimensions.
      ci_yaml_dimensions = build.get('dimensions', {})
      task_dimensions = []
      platform_name = build.get('platform') or PLATFORM_TO_NAME.get(
          self.m.platform.name
      )
      bucket = self.m.buildbucket.build.builder.bucket
      environment = ENVIRONMENTS_MAP.get(bucket, '')
      builder_name = build.get(
          'drone_builder_name',
          '%s %sEngine Drone' % (platform_name, environment)
      )
      suffix = drone_properties.get('builder_name_suffix')
      if suffix:
        builder_name = '%s%s' % (builder_name, suffix)
      # Delete builds property if it exists.
      drone_properties.pop('builds', None)
      for d in drone_dimensions:
        k, v = d.split('=')
        task_dimensions.append(common_pb2.RequestedDimension(key=k, value=v))
      for k, v in ci_yaml_dimensions.items():
        task_dimensions.append(common_pb2.RequestedDimension(key=k, value=v))
      # Override recipe.
      drone_properties['recipe'] = build['recipe']
      properties = collections.OrderedDict(
          (key, val)
          for key, val in sorted(drone_properties.items())
          if key not in PROPERTIES_TO_REMOVE
      )
      task_names.append(task_name)
      req = self.m.buildbucket.schedule_request(
          swarming_parent_run_id=self.m.swarming.task_id,
          builder=builder_name,
          properties=properties,
          dimensions=task_dimensions or None,
          # Having main build and subbuilds with the same priority can lead
          # to a deadlock situation when there are limited resources. For example
          # if we have only 7 mac bots and we get more than 7 new build requests the
          # within minutes of each other then the 7 bots will be used by main tasks
          # and they will all timeout waiting for resources to run subbuilds.
          # Increasing priority won't fix the problem but will make the deadlock
          # situation less unlikely.
          # https://github.com/flutter/flutter/issues/59169.
          #
          # Set priority to be same of main build temporily to help triage
          # https://github.com/flutter/flutter/issues/124155
          priority=30,
          exe_cipd_version=self.m.properties.get(
              'exe_cipd_version', 'refs/heads/%s' % branch
          )
      )
      # Increase timeout if no_goma, since the runtime is going to
      # be much longer.
      if drone_properties.get("no_goma", False):
        req.execution_timeout.FromSeconds(60 * 60 * 2)
      reqs.append(req)
    scheduled_builds = self.m.buildbucket.schedule(reqs, step_name="schedule")
    results = {}
    for build, task_name in zip(scheduled_builds, task_names):
      build_url = "https://ci.chromium.org/b/%s" % build.id
      results[build.id] = SubbuildResult(
          builder=build.builder.builder,
          build_id=build.id,
          url=build_url,
          build_name=task_name
      )
    return results

  def collect(self, tasks):
    """Collects builds from build bucket services using the provided tasks.

    Args:
      tasks (dict(int, SubbuildResult)): A dictionary with the subbuild
        results and the build id as key.

    Returns: A list of SubBuildResult, one per task.
    """
    build_ids = [build.build_id for build in tasks.values()]
    build_id_to_name = {
        int(build.build_id): build.build_name for build in tasks.values()
    }
    bb_fields = self.m.buildbucket.DEFAULT_FIELDS.union({
        "infra.swarming.task_id",
        "summary_markdown",
        "input",
    })
    # As of 2019-11-18, timeout defaults to something too short.
    # We never want this step to time out. We'd rather the whole build time out.
    builds = self.m.buildbucket.collect_builds(
        [int(build_id) for build_id in build_ids],
        interval=20,  # Lower from default of 60 b/c we're impatient.
        timeout=24 * 60 * 60,
        step_name="collect",
        fields=bb_fields,
        # Setting mirror status to False allows to pass the error processing
        # to the subbuild presentation step.
        mirror_status=False,
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
          "wait for %s to complete" % pluralize("task", task_ids), task_ids
      )
    for build_id, build in sorted(builds.items()):
      builds[build_id] = SubbuildResult(
          builder=build.builder.builder,
          build_id=build_id,
          build_proto=build,
          build_name=build_id_to_name[int(build_id)],
          url=self.m.buildbucket.build_url(build_id=build_id)
      )
    return builds

  def download_full_builds(self, build_results, out_build_paths):
    """Downloads intermediate builds from CAS.

    Args:
      build_results (dict(int, SubbuildResult)): A dictionary with the subbuild
        result and the build id as key.

    Mac and fuchsia use artifacts from different sub-builds to generate the final artifacts.
    Calls to this API will happen most likely after all the subbuilds have been completed and
    only if global generators will be executed.
    """
    for build_id in build_results:
      build_props = build_results[build_id].build_proto.output.properties
      if 'cas_output_hash' in build_props:
        cas_out_dict = build_props['cas_output_hash']
        build_name = build_results[build_id].build_name
        if 'full_build' in cas_out_dict:
          self.m.cas.download(
              'Download for build %s and cas key %s' % (build_id, build_name),
              cas_out_dict['full_build'], out_build_paths
          )

  def archive_full_build(self, build_dir, target):
    """Archives a full build in cas.

    Args:
      build_dir: The path to the build output folder.
      target(str): The name of the build we are archiving.

    Returns:
      A string with the hash of the cas archive.
    """
    cas_dir = self.m.path.mkdtemp('out-cas-directory')
    cas_engine = cas_dir.join(target)
    self.m.file.copytree('Copy host_debug_unopt', build_dir, cas_engine)

    def _upload():
      return self.m.cas_util.upload(
          cas_dir, step_name='Archive full build for %s' % target
      )

    # Windows CAS upload is flaky, hashes are calculated before files are fully synced to disk.
    return self.m.retry.basic_wrap(
        _upload,
        step_name='Archive full build',
        sleep=10.0,
        backoff_factor=5,
        max_attempts=3
    )

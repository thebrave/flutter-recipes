# Copyright 2019 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


class FlutterSwarmingRetryTestApi(recipe_test_api.RecipeTestApi):

  def task_result(
      self,
      name,
      task_id,
      failed=False,
      incomplete=False,
      timed_out=False,
      **kwargs
  ):
    """Mock data for call to api.buildbucket.collect().

        Args:
          name (str): name of task
          task_id (str): id of task
          failed (bool): if the task failed
          incomplete (bool): if the task is incomplete
          timed_out (bool): if the task timed out (implies failed)
          **kwargs (dict): additional args to pass to swarming.task_result()
        """
    assert not (failed and incomplete)
    assert not (timed_out and incomplete)

    failed = failed or timed_out

    msg = self.m.buildbucket.try_build_message(
        builder='builder', project='project', build_id=task_id
    )
    state = common_pb2.Status.SUCCESS
    if incomplete:
      state = common_pb2.Status.STARTED
    #  name = None
    elif timed_out:
      state = common_pb2.Status.CANCELED
    elif failed:
      state = common_pb2.Status.FAILURE

    msg.status = state
    return msg

  # These methods are just for convenience to make tests more readable.
  def incomplete_task(self, name, task_id, **kwargs):
    return self.task_result(name, task_id, incomplete=True, **kwargs)

  def failed_task(self, name, task_id, **kwargs):
    return self.task_result(name, task_id, failed=True, **kwargs)

  def timed_out_task(self, name, task_id, **kwargs):
    return self.task_result(name, task_id, timed_out=True, **kwargs)

  def passed_task(self, name, task_id, **kwargs):
    return self.task_result(name, task_id, **kwargs)

  def collect_data(self, results, iteration=0):
    return self.m.buildbucket.simulated_collect_output(
        results,
        step_name=f"launch/collect.{int(iteration)}.buildbucket.collect"
    )

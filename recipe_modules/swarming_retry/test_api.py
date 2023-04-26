# Copyright 2019 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class FuchsiaSwarmingRetryTestApi(recipe_test_api.RecipeTestApi):
    def _attempt(self, attempt, iteration):
        """If not given guess the attempt number from context."""

        # First, if the attempt number is given use it. The next couple
        # statements make some assumptions but this is the way to ignore
        # those assumptions.
        if attempt is not None:  # pragma: no cover
            return attempt

        # If no attempt number is given assume attempts starting at iteration
        # 0 have attempt number 0.
        if iteration == 0:
            return 0

        # If not at iteration 0 assume we're relaunching and since the max
        # attempts is currently 2 this has to be attempt 1.
        return 1

    def trigger_data(self, name, task_id, iteration=0, attempt=None):
        """Like led_data() above, but for mocking api.swarming.trigger."""

        attempt = self._attempt(attempt=attempt, iteration=iteration)

        step_name = (
            f"launch/collect.{iteration}.launch.{name} (attempt {attempt}).trigger"
        )
        launch_data = self.m.swarming.trigger(
            task_names=[name], initial_id=int(task_id)
        )
        return self.step_data(step_name, launch_data)

    def task_result(
        self, name, task_id, failed=False, incomplete=False, timed_out=False, **kwargs
    ):
        """Mock data for call to api.swarming.collect().

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

        state = self.m.swarming.TaskState.COMPLETED
        if incomplete:
            state = None
            name = None
        elif timed_out:
            state = self.m.swarming.TaskState.TIMED_OUT

        return self.m.swarming.task_result(
            id=str(task_id), name=name, state=state, failure=failed, **kwargs
        )

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
        return self.override_step_data(
            f"launch/collect.{int(iteration)}.collect", self.m.swarming.collect(results)
        )

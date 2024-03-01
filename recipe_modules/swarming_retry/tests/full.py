# Copyright 2019 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

from PB.go.chromium.org.luci.led.job import job as job_pb2

from RECIPE_MODULES.flutter.swarming_retry import api as swarming_retry_api

DEPS = [
    "flutter/swarming_retry",
    "recipe_engine/buildbucket",
    "recipe_engine/led",
    "recipe_engine/properties",
    "recipe_engine/step",
]

PROPERTIES = {
    "full":
        Property(
            kind=bool,
            default=False,
            help="Whether to run six tasks or just one.",
        ),
    "run_count":
        Property(
            kind=int,
            default=1,
            help="Number of successful runs we want for each task.",
        ),
    "task_type":
        Property(
            kind=str,
            default="test",
            help="Type of tasks to create. Options: "
            '"test", "internal_failure", "raising", "led", "triggered".',
        ),
    "max_attempts":
        Property(kind=int, default=2, help="Overall max attempts."),
    "last_task_max_attempts":
        Property(
            kind=int,
            default=None,
            help="Override the overall max attempts by setting on "
            "Task.max_attempts. Only set on last task.",
        ),
    "abort_early":
        Property(
            kind=bool,
            default=False,
            help="Whether to run a task that will fail and abort early",
        ),
    "on_backend":
        Property(
            kind=bool,
            help="whether the build infra backend is supported",
            default=True,
        ),
}


class Task(swarming_retry_api.Task):
  """Required subclass for testing swarming_retry.

    Defined inside a function because base class is inside api object.
    """

  def __init__(self, initial_task_id, *args, **kwargs):
    """Construct a Task object.

        Args:
          initial_task_id (int or str): integer decimal value (since this needs
            to be incremented but is then used as a str later this method
            accepts both int and str types to minimize confusion, so long as
            int(initial_task_id) works)
        """

    abort_early = kwargs.pop("abort_early", False)
    kwargs.pop("on_backend", True)
    super().__init__(*args, **kwargs)
    self._next_task_id = int(initial_task_id)
    self.abort_early_if_failed = abort_early

  def launch(self, _):
    kwargs = {
        "task_id": str(self._next_task_id),
    }

    self._next_task_id += 1

    # This looks funny but it's needed to ensure coverage of
    # Attempt.task_ui_link.
    if self._next_task_id % 2 == 0:
      kwargs["host"] = "testhost"
    else:
      kwargs["task_ui_link"] = f"https://testhost/task?id={kwargs['task_id']}"

    attempt = self._api.swarming_retry.Attempt(**kwargs)
    self._api.step.empty(f"launch {self.name}", step_text=attempt.task_id)
    return attempt


class FlakeTask(Task):

  def process_result(self, attempt):
    attempt.has_flakes = True


class InternalFailureTask(Task):

  def process_result(self, attempt):
    attempt.failure_reason = "internal failure"


class RaisingTask(Task):

  def process_result(self, _):
    self._api.step.empty("failing step", status=self._api.step.FAILURE)


class LedTask(swarming_retry_api.LedTask):

  def __init__(self, initial_task_id, api, **kwargs):
    ir = api.led("get-builder", "project/bucket:builder")
    build_proto = ir.result.buildbucket.bbagent_args.build
    build_proto.id = int(initial_task_id)
    self.on_backend = kwargs.pop("on_backend", True)
    if self.on_backend:
      build_proto.infra.backend.task.id.id = str(initial_task_id)
      build_proto.infra.backend.config['priority'] = 30
    else:
      build_proto.infra.swarming.priority = 30
      build_proto.infra.swarming.task_id = str(initial_task_id)
    super().__init__(ir, api=api, **kwargs)

  def launch(self, priority_boost_amount):
    ret = super().launch(priority_boost_amount)

    build_proto = self._led_data.result.buildbucket.bbagent_args.build
    if self.on_backend:
      cur_id = int(build_proto.infra.backend.task.id.id)
    else:
      cur_id = int(build_proto.infra.swarming.task_id)
    build_proto.infra.backend.task.id.id = str(cur_id + 1)
    build_proto.id = cur_id + 1
    return ret

# pylint: disable=invalid-name
def RunSteps(
    api,
    full,
    task_type,
    max_attempts,
    last_task_max_attempts,
    run_count,
    abort_early,
    on_backend,
):
  task_types = {
      "test": Task,
      "flake_task": FlakeTask,
      "internal_failure": InternalFailureTask,
      "raising": RaisingTask,
      "led": LedTask,
      #"triggered": TriggeredTask,
  }

  _create_task = task_types[task_type]  # pylint: disable=invalid-name

  if full:
    tasks = [
        _create_task(api=api, name="pass", initial_task_id=100),
        _create_task(api=api, name="flake", initial_task_id=200),
        _create_task(api=api, name="fail", initial_task_id=300),
        _create_task(api=api, name="pass_long", initial_task_id=400),
        _create_task(api=api, name="flake_long", initial_task_id=500),
        _create_task(api=api, name="fail_long", initial_task_id=600),
    ]

  else:
    tasks = [_create_task(api=api, name="task", initial_task_id=100, on_backend=on_backend)]

  if abort_early:
    tasks.append(
        _create_task(
            api=api,
            name="abort_early_task",
            initial_task_id=700,
            abort_early=True,
        )
    )

  if last_task_max_attempts:
    tasks[-1].max_attempts = last_task_max_attempts

  api.swarming_retry.run_and_present_tasks(
      tasks, max_attempts=max_attempts, run_count=run_count
  )


def GenTests(api):  # pylint: disable=invalid-name
  test_api = api.swarming_retry

  def led_build_data(priority=100):
    build = api.buildbucket.ci_build_message(priority=priority, on_backend=True)

    job_def = job_pb2.Definition()
    job_def.buildbucket.bbagent_args.build.CopyFrom(build)
    return api.led.mock_get_builder(job_def)

  yield (
      api.test("full_test", status="FAILURE") + api.properties(full=True) +
      test_api.collect_data(
          [
              test_api.passed_task("pass", 100),
              test_api.failed_task("flake", 200),
              test_api.failed_task("fail", 300),
          ],
          iteration=0,
      ) + test_api.collect_data(
          [
              test_api.passed_task("flake", 201),
              test_api.failed_task("fail", 301)
          ],
          iteration=1,
      ) +
      # `fail` task failed max times so remaining long tasks should only be run
      # once.
      test_api.collect_data(
          [
              test_api.incomplete_task("pass_long", 400),
              test_api.incomplete_task("flake_long", 500),
              test_api.incomplete_task("fail_long", 600),
          ],
          iteration=2,
      ) + test_api.collect_data([], iteration=3) +
      test_api.collect_data([test_api.passed_task("pass_long", 400)],
                            iteration=4) +
      test_api.collect_data([test_api.failed_task("flake_long", 500)],
                            iteration=5) +
      test_api.collect_data([test_api.failed_task("fail_long", 600)],
                            iteration=6)
  )

  yield (
      api.test("timeout_then_pass") + api.properties(full=False) +
      test_api.collect_data([test_api.timed_out_task("task", 100)]) +
      test_api.collect_data([test_api.passed_task("task", 101)], iteration=1)
  )

  yield (
      api.test("internal_failure", status="FAILURE") +
      api.properties(full=False, task_type="internal_failure") +
      test_api.collect_data([test_api.passed_task("task", 100)], iteration=0) +
      test_api.collect_data([test_api.passed_task("task", 101)], iteration=1)
  )

  yield (
      api.test("raising_process_results", status="FAILURE") +
      api.properties(full=False, task_type="raising") +
      test_api.collect_data([test_api.passed_task("task", 100)], iteration=0) +
      test_api.collect_data([test_api.passed_task("task", 101)], iteration=1)
  )

  yield (
      api.test("led_task") + api.properties(full=False, task_type="led") +
      led_build_data() +
      test_api.collect_data([test_api.failed_task("task", 100)], iteration=0) +
      test_api.collect_data([test_api.passed_task("task", 101)], iteration=1)
  )

  yield (
      api.test("led_task_backend_false") + api.properties(full=False, task_type="led") +
      api.properties(on_backend=False) +
      test_api.collect_data([test_api.failed_task("task", 100)], iteration=0) +
      test_api.collect_data([test_api.passed_task("task", 101)], iteration=1)
  )

  yield (
      api.test("led_task_hardcoded_attempt") +
      api.properties(full=False, task_type="led") + led_build_data()
  )

  yield (
      api.test("max_attempts_three", status="FAILURE") +
      api.properties(full=False, task_type="raising", max_attempts=3) +
      test_api.collect_data([test_api.passed_task("task", 100)], iteration=0) +
      test_api.collect_data([test_api.passed_task("task", 101)], iteration=1) +
      test_api.collect_data([test_api.passed_task("task", 102)], iteration=2)
  )

  yield (
      api.test("last_task_max_attempts_low", status="FAILURE") + api.properties(
          full=False,
          task_type="raising",
          max_attempts=3,
          last_task_max_attempts=1
      ) +
      test_api.collect_data([test_api.passed_task("task", 100)], iteration=0)
  )

  yield (
      api.test("last_task_max_attempts_high", status="FAILURE") +
      api.properties(
          full=False,
          task_type="raising",
          max_attempts=3,
          last_task_max_attempts=5
      ) +
      test_api.collect_data([test_api.passed_task("task", 100)], iteration=0) +
      test_api.collect_data([test_api.passed_task("task", 101)], iteration=1) +
      test_api.collect_data([test_api.passed_task("task", 102)], iteration=2) +
      test_api.collect_data([test_api.passed_task("task", 103)], iteration=3) +
      test_api.collect_data([test_api.passed_task("task", 104)], iteration=4)
  )

  # Test case where we want to get multiple successful runs of the same
  # task (run_count > 1).

  # Test the simple case where there are no failures of the task.
  yield (
      api.test("multirun_without_failures", status="SUCCESS") +
      api.properties(run_count=2, task_type="led") +
      # Enforce that both of these task attempt are launched in the first
      # iteration.  (This requires using task_type="triggered".)
      #+ api.swarming_retry.trigger_data("task", 100, iteration=0, attempt=0) +
      #api.swarming_retry.trigger_data("task", 101, iteration=0, attempt=1) +
      test_api.collect_data([test_api.passed_task("task", 100)], iteration=0) +
      test_api.collect_data([test_api.passed_task("task", 101)], iteration=1)
  )

  # Test the case where a task must be retried (multiple times) but
  # eventually passes.
  yield (
      api.test("multirun_retry_overall_pass", status="SUCCESS") +
      api.properties(run_count=2, task_type="led") +
      test_api.collect_data([test_api.passed_task("task", 100)], iteration=0) +
      test_api.collect_data([test_api.failed_task("task", 101)], iteration=1) +
      test_api.collect_data([test_api.failed_task("task", 102)], iteration=2) +
      test_api.collect_data([test_api.passed_task("task", 103)], iteration=3)
  )

  # Test the case where a task is retried, but ultimately we do not get
  # enough passes within the max_attempts retry limit.
  yield (
      api.test("multirun_retry_overall_fail", status="FAILURE") +
      api.properties(run_count=2, task_type="led") +
      test_api.collect_data([test_api.passed_task("task", 100)], iteration=0) +
      test_api.collect_data([test_api.failed_task("task", 101)], iteration=1) +
      test_api.collect_data([test_api.failed_task("task", 102)], iteration=2) +
      test_api.collect_data([test_api.failed_task("task", 103)], iteration=3)
  )

  # If the last attempt in the list passed but the task failed overall,
  # it should not be treated as passed.
  #
  # Also, if the last attempt in the list completes before other attempts
  # have completed, the task should be treated as in-progress not
  # finished.
  yield (
      api.test("multirun_fail_pass", status="FAILURE") +
      api.properties(run_count=2, max_attempts=1, task_type="led") +
      test_api.collect_data([test_api.passed_task("task", 101)], iteration=0) +
      test_api.collect_data([test_api.failed_task("task", 100)], iteration=1)
  )

  # Test that the "no futile retries" strategy is applied: If all of the
  # attempts in the first batch fail, there should be no retries.
  yield (
      api.test("multirun_no_futile_retries", status="FAILURE") +
      api.properties(run_count=2, task_type="led") +
      test_api.collect_data([test_api.failed_task("task", 100)], iteration=0) +
      test_api.collect_data([test_api.failed_task("task", 101)], iteration=1)
  )

  yield (
      api.test("no_collect_after_failed_abort_early_task", status="FAILURE") +
      api.properties(full=True, abort_early=True, task_type="flake_task") +
      test_api.collect_data(
          [
              test_api.failed_task("abort_early_task", 700),
              test_api.passed_task("pass", 100),
              test_api.failed_task("flake", 200),
              test_api.failed_task("fail", 300),
          ],
          iteration=0,
      ) + test_api.collect_data(
          [test_api.failed_task("abort_early_task", 701)],
          iteration=1,
      )
  )

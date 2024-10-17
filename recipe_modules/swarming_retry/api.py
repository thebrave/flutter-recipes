# Copyright 2019 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Launch and retry swarming jobs until they pass or we hit max attempts."""

import itertools
from urllib.parse import urlparse

import attr
from recipe_engine import recipe_api
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from RECIPE_MODULES.fuchsia.utils import pluralize

DEFAULT_MAX_ATTEMPTS = 2


@attr.s
class Attempt:
  """References a specific attempt of a task."""

  task_id = attr.ib(type=str)
  index = attr.ib(type=int, default=None)  # Number of prior attempts.
  host = attr.ib(type=str, default=None)
  task_ui_link = attr.ib(type=str, default=None)
  result = attr.ib(default=None)
  # This attribute should be set by overrides of Task.process_result(). It
  # indicates that even though at the swarming level the task may have
  # passed something failed inside that larger task.
  failure_reason = attr.ib(type=str, default="")
  has_flakes = attr.ib(type=bool, default=False)
  task_outputs_link = attr.ib(type=str, default=None)
  logs = attr.ib(type=dict, default=attr.Factory(dict))

  def __attrs_post_init__(self):
    # The led module gives the host and the id, but the swarming module
    # gives the link and the id. Require the id (since it has no default
    # above) and require either the host or task_ui_link attributes.
    assert self.host or self.task_ui_link

  @property
  def name(self):
    return f"attempt {int(self.index)}"

  @property
  def success(self):
    if self.failure_reason:
      return False

    if not self.result:  # pragma: nocover
      return False

    return self.result.status == common_pb2.Status.SUCCESS


class TaskTracker:
  """TaskTracker tracks state about attempts to run a task.

    TaskTracker runs the task until we get run_count successes. Usually
    run_count is 1, for running regular tests, but run_count may be >1 when
    gathering results of performance tests.
    """

  # States returned by _get_state()
  _LAUNCH_MORE = "launch_more"
  _IN_PROGRESS = "in_progress"
  _OVERALL_SUCCESS = "overall_success"
  _OVERALL_FAILURE = "overall_failure"

  def __init__(self, api, task, run_count):
    """
        Args:
          api: recipe_api.RecipeApiPlain object.
          task: Task object.
          run_count: number of successful runs we want to get for the task.
        """
    self._api = api
    self._task = task
    self._attempts = []
    self._in_progress_attempts = []
    self._successes_required = run_count
    self._successes_got = 0
    self._failures_got = 0
    self._flakes_got = 0

  @property
  def name(self):
    return self._task.name

  @property
  def abort_early_if_failed(self):
    return self._task.abort_early_if_failed

  # Returns a pair (state, number_to_launch), where number_to_launch
  # is the number of new task attempts to be launched.
  def _get_state(self):
    if len(self._in_progress_attempts) != 0:
      return self._IN_PROGRESS, 0

    if self._successes_got >= self._successes_required:
      return self._OVERALL_SUCCESS, 0
    # We treat the max_attempts parameter as a multiplier, basically
    # "max attempts per successful run needed", so that the same
    # max_attempts value can be used for both perfcompare and regular
    # builders.
    attempts_allowed = self._task.max_attempts * self._successes_required
    remaining_needed = self._successes_required - self._successes_got
    remaining_allowed = attempts_allowed - len(self._attempts)
    if remaining_needed > remaining_allowed:
      return self._OVERALL_FAILURE, 0
    # Apply the "no futile retries" strategy: If we need multiple
    # successful runs but we see no successes in the first batch of
    # attempts, don't do any retries, on the grounds that the build
    # we're testing is probably bad (i.e. it won't pass if retried).
    # This is intended to avoid wasting time and infra capacity.
    if (self._successes_required > 1 and self._successes_got == 0 and
        len(self._attempts) >= self._successes_required):
      return self._OVERALL_FAILURE, 0
    return self._LAUNCH_MORE, remaining_needed

  def should_launch(self):
    _, number_to_launch = self._get_state()
    return number_to_launch > 0

  # Launch one or more task attempts.  This assumes that should_launch()
  # was previously called and returned True.
  def launch(self):
    state, number_to_launch = self._get_state()
    assert state == self._LAUNCH_MORE, state
    assert number_to_launch > 0

    # Don't increase the priority if we need multiple successful runs (used
    # for perfcompare mode).
    if self._successes_required > 1:
      priority_boost_amount = 0
    else:
      # Boost the priority by the number of previous attempts.  This means
      # that second attempts will take priority over first attempts, third
      # attempts will take priority over second attempts, etc.
      #
      # This means that if there is a long queue for Swarming tasks to run,
      # only the first attempts should wait.  Subsequent attempts should
      # jump ahead in the queue.
      priority_boost_amount = len(self._attempts)

    task_ids = []
    for _ in range(number_to_launch):
      attempt_index = len(self._attempts)
      task_name = f"{self.name} (attempt {int(attempt_index)})"
      with self._api.step.nest(task_name) as presentation:
        attempt = self._task.launch(priority_boost_amount)
        attempt.index = attempt_index
        self._attempts.append(attempt)
        self._in_progress_attempts.append(attempt)
        task_ids.append(attempt.task_id)
        presentation.links["Swarming task"] = attempt.task_ui_link
    return task_ids

  @property
  def attempts(self):  # pragma: no cover
    return self._attempts[:]

  @property
  def in_progress(self):
    state, _ = self._get_state()
    return state == self._IN_PROGRESS

  @property
  def success(self):
    state, _ = self._get_state()
    return state == self._OVERALL_SUCCESS

  @property
  def failed(self):
    return not self.success and not self.in_progress

  def failed_after_max_attempts(self):
    state, _ = self._get_state()
    return state == self._OVERALL_FAILURE

  def has_flakes(self):
    return self._flakes_got > 0 or (
        self._successes_got > 0 and self._failures_got > 0
    )

  def process_result(self, attempt, result):
    # TODO(fujino): ensure this is never empty, https://crbug.com/369586985
    with self._api.step.nest(result.builder.builder):
      self._in_progress_attempts.remove(attempt)
      attempt.result = result
      try:
        self._task.process_result(attempt)
      except recipe_api.StepFailure as e:
        error_step = self._api.step.empty("exception")
        error_step.presentation.step_summary_text = str(e)
        attempt.failure_reason = "exception during result processing"
        if e.name and e.exc_result:
          # The error name generally contains the name of the step
          # that failed. The full step name will already be namespaced
          # by task name, so present everything after the task name
          # since the failure_reason will only be presented in the
          # context of this task.
          attempt.failure_reason += f": {e.name.split(self.name + '.')[-1]} (retcode {e.exc_result.retcode})"
        trace_lines = self._api.utils.traceback_format_exc().splitlines()
        attempt.logs["exception"] = trace_lines
        error_step.presentation.logs["exception"] = trace_lines
      if attempt.success:
        self._successes_got += 1
        if attempt.has_flakes:
          self._flakes_got += 1
      else:
        self._failures_got += 1

  def present(self, **kwargs):
    """Present this task when summarizing results at the end of the run.

        Args:
          **kwargs (Dict): passed through to present_attempt()

        Returns:
          None
        """
    with self._api.step.nest(self.name) as task_step_presentation:
      for attempt in self._attempts:
        self._task.present_attempt(task_step_presentation, attempt, **kwargs)

      # Show incomplete tasks in green so as not to be confused with
      # actual failures.
      if self.success or self.in_progress:
        task_step_presentation.status = self._api.step.SUCCESS
      else:
        task_step_presentation.status = self._api.step.FAILURE


class Task:
  """A Task object describes:

     * How to launch a task.
     * How to process and present the results from a task.

    This class is meant to be subclassed. Subclasses must define a launch()
    method.

    In most cases Task.max_attempts should be left alone. If the caller wants
    to ensure a task has a larger or smaller number of max attempts than the
    default for other tasks, set max_attempts to that number.
    """

  def __init__(self, api, name):
    """Initializer.

        Args:
          api: recipe_api.RecipeApiPlain object.
          name: str, human readable name of this task
        """
    self._api = api
    self.name = name
    self.max_attempts = None
    self.abort_early_if_failed = False

  def process_result(self, attempt):
    """Examine the result in the given attempt for failures.

        Subclasses can set attempt.failure_reason if they find a failure inside
        attempt.result. failure_reason should be a short summary of the failure
        (< 50 chars).

        This is invoked shortly after api.swarming.collect() returns that a
        task completed. It cannot assume the swarming task completed
        successfully.

        This is a no-op here but can be overridden by subclasses.

        Returns:
          None
        """

  def present_attempt(self, task_step_presentation, attempt, **kwargs):
    """Present an Attempt when summarizing results at the end of the run.

        Args:
          task_step_presentation (StepPresentation): assuming present() was not
            overridden, this will always be for a step titled after the current
            task
          attempt (Attempt): the Attempt to present
          **kwargs (Dict): pass-through arguments for subclasses

        This method will be invoked to show details of an Attempt. This base
        class method just creates a link to the swarming results from the task,
        but subclasses are free to create a step with much more elaborate
        details of results.

        Returns:
          None
        """
    del kwargs  # Unused.
    name = f"{attempt.name} ({'pass' if attempt.success else 'fail'})"
    task_step_presentation.links[name] = attempt.task_ui_link

  def launch(self, priority_boost_amount):
    """Launch the task (using Swarming, led, or something else).

        Args:
          priority_boost_amount (int): Non-negative integer specifying how much
            the priority of the task should be increased from the default.

        Returns:
          Attempt object, with the task_id or host property filled out from
          from the Swarming or led result.
        """
    assert False, "Subclasses must define launch() method."  # pragma: no cover


class LedTask(Task):

  def __init__(self, led_data, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._led_data = led_data

    build = led_data.result.buildbucket.bbagent_args.build

    self._backend_config = build.infra.backend.config
    self._original_priority = self._backend_config['priority']

  def launch(self, priority_boost_amount):
    assert self._led_data

    # For Swarming tasks, numerically lower priority values are logically
    # higher priorities, so use subtraction here.
    new_priority = self._original_priority - priority_boost_amount
    # Although we modify this data structure in place, one launch()
    # invocation should not affect later launch() invocations because this
    # 'priority' field is always overwritten.
    self._backend_config['priority'] = new_priority
    if priority_boost_amount != 0:
      with self._api.step.nest("increase priority") as pres:
        pres.step_summary_text = (
            f"from {int(self._original_priority)} to {int(new_priority)}"
        )

    res = self._led_data.then("launch", "-real-build")
    host = res.launch_result.buildbucket_hostname
    task_id = str(res.launch_result.build_id)
    build_url = res.launch_result.build_url
    return self._api.swarming_retry.Attempt(
        host=host,
        task_id=task_id,
        # Use Milo since this task is running a recipe.
        task_ui_link=build_url,
    )


class RetrySwarmingApi(recipe_api.RecipeApi):
  """Launch and retry swarming jobs until they pass or we hit max attempts."""

  Task = Task  # pylint: disable=invalid-name
  LedTask = LedTask  # pylint: disable=invalid-name
  Attempt = Attempt  # pylint: disable=invalid-name

  DEFAULT_MAX_ATTEMPTS = DEFAULT_MAX_ATTEMPTS

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._task_ids_seen = set()

  def run_and_present_tasks(self, tasks, **kwargs):
    tasks = self.run_tasks(tasks, **kwargs)
    self.present_tasks(tasks)
    self.raise_failures(tasks)

  def _is_complete(self, result):
    return result.status not in {
        common_pb2.Status.STATUS_UNSPECIFIED,
        common_pb2.Status.SCHEDULED,
        common_pb2.Status.STARTED,
    }

  def _get_tasks_to_launch(self, tasks):
    if any(task.failed_after_max_attempts() for task in tasks):
      # The build has failed overall, so disable launching any
      # further task attempts.
      return []
    return [task for task in tasks if task.should_launch()]

  def _launch(self, tasks):
    for task in tasks:
      task_ids = task.launch()
      # Check whether we got any duplicate task IDs.  This is just a
      # rationality check for testing.  With the current testing
      # framework, it is easy for multiple launch attempts to return
      # the same ID, because the default testing output always
      # returns the same task ID value.
      for task_id in task_ids:
        assert (
            task_id not in self._task_ids_seen
        ), f"Duplicate task ID seen: {repr(task_id)}"
        self._task_ids_seen.add(task_id)

  def _launch_and_collect(
      self, tasks, collect_output_dir, summary_presentation
  ):
    """Launch necessary tasks and process those that complete.

        Launch any tasks that are not currently running, have not passed,
        and have not exceeded max_attempts.

        After launching tasks, wait for the first task to complete (of the tasks
        just launched as well as those that have been running for awhile).
        Summarize the jobs that have just passed or failed as well as those still
        running (with swarming links).

        This function is mostly stateless. The caller must pass in the
        same arguments for each invocation, and state is kept inside the
        tasks themselves.

        Args:
          tasks (list[Task]): tasks to execute
          collect_output_dir (Path or None): output directory to pass to
            api.swarming.collect()
          summary_presentation (StepPresentation): where to attach the
            summary for this round of launch/collect.

        Returns:
          Number of jobs still running or to be relaunched. As long as this
          is positive the caller should continue calling this method.
        """
    summary = []

    def summary_entry(list_name, task_list):
      if len(task_list) == 1:
        count_or_name = task_list[0].name
      else:
        count_or_name = len(task_list)
      return f"{count_or_name} {list_name}"

    to_launch = self._get_tasks_to_launch(tasks)
    if to_launch:
      with self.m.step.nest("launch"):
        self._launch(to_launch)

    # Wait on tasks that are in-progress.
    tasks_by_id = {}
    for task in tasks:
      for attempt in task._in_progress_attempts:
        assert attempt.task_id not in tasks_by_id
        tasks_by_id[attempt.task_id] = (task, attempt)
    results = {}
    if tasks_by_id:
      results = self.m.buildbucket.collect_builds(
          sorted([int(build_id) for build_id in tasks_by_id]),
          mirror_status=False
      )
    # 'collect' takes a list of build IDs and returns a list specifying
    # whether each task has completed or is still running.  However,
    # sometimes the list it returns misses tasks that haven't
    # completed.  That makes no difference here because we only look at
    # the completed tasks.
    completed_results = list(filter(self._is_complete, results.values()))
    passed_tasks = []
    failed_tasks = []
    if completed_results:
      with self.m.step.nest("process results") as process_results_presentation:
        for result in completed_results:
          task, attempt = tasks_by_id[str(result.id)]
          task.process_result(attempt, result)
          if attempt.success:
            passed_tasks.append((task, attempt))
          else:
            failed_tasks.append((task, attempt))

        # Prevent failure states from the child log steps being
        # propagated up the log step tree by the recipe log step
        # system.  This is desirable because although
        # task.process_result() may internally catch and suppress
        # an exception, the exception will still be reported
        # through recipe log step system.
        process_results_presentation.status = self.m.step.SUCCESS

    for list_name, task_list in [
        ("passed", passed_tasks),
        ("failed", failed_tasks),
    ]:
      if not task_list:
        continue
      links = []
      for task, attempt in task_list:
        name = f"{task.name} ({attempt.name})"
        links.append((name, attempt.task_ui_link))
      with self.m.step.nest(f"{list_name} tasks") as list_step_presentation:
        list_step_presentation.links.update(links)

      summary.append(summary_entry(list_name, [task for task, _ in task_list]))

    incomplete_tasks = [task for task in tasks if task.in_progress]
    # Do minimal presentation of all in-progress Attempts.
    links = []
    for task in tasks:
      for attempt in task._in_progress_attempts:
        name = f"{task.name} ({attempt.name})"
        links.append((name, attempt.task_ui_link))
    if links:
      with self.m.step.nest("incomplete tasks") as list_step_presentation:
        list_step_presentation.links.update(links)
      summary.append(summary_entry("incomplete", incomplete_tasks))

    to_be_relaunched = self._get_tasks_to_launch(tasks)
    failed_after_max_attempts = [
        task for task in tasks if task.failed_after_max_attempts()
    ]
    if failed_after_max_attempts:
      summary.append(
          summary_entry("failed after max attempts", failed_after_max_attempts)
      )

    summary_presentation.step_summary_text = ", ".join(summary)

    # Check if all abort_early_if_failed tasks are finished. If one or more
    # fail, don't wait on remaining tasks. They will be automatically
    # forcibly terminated when the build's Swarming task completes.
    abort_early_tasks = [task for task in tasks if task.abort_early_if_failed]
    abort_early_tasks_in_progress = [
        task for task in abort_early_tasks if task.in_progress
    ]
    if not abort_early_tasks_in_progress:
      failed_abort_early_tasks = [
          task for task in abort_early_tasks if task.failed_after_max_attempts()
      ]
      if failed_abort_early_tasks:
        return 0

    return len(to_be_relaunched) + len(incomplete_tasks)

  def run_tasks(
      self,
      tasks,
      max_attempts=0,
      collect_output_dir=None,
      run_count=1,
  ):
    """Launch all tasks, retry until max_attempts reached.

        Args:
          tasks (seq[Task]): tasks to execute
          max_attempts (int): maximum number of attempts per task (0 means
            DEFAULT_MAX_ATTEMPTS)
          collect_output_dir (Path or None): output directory to pass to
            api.swarming.collect()
        """

    max_attempts = max_attempts or DEFAULT_MAX_ATTEMPTS

    for task in tasks:
      if not task.max_attempts:
        task.max_attempts = max_attempts

    tasks = [TaskTracker(self.m, task, run_count) for task in tasks]

    with self.m.step.nest("launch/collect"), self.m.context(infra_steps=True):
      for i in itertools.count(0):
        with self.m.step.nest(str(i)) as presentation:
          if not self._launch_and_collect(
              tasks=tasks,
              collect_output_dir=collect_output_dir,
              summary_presentation=presentation,
          ):
            break

    return tasks

  def present_tasks(self, tasks):
    """Present results as steps.

        Examine tasks for pass/fail status and create step data for displaying
        that status. Group all passes under one step and all failures under
        another step. Passes that failed at least once are also listed as
        flakes.

        Args:
          tasks (seq[Task]): tasks to examine
        """
    # TODO(mohrr) add hooks to include task-specific data beyond pass/fail.
    passed_tasks = [x for x in tasks if x.success]
    # Some tasks may be incomplete if the launch_and_collect loop exited
    # early due to failures.
    incomplete_tasks = [x for x in tasks if x.in_progress]
    failed_tasks = [x for x in tasks if x.failed]
    flaked_tasks = [x for x in tasks if x.has_flakes()]

    with self.m.step.nest("passes") as step_presentation:
      for task in passed_tasks:
        task.present(category="passes")
      step_presentation.step_summary_text = f"{len(passed_tasks)} passed"

    with self.m.step.nest("flakes") as step_presentation:
      for task in flaked_tasks:
        task.present(category="flakes")
      step_presentation.step_summary_text = f"{len(flaked_tasks)} flaked"

    with self.m.step.nest("failures") as step_presentation:
      for task in failed_tasks:
        task.present(category="failures")
      step_presentation.step_summary_text = f"{len(failed_tasks)} failed"

    if incomplete_tasks:
      with self.m.step.nest("incomplete") as step_presentation:
        for task in incomplete_tasks:
          task.present(category="incomplete")
        step_presentation.step_summary_text = (
            f"{len(incomplete_tasks)} incomplete"
        )

    if not failed_tasks and not incomplete_tasks:
      self.m.step.empty("all tasks passed")  # pragma: no cover

  def raise_failures(self, tasks):
    """Raise an exception if any tasks failed.

        Examine tasks for pass/fail status. If any failed, raise a StepFailure.

        Args:
          tasks (seq[Task]): tasks to examine
        """
    failed = [x for x in tasks if x.failed]
    if failed:
      raise self.m.step.StepFailure(
          f"{pluralize('task', failed)} failed: {', '.join(x.name for x in failed)}"
      )

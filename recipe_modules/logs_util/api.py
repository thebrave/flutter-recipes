# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re
from recipe_engine import recipe_api


class LogUtilsApi(recipe_api.RecipeApi):
  """Utilities to collect logs in a generic way."""

  def initialize_logs_collection(self, env):
    """Initializes log processing.

    The initialization process creates a temp directory and adds it to the
    FLUTTER_LOGS_DIR env variable to make it available to the task steps. Task
    steps can place any files they want to upload to GCS as public logs.

    Args:
      env(dict): Env variables dictionary.
    """
    # Create a temp folder to keep logs until we can upload them to gcs
    # at the end of the execution of the test.
    with self.m.step.nest('Initialize logs'):
      logs_path = self.m.path['cleanup'].join('flutter_logs_dir')
      self.m.file.ensure_directory('Ensure %s' % logs_path, logs_path)
      env['FLUTTER_LOGS_DIR'] = logs_path
      # Ensure that any test outputs, e.g. timelines/timeline summaries are
      # included as logs.
      env['FLUTTER_TEST_OUTPUTS_DIR'] = logs_path
      # Write a noop file to force the creation of the remote folder structure
      # when the logs folder is empty.
      self.m.file.write_text(
          'Write noop file', logs_path.join('noop.txt'), '', include_log=False
      )

  def upload_logs(self, task, type='flutter'):
    """Upload the log files in FLUTTER_LOGS_DIR to GCS.

    Args:
      task(str): A string with the task name the logs belong to.
    """
    git_hash = self.m.buildbucket.gitiles_commit.id
    # gitiles_commit is only populated on post-submits.
    # UUID is used in LED and try jobs.
    uuid = self.m.uuid.random()
    invocation_id = git_hash if git_hash else uuid
    logs_path = self.m.path['cleanup'].join('flutter_logs_dir')
    with self.m.step.nest('process logs'):
      self.m.gsutil.upload(
          bucket='flutter_logs',
          source=logs_path,
          dest='%s/%s/%s/%s' % (type, invocation_id, task, uuid),
          link_name='archive logs',
          args=['-r'],
          multithreaded=True,
          name='upload logs %s' % invocation_id,
          unauthenticated_url=True
      )
      log_files = self.m.file.glob_paths(
          'logs', source=logs_path, pattern='*', test_data=['a.txt']
      )
    with self.m.step.nest('log links') as presentation:
      pattern_str = 'https://storage.googleapis.com/%s/%s/%s/%s/%s/%s'
      log_files = self.m.file.listdir(
          'List logs path', logs_path, True, test_data=('myfile.txt',)
      )
      for log_file in log_files:
        base_name = self.m.path.basename(log_file)

        url = pattern_str % (
            'flutter_logs', type, invocation_id, task, uuid, base_name
        )
        presentation.links[base_name] = url

  def upload_test_metrics(self, file_path, task_name, git_hash=None):
    """Retrieve the file from the provided path and store it in gcs.

    Upload test metrics only on post-submit. These are metrics about unit test execution time,
    and they will be used to shard tests evenly according to their overall execution time.
    """
    with self.m.step.nest('store metrics'):
      git_hash = self.m.buildbucket.gitiles_commit.id if not git_hash else git_hash
      if not git_hash or not self.m.path.exists(file_path):
        return
      uuid = self.m.uuid.random()
      self.m.gsutil.upload(
          bucket='flutter_logs',
          source=file_path,
          dest='flutter/%s/%s/%s' % (git_hash, task_name, uuid),
          link_name='archive logs',
          args=['-r'],
          multithreaded=True,
          name='upload logs %s' % git_hash,
          unauthenticated_url=True
      )

  def show_logs_stdout(self, file_path):
    """Outputs to sdout the connect of file_path

    :param file_path: str
    :return: 
    """
    if self.m.path.exists(file_path):
      self.m.file.read_text('Read log file', file_path)

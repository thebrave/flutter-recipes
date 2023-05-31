# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class PubSubApi(recipe_api.RecipeApi):

  def publish_message(
      self, topic, message, step_name='Publish message to pubsub'
  ):
    """Publish a message to a pubsub topic

    Args:
      topic(str): gcloud topic to publish the message to.
      message(str): the message to publish to pubsub.
      step_name(str): an optional custom step name.
    """
    with self.m.step.nest(step_name):
      cmd = ['pubsub', 'topics', 'publish', topic, '--message=\'%s\'' % message]
      self.m.gcloud(*cmd, infra_step=True)

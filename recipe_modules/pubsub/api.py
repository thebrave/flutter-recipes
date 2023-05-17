# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class PubSubApi(recipe_api.RecipeApi):

  def publish_message(self, topic, message):
    """Publish a message to a pubsub topic

    Args:
      topic(str): gcloud topic to publish the message to.
      message(str): the message to publish to pubsub.
    """
    with self.m.step.nest('Publish message to pubsub'):
      cmd = ['pubsub', 'topics', 'publish', topic, '--message=\'%s\'' % message]
      self.m.gcloud(*cmd, infra_step=True)

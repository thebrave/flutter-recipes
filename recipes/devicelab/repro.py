from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/step',
    'recipe_engine/time',
]

def RunSteps(api):
  for i in range(1000):
    api.step(
        'curl',
        ['curl', 'http://storage.googleapis.com/flutter_infra_release/flutter/398bede5b914736c07366bccc60a083a2bb8067c/dart-sdk-linux-x64.zip', '--output', 'myfile.zip'],
    )

    api.time.sleep(60)



def GenTests(api):
  yield api.test(
      "basic",
  )

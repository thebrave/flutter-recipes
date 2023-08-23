# Flutter LUCI Recipes

This repository contains Flutter's LUCI recipes. For the LUCI infrastructure
config, see [flutter/infra](https://flutter.googlesource.com/infra). Builds can
be found in the [Flutter Dashboard](https://flutter-dashboard.appspot.com/).

Supported repositories roll their `.ci.yaml` into flutter/infra, which updates
what properties builds have. For example, [flutter](https://github.com/flutter/flutter/blob/master/.ci.yaml)
config specifies various dependencies the different tests require, which are
then used by the [flutter_deps recipe_module](https://cs.opensource.google/flutter/recipes/+/master:recipe_modules/flutter_deps/api.py)
No modifications to flutter/infra are required to work on the recipes.

## Configuration

## Contributing

Please follow instructions on [Contributing docs](CONTRIBUTING.md) to setup your development environment.

## Testing locally

Running `python3 recipes.py test train` will execute all of the tests in this repository

## Troubleshooting

### "Required binary is not found on PATH: cipd" when testing locally

You need to ensure [depot_tools](https://chromium.googlesource.com/chromium/tools/depot_tools.git) is installed.
See the [Depot Tools Installation Tutorial](https://commondatastorage.googleapis.com/chrome-infra-docs/flat/depot_tools/docs/html/depot_tools_tutorial.html#_setting_up).

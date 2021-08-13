# Flutter LUCI Recipes

This repository contains Flutter's LUCI recipes. For the LUCI infrastructure
config, see [flutter/infra](https://flutter.googlesource.com/infra). Actual
builds can be seen at [ci.chromium.org](https://ci.chromium.org/p/flutter).

Supported repositories roll their `.ci.yaml` into flutter/infra, which updates
what properties builds have. For example, [flutter](https://github.com/flutter/flutter/blob/master/.ci.yaml)
config specifies various dependencies the different tests require, which are
then used by the [flutter_deps
recipe_module](https://cs.opensource.google/flutter/recipes/+/master:recipe_modules/flutter_deps/api.py)
No modifications to flutter/infra are required to work on the recipes.

## Configuration

[Tricium](https://chromium.googlesource.com/infra/infra/+/master/go/src/infra/tricium/README.md) configurations recipes repo.

## Recipe Branching for Releases

The script `branch_recipes.py` is used to generate new copies of the LUCI
recipes for a beta release. See [Recipe Branching for Releases](https://github.com/flutter/flutter/wiki/Recipe-Branching-for-Releases)
for more information. For usage:

```
$ ./branch_recipes.py --help
```

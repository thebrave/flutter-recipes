## SUMMARY

Engine V2 recipes were conceived as a way to speed up engine builds by sharding them into
multiple sub-builds. That initial idea has evolved into a generic solution that speeds up
builds, improve reusability, simplify the build workflows, improve presubmit testing of
new artifacts and in general improves visibility of what the build system is generating.

**Author**: Godofredo Contreras (godofredoc)
**Created:** 02/2023   /  **Last updated**: 08/2023

## BACKGROUND

[Recipes](https://github.com/luci/recipes-py) is a domain specific language to describe
sequences of steps in a cross-platform and testable way. The chromium team has created
multiple modules that simplify the communication with LUCI which are the services used
by Flutter to build and test.

There are a few reasons why the use of recipes is very complicated in the Flutter
Infrastructure but the most important one is that we are putting too much business logic
in a place designed to orchestrate tasks in multiple platforms emphasizing scalability
over simplicity.

This document outlines the design of generic recipes that will rarely change. It will
explain in detail how the business logic will be moved to the engine repository and how
these recipes will be used as a foundational block to implement build dependency graphs
and optimize build and test executions.

## Audience

Flutter contributors adding new features to Engine V2 recipes and improving the Build
Configuration Language.

## Glossary

* **Build properties** - Key value pairs passed from the build configurations to the LUCI
  services and recipes.
* **Code signing** - The process of signing binaries with Flutter Certificates and notarizing
  the binaries with Apple services.
* **Logical monorepo** - Multiple repositories checked out in a predetermined structure that
  simplifies developing, building and testing by providing an integrated view of multiple
  independent repositories.
* **[.ci.yaml](https://cs.opensource.google/flutter/engine/+/main:.ci.yaml)** - Per repository
  file that defines a target per build to be executed in the LUCI services.
* **LUCI** - A replacement for Buildbot that runs primarily on the Google Cloud Platform and is
  designed to scale well for large projects.
* **BuildBucket** - A generic build queue. A build requester can schedule a build and wait for
  a result. A building system, such as Swarming, can lease it, build it and report a result back.
* **Led** - An infrastructure tool used to manually trigger builds on any builder running on
  LUCI. It‘s designed to help debug build failures or experiment with new builder changes.

## OVERVIEW

Engine V2 recipes implementation uses three recipes:
[engine\_v2/engine\_v2.py](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipes/engine_v2/engine_v2.py) (orchestrator),[engine\_v2/builder.py](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipes/engine_v2/builder.py) (builder), [engine\_v2/tester.py](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipes/engine_v2/tester.py) (tester) and several recipe modules: [shard\_util\_v2](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipe_modules/shard_util/api.py),  [archives](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipe_modules/archives/api.py), and [flutter\_deps](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipe_modules/flutter_deps/api.py).

The recipes and modules are highly customizable through a build configuration file making it
possible to create a completely new build without modifying a single line of code in the recipes
repository.

Engine V2 recipes are designed to automatically shard sub-builds with the possibility of mixing
and matching platforms. It is possible to build an artifact in a Linux machine (e.g. Javascript tests)
and use it in sub-builds targeting different platforms. Furthermore the orchestrator is designed as an
intermediate step to support dependency graphs, reusability of builds and to make efficient use of
resources.

Code signing is not only getting automated but it is also getting a major revamp to simplify the entire
process separating responsibilities (build/test/archive separation).

Security is another major benefit of Engine V2 recipes allowing release candidate branch artifacts to
be built in SLSA compliant infrastructure reusing the same recipes and build configurations.

Engine V2 recipes are opening the possibility to share infrastructure between Dart and Flutter with
minimal effort setting the groundwork for building a logical monorepo where changes in dart, engine,
flutter, packages, etc can be built and tested as a single unit.

## USAGE EXAMPLES

Engine V2 recipes will be used in conjunction with the [Engine Build Definition Language](flutter.dev/go/engine-build-definition-language) and [GN+Ninja Artifacts](flutter.dev/go/gn-ninja-engine-artifacts)
to optimize, simplify and speed up the Flutter Engine Builds.

A build configuration file will be created in flutter/engine describing a build, a target referencing
the configuration will be added to .ci.yaml. The Cocoon Backend will use them to trigger builds in
LUCI infrastructure.

A second use case will reuse the build configuration files and .ci.yaml to trigger builds in SLSA
compliant builders using a recipes orchestrator.

## Detailed design

### Build configuration files

Build configuration files describe the build components. Detailed information can be found
[here](http://flutter.dev/go/engine-build-definition-language). These configurations are used
by engine\_v2.py to shard builds, wait for their completion and run any post-build tasks that
require inputs from multiple sub-builds.

### .ci.yaml target

.ci.yaml is a per repository file used to instruct the LUCI infrastructure what to run, which
environments to use, and the platform configurations to run the builds on. Documentation for
.ci.yaml can be found [here](https://github.com/flutter/cocoon/blob/main/CI_YAML.md). For
the purpose of this document the engine [.ci.yaml](https://cs.opensource.google/flutter/engine/+/main:.ci.yaml)
file will be used.

Engine V2 build configuration is very simple, the following is an example:

```yaml
  - name: Mac mac_android_aot_engine
    recipe: engine_v2/engine_v2
    timeout: 60
    properties:
      config_name: mac_android_aot_engine
      $flutter/osx_sdk : >-
        { "sdk_version": "14a5294e" }
```

Where **name** is the title in the task in the [flutter-dashboard](https://flutter-dashboard.appspot.com/#/build),
recipe is the [engine v2 orchestrator recipe](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipes/engine_v2/engine_v2.py), **timeout** represents for how many minutes the build is allowed to run before timing out
and **properties** is a list of key/value pairs with additional information to be passed to the build.

### Engine V2 Recipes

This is a group of recipes collaborating to run builds/tests efficiently using the available resources.
This group currently includes: [engine\_v2](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipes/engine_v2/engine_v2.py)(orchestrator),
 [builder](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipes/engine_v2/builder.py),
 [tester](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipes/engine_v2/tester.py) and
  [signer](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipes/engine_v2/signer.py).

The following are the design principles for these recipes:

* **Small** - its core functionality is implemented in < 100 lines. Note this does not  count tests
  and top level documentation.
* **100% coverage** - this is required by the recipes engine.
* **Reusability** - Anything that can be reused is implemented in a single place using modules.
* **Improvements shared with legacy recipes** - Utilities created for V2 recipes can be used with legacy recipes.
* **Incremental rollout** - Transition from legacy recipes to v2 can be executed as small incremental steps.
* **Fast builds** - Builds using V2 must be faster than legacy builders.
* **Time bounded execution time** - Adding new configurations to a build must not increase the build time
  unless the new build unit is slower than any of the existing build units.
* **Reusable** - Builds using V2 recipes must be reusable by Dart and Flutter.
* **Low touch** - V2 recipes are low touch with less and less changes required as they stabilize in production.

#### Orchestrator

Entry point recipe which reads the build configuration file, triggers multiple sub-builds, waits for builds
to complete, runs global generators and signs the generated artifacts.

There is room for optimization like running global generators as soon as their dependencies are built,
 using low resource machines as orchestrators. These optimizations were intentionally left out as a
build graph scheduler will be implemented as soon as the migration to engine build v2 is completed.

#### Builder

This is a recipe that knows how to run GN|Ninja commands and how to run scripts in different languages.

It receives a build configuration with instructions of which gn and ninja commands to run and the tests
to run on the outputs of build.

#### Tester

This recipe knows how to run scripts(tests) using the outputs of a sub-build. An usage example of this
functionality is Web Engine builds Javascript tests and then triggers several tester sub-builds in
 different platforms.

This may not seem like a huge improvement over the status quo but it really is. It removes all the overhead
of setting up the build environment, e.g. third\_party dependencies, xcode, android sdk, etc.

Using the tester sub-builds efficiently requires foundational changes where the build system prepares
everything required to run the tests in a way that the tester only needs to know how to download the
sub-build artifacts, run it and provide a pass|fail signal. In other words, global tests become self
contained artifacts that include everything needed to run.

**Note:** Requiring checkouts of the source code, files in certain locations etc. removes most of the
benefits of separating build/tests/archives.

#### Sharding

Builds and global tests are automatically sharded by the orchestrator, injecting dependencies described
in the build configuration file to builder|tester tasks.

### Release Builder

Dart & Flutter have been investing heavily in SLSA compliant workflows. SLSA requires secure
infrastructure where human intervention is minimal with multi party approval.

Engine v2 builds provide the foundational work required to run the builds in different
environments using the same configurations, additional logging, audit trails and multi-party
approval. All of this without impacting the velocity of the development workflows.

[Release builder](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipes/release/release_builder.py)
is implemented with <50 lines of code. It takes .ci.yaml and the build configurations to produce SLSA compliant
artifacts for release candidate branches.

### Recipe modules

There is functionality that can be reused across multiple recipes. One example is engine\_v2 and
release\_builder recipes triggering sub-builds or code to set up the engine build environment.
One of the reasons we were able to implement release\_builder with minimal lines of code is because
it is reusing functionality already implemented. Structuring functionality as recipe\_modules help us
to implement fixes in a single place and apply to all the recipes. Although there are many modules,
 only the three most important ones are covered in this document: shard\_util\_v2, archives, and display\_util.

#### [Shard\_util\_v2](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipe_modules/shard_util/api.py)

This module provides the core functionality supporting Engine V2 Builds. It understands the build configuration
language files and helps trigger multiple sub-builds based on those configurations. It also supports automated
executions of builds using BuildBucket or manual execution using Led.

#### [Archives](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipe_modules/archives/api.py)

This module provides generic functionality to archive artifacts using different environments.

#### [Display\_util](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipe_modules/display_util/api.py)

This module provides functionality to display builds in a human readable format. It encapsulates all the
functionality to display sub-builds in a single place. This simplifies improving user interface changes
and rolling it to all the flutter infrastructure at once.

### INTEGRATION WITH EXISTING FEATURES

The recipe modules will be reused in both legacy and engine v2 recipes and the builds using the two
versions of recipes will coexist for some time.

All the work described in this document will integrate with no additional effort with .ci.yaml and
with the cocoon scheduler for the development workflows.

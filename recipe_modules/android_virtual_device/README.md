# Understanding Android virtual device in recipes.

AVD is how Flutter launches emulators as defined by CIPD.

* The dependency can be found in https://chrome-infra-packages.appspot.com/p/chromium/tools/android/avd/linux-amd64/
    * Available dependencies appear to be automatically uploaded once per week by the chrome team.
    * At the time of writing, Flutter pins the version of AVD used.
    * The "versions" supported for a particular dependency come from the source/tools/android/ave/proto directory of the downloaded asset. There is no other way to know support via the CIPD tooling.
* To learn how to update this dependency in the Flutter engine/framework, visit https://github.com/flutter/flutter/blob/master/docs/platforms/android/New-Android-version.md#update-ci.
REM Copyright 2020 The Chromium Authors. All rights reserved.
REM Use of this source code is governed by a BSD-style license that can be
REM found in the LICENSE file.

git fetch origin %GIT_BRANCH%:%GIT_BRANCH%
CD dev/customer_testing/
CALL ci.bat

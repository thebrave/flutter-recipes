REM Copyright 2020 The Chromium Authors. All rights reserved.
REM Use of this source code is governed by a BSD-style license that can be
REM found in the LICENSE file.

REM The customer testing requires both the branch under test and master to be checked out.
git fetch origin master
git checkout master
git fetch origin %GIT_BRANCH%:%GIT_BRANCH%
git checkout %GIT_BRANCH%
CD dev/customer_testing/
CALL ci.bat

# Copyright 2022 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# [VPYTHON:BEGIN]
# python_version: "3.8"
# wheel: <
#   name: "infra/python/wheels/idna-py2_py3"
#   version: "version:2.10"
# >
# wheel: <
#   name: "infra/python/wheels/urllib3-py2_py3"
#   version: "version:1.26.4"
# >
# wheel: <
#   name: "infra/python/wheels/certifi-py2_py3"
#   version: "version:2020.12.5"
# >
# wheel: <
#   name: "infra/python/wheels/chardet-py2_py3"
#   version: "version:4.0.0"
# >
# wheel: <
#   name: "infra/python/wheels/requests-py2_py3"
#   version: "version:2.25.1"
# >
# [VPYTHON:END]

import json
import argparse
import os
import sys
import requests


def upload_results(test_result, url, auth_token):
    res = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"ResultSink {auth_token}",
        },
        data=json.dumps({"test_results": [test_result]}),
    )
    res.raise_for_status()


def add_artifacts_to_test_result(test_result, artifacts):
    """
    Args:
        test_result (dict(str, str)): A dictionary containing the json test_results.

        artifacts (list(list(str, str))): a list containing tuples of size 2 where
            the first element of the tuple is the name of the artifact, and the
            second is the file path to the artifact.
    """
    if not test_result.get("artifacts") and artifacts:
        test_result["artifacts"] = {}

    for name, path in artifacts:
        test_result["artifacts"][name] = {"filePath": path}


def main():
    parser = argparse.ArgumentParser(
        description="Uploads the test result to resultdb. The input is expected to be \
        a json conforming to a TestResult proto message"
    )

    parser.add_argument(
        "test_result",
        action="store",
        help="json string to upload to ResultDB",
    )

    parser.add_argument(
        "--artifact",
        dest="artifacts",
        nargs=2,
        action="append",
        default=[],
        help="artifact to upload as part of the test result, the first arg \
        is the name of the artifact and the second is the path to the artifact, \
        it can be repeated, \
        e.g. --artifact foo path/to/foo --artifact bar path/to/bar",
    )

    args = parser.parse_args()

    sink = None
    if "LUCI_CONTEXT" in os.environ:
        with open(os.environ["LUCI_CONTEXT"], encoding="utf-8") as f:
            sink = json.load(f)["result_sink"]
    if sink is None:
        print("result_sink not defined in LUCI_CONTEXT")
        return 1

    if not args.test_result:
        print("Empty test results: skipping")
        return 0

    url = str.format(
        "http://{}/prpc/luci.resultsink.v1.Sink/{}",
        sink["address"],
        "ReportTestResults",
    )

    test_result = json.loads(args.test_result)
    add_artifacts_to_test_result(test_result, args.artifacts)

    print(f"Uploading test_result: {test_result}")
    upload_results(test_result, url, sink["auth_token"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

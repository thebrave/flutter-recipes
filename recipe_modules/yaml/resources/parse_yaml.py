#!/usr/bin/env vpython3

# [VPYTHON:BEGIN]
# python_version: "3.8"
# wheel <
#   name: "infra/python/wheels/pyyaml/${platform}_${py_python}_${py_abi}"
#   version: "version:5.4.1.chromium.1"
# >
# [VPYTHON:END]

import argparse
import json
import sys
import yaml


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--yaml_file')
  parser.add_argument('--json_file')
  args = parser.parse_args()

  with open(args.yaml_file) as f:
    with open(args.json_file, 'w+') as j:
      json.dump(yaml.safe_load(f), j)


if __name__ == '__main__':
  sys.exit(main())

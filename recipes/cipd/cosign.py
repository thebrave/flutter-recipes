# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
from datetime import datetime

DEPS = [
    'flutter/repo_util',
    'flutter/flutter_deps',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]


# This recipe builds the cosign CIPD package.
def RunSteps(api):
  env = {}
  env_prefixes = {}
  api.flutter_deps.required_deps(
      env, env_prefixes, api.properties.get('dependencies', [])
  )

  cosign_default_dir = api.path.start_dir.join('cosign')

  cosign_download_uris = GetLatestCosignDownloadUris(api)

  for platform in ['darwin', 'linux', 'windows']:
    cosign_dir = cosign_default_dir.join(platform)

    DownloadCosignArtifacts(api, cosign_dir, platform, cosign_download_uris)

    with api.context(env=env, env_prefixes=env_prefixes):
      VerifyCosignArtifactSignature(api, cosign_dir, platform)

    UploadCosignToCipd(api, cosign_dir, platform)


def GetLatestCosignDownloadUris(api):
  """Gets the list of latest sigstore/cosign binary urls.

  Queries Github for a list of cosign releases, then picks the latest release,
  queries the artifacts for that release, and returns a list of cosign binary
  urls for that release.

  Args:
    api: luci api object.
  """
  cosign_releases_raw_response = api.step(
      'Get cosign releases from github',
      cmd=['curl', 'https://api.github.com/repos/sigstore/cosign/releases'],
      stdout=api.raw_io.output_text()
  ).stdout
  cosign_releases = json.loads(cosign_releases_raw_response)

  latest_release = max(
      cosign_releases,
      key=lambda release: datetime.
      strptime(release.get('published_at'), '%Y-%m-%dT%H:%M:%SZ')
  ).get('url')

  release_artifacts_raw_response = api.step(
      'Get artifacts from sigstore/cosign for a specific release version',
      cmd=['curl', latest_release],
      stdout=api.raw_io.output_text()
  ).stdout
  release_artifacts = json.loads(release_artifacts_raw_response)

  release_artifacts_download_uris = list(
      map(
          lambda asset: asset.get('browser_download_url'),
          release_artifacts.get('assets')
      )
  )

  return release_artifacts_download_uris


def DownloadCosignArtifacts(api, cosign_dir, platform, cosign_download_uris):
  """Downloads the latest cosign binary, certificate, and signature.

  Takes a list of cosign download uris and finds the binary, certificate, and
  signature urls based on the platform. Then, the three files are downloaded to
  the cosign directory.

  Args:
    api: luci api object.
    cosign_dir(str): the folder where the cosign binary/certificate/signature
      will be downloaded.
    platform(str): the platform of the binary that needs to be downloaded
      (windows, linux, darwin)
    cosign_download_uris(list(str)): a list of all the download uris for a
      specific cosign release.
  """
  exe = '.exe' if platform == 'windows' else ''
  cosign_base_name = 'cosign-%s-amd64%s' % (platform, exe)

  cosign_binary_download_uri = next(
      filter(lambda uri: uri.endswith(cosign_base_name), cosign_download_uris)
  )

  cosign_certificate_download_uri = next(
      filter(
          lambda uri: uri.endswith('%s-keyless.pem' % cosign_base_name),
          cosign_download_uris
      )
  )

  cosign_signature_download_uri = next(
      filter(
          lambda uri: uri.endswith('%s-keyless.sig' % cosign_base_name),
          cosign_download_uris
      )
  )

  api.step(
      'Download %s cosign binary' % platform, [
          'curl', '-L', cosign_binary_download_uri, '-o',
          cosign_dir.join('bin', 'cosign%s' % exe), '--create-dirs'
      ],
      infra_step=True
  )

  api.step(
      'Download %s cosign certificate' % platform, [
          'curl', '-L', cosign_certificate_download_uri, '-o',
          cosign_dir.join("certificate", "cosign-cert%s.pem" % exe),
          '--create-dirs'
      ],
      infra_step=True
  )

  api.step(
      'Download %s cosign signature' % platform, [
          'curl', '-L', cosign_signature_download_uri, '-o',
          cosign_dir.join("certificate", "cosign-sig%s.sig" % exe),
          '--create-dirs'
      ],
      infra_step=True
  )

  if platform == 'linux' or platform == 'darwin':
    api.step(
        'Make %s cosign binary executable' % platform,
        ['chmod', '755',
         cosign_dir.join('bin', 'cosign%s' % exe)]
    )


def VerifyCosignArtifactSignature(api, cosign_dir, platform):
  """Verifies the cosign artifact is legitimate

  Uses the cosign release signature and certificate to ensure that the cosign
  binary is legitimate. This is done using the current version of cosign in
  CIPD.

  Args:
    api: luci api object.
    cosign_dir(str): the folder where the cosign binary/certificate/signature
      is located.
    platform(str): the platform of the binary (windows, linux, darwin)
  """
  exe = '.exe' if platform == 'windows' else ''

  api.step(
      'Verify %s cosign binary is legitimate' % platform, [
          'cosign', 'verify-blob', '--cert',
          cosign_dir.join("certificate", "cosign-cert%s.pem" % exe),
          '--signature',
          cosign_dir.join("certificate", "cosign-sig%s.sig" % exe),
          cosign_dir.join("bin", "cosign%s" % exe)
      ]
  )


def UploadCosignToCipd(api, cosign_dir, platform):
  """Uploads cosign to CIPD.

  Upload the cosign binary, certificate, and signature to CIPD and adds the
  latest tag to this version.

  Args:
    api: luci api object.
    cosign_dir(str): the folder where the cosign binary/certificate/signature
      is located.
    platform(str): the platform of the binary (windows, linux, darwin)
  """
  cipd_platform = 'mac' if platform == 'darwin' else platform
  cipd_package_name = 'flutter/tools/cosign/%s-amd64' % cipd_platform
  cipd_zip_path = 'cosign.zip'
  api.cipd.build(cosign_dir, cipd_zip_path, cipd_package_name)
  api.cipd.register(cipd_package_name, cipd_zip_path, refs=['latest'])


def GenTests(api):
  yield api.test(
      'cosign', api.properties(cosign_version='v1.0'),
      api.platform('linux', 64),
      api.step_data(
          'Get cosign releases from github',
          stdout=api.raw_io.output_text(
              '''
        [
          {
            "url": "https://api.github.com/releases/1",
            "published_at": "2022-06-03T14:08:35Z"
          },
          {
            "url": "https://api.github.com/releases/2",
            "published_at": "2022-06-02T14:08:35Z"
          }
        ]
        '''
          )
      ) + api.step_data(
          'Get artifacts from sigstore/cosign for a specific release version',
          stdout=api.raw_io.output_text(
              '''
        {
          "assets":[
            {
              "browser_download_url":"cosign-linux-amd64"
            },
            {
              "browser_download_url":"cosign-linux-amd64-keyless.pem"
            },
            {
              "browser_download_url":"cosign-linux-amd64-keyless.sig"
            },
            {
              "browser_download_url":"cosign-darwin-amd64"
            },
            {
              "browser_download_url":"cosign-darwin-amd64-keyless.pem"
            },
            {
              "browser_download_url":"cosign-darwin-amd64-keyless.sig"
            },
            {
              "browser_download_url":"cosign-windows-amd64.exe"
            },
            {
              "browser_download_url":"cosign-windows-amd64.exe-keyless.pem"
            },
            {
              "browser_download_url":"cosign-windows-amd64.exe-keyless.sig"
            },
            {
              "browser_download_url":"some-other-artifact"
            }
          ]
        }
        '''
          )
      )
  )

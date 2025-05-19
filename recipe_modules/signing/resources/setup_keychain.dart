#!/usr/bin/env dart
// Copyright 2024 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Helper script to import a flutter p12 identity.

import 'dart:io' as io;

const String keychainName = 'build.keychain';
const String keychainPassword = '';
const int totalRetryAttempts = 3;

Future<void> main() async {
  final io.File logFile = io.File(
    io.Platform.environment['SETUP_KEYCHAIN_LOGS_PATH']!,
  );
  final logSink = logFile.openWrite();
  void log(String line) {
    logSink.writeln('$line\n');
  }

  final SetupKeychain setupKeychain = SetupKeychain(log: log);

  int exitCode = 1;
  try {
    exitCode = await setupKeychain.setup(
      passwordPath: io.Platform.environment['FLUTTER_P12_PASSWORD']!,
      flutterP12Path: io.Platform.environment['FLUTTER_P12']!,
      p12SuffixFilePath: io.Platform.environment['P12_SUFFIX_FILEPATH']!,
      codesignPath: io.Platform.environment['CODESIGN_PATH']!,
    );
  } finally {
    await logSink.flush();
    await logSink.close();
  }
  io.exit(exitCode);
}

class SetupKeychain {
  SetupKeychain({required this.log});

  final void Function(String) log;

  /// Create a keychain called `build.keychain` and import the Flutter private key (p12),
  /// the password for the p12, and various Apple certs into it.
  Future<int> setup({
    required String passwordPath,
    required String flutterP12Path,
    required String p12SuffixFilePath,
    required String codesignPath,
  }) async {
    try {
      final String rawPassword = io.File(passwordPath).readAsStringSync();

      // Only filepath with a .p12 suffix will be recognized
      io.File(flutterP12Path).renameSync(p12SuffixFilePath);

      // Delete build.keychain if it exists
      _security(const <String>[
        'delete-keychain',
        keychainName,
      ], allowNonzero: true);

      // Create keychain.
      _security(const <String>[
        'create-keychain',
        '-p',
        keychainPassword,
        keychainName,
      ]);

      await _downloadAndImportAppleCert(
        'DeveloperIDG2CA',
        codesignPath,
        keychainName,
      );

      await _downloadAndImportAppleCert(
        'AppleWWDRCAG3',
        codesignPath,
        keychainName,
      );

      // Allow non-zero exit code when adding to login.keychain as it may already exist in the keychain.
      await _downloadAndImportAppleCert(
        'AppleWWDRCAG3',
        codesignPath,
        'login.keychain',
        allowNonzero: true,
      );

      // Retrieve current list of keychains on the search list of current machine.
      final keychains =
          _security(const <String>[
            'list-keychains',
            '-d',
            'user',
          ]).split('\n').map<String?>((String line) {
            final RegExp pattern = RegExp(r'^\s*".*\/([a-zA-Z0-9.]+)-db"');
            final RegExpMatch? match = pattern.firstMatch(line);
            if (match == null) {
              return null;
            }
            // The first (and only) capture group is the name of the keychain
            return match.group(1);
          }).whereType<String>();

      print('User keychains on this machine: $keychains');

      // Add keychain name to search list.
      // Without this, future commands such as `security import`,
      // `security find-identity` and `codesign ...` will fail to find the cert
      // in our newly created keychain.
      _security(<String>[
        '-v',
        'list-keychains',
        // TODO(fujino): we probably don't need $keychains here, only keychainName should be required
        '-s', ...keychains, keychainName,
      ]);

      // For diagnostic purposes, list keychains AFTER adding our newly created
      // keychain to the search list.
      _security(const <String>['list-keychains', '-d', 'user']);

      // Set $keychainName as default.
      _security(<String>['default-keychain', '-s', keychainName]);

      // Unlock keychainName to allow sign commands to use its certs.
      _security(<String>[
        'unlock-keychain',
        '-p',
        keychainPassword,
        keychainName,
      ]);

      // This will be exponentially increased on retries
      int sleepSeconds = 2;

      for (int attempt = 0; attempt < totalRetryAttempts; attempt++) {
        _security(<String>[
          'import',
          p12SuffixFilePath,
          '-k', keychainName,
          '-P', rawPassword,
          // -T allows the specified program to access this identity
          '-T', codesignPath,
          '-T', '/usr/bin/codesign',
        ]);
        _security(<String>[
          'set-key-partition-list',
          '-S',
          'apple-tool:,apple:,codesign:',
          '-s',
          '-k',
          '',
          keychainName,
        ]);

        final String identities = _security(const <String>[
          'find-identity',
          '-v',
          keychainName,
        ]);
        if (identities.contains('FLUTTER.IO LLC')) {
          log(
            'successfully found a Flutter identity in the $keychainName keychain',
          );
          return 0;
        }
        log(
          'failed to find a Flutter identity in the $keychainName keychain on attempt $attempt',
        );
        await Future<void>.delayed(Duration(seconds: sleepSeconds));
        sleepSeconds *= sleepSeconds;
      }
    } finally {
      _security(const <String>[
        'find-certificate',
        // Find all matching certificates, not just the first
        '-a',
      ]);
    }
    log(
      'failed to find a Flutter identity after $totalRetryAttempts attempts.',
    );
    return 1;
  }

  String _security(List<String> args, {bool allowNonzero = false}) {
    log('Executing ${<String>['/usr/bin/security', ...args]}');

    final io.ProcessResult result = io.Process.runSync(
      '/usr/bin/security',
      args,
    );

    log('process finished with exitCode ${result.exitCode}');
    log('STDOUT:\n\n${result.stdout}');
    log('STDERR:\n\n${result.stderr}');

    if (!allowNonzero && result.exitCode != 0) {
      throw io.ProcessException(
        '/usr/bin/security',
        args,
        'failed',
        result.exitCode,
      );
    }

    return result.stdout as String;
  }

  Future<void> _downloadAndImportAppleCert(
    String certName,
    String codesignPath,
    String targetKeychain, {
    bool allowNonzero = false,
  }) async {
    // TODO(vashworth): cache this via CIPD
    final io.File certFile = await _downloadFile(
      // Link from https://www.apple.com/certificateauthority
      remoteUri: Uri.parse(
        'https://www.apple.com/certificateauthority/$certName.cer',
      ),
      localPath: './$certName.cer',
    );

    // LOAD certificate authority into the build keychain
    await _security(<String>[
      'import',
      certFile.absolute.path,
      '-k', targetKeychain,
      // -T allows the specified program to access this identity
      '-T', codesignPath,
      '-T', '/usr/bin/codesign',
    ], allowNonzero: allowNonzero);
  }

  Future<io.File> _downloadFile({
    required Uri remoteUri,
    required String localPath,
  }) async {
    final io.HttpClient client = io.HttpClient();

    final io.HttpClientRequest request = await client.getUrl(remoteUri);
    final io.HttpClientResponse response = await request.close();
    final io.File certFile = io.File(localPath);
    final io.IOSink sink = certFile.openWrite();
    await response.pipe(sink);

    client.close();
    return certFile;
  }
}

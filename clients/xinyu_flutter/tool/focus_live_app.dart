import 'dart:io';

import 'package:flutter/material.dart';
import 'package:xinyu_flutter/data/local_repository.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';

/// Runs the production widgets and controller against an owned synthetic test
/// instance. Never falls back to the installed application's daily database.
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final endpoint = Platform.environment['XINYU_REVIEW_ENDPOINT'];
  if (endpoint == null) throw StateError('An isolated review endpoint is required.');
  runApp(
    XinYuApp(
      controller: CompanionController(repository: LocalRepository(endpoint)),
    ),
  );
}

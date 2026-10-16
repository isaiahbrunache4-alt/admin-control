// Fortress Console: the main UI (Spec 01 §5). Talks to Fortress Core on localhost.
//
//   flutter run -d windows                      # Core on the default port
//   flutter run -d windows --dart-define=FORTRESS_CORE_URL=http://127.0.0.1:47811/api/v1/

import 'package:flutter/material.dart';

import 'api.dart';
import 'state.dart';
import 'ui/app.dart';

const _coreUrl = String.fromEnvironment('FORTRESS_CORE_URL', defaultValue: defaultCoreUrl);

void main() {
  final state = ConsoleState(FortressApi(base: Uri.parse(_coreUrl)));
  state.start();
  runApp(ConsoleApp(state: state));
}

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/state/automation_controller.dart';
import 'package:xinyu_flutter/ui/reply_haptics.dart';

import 'phone_test.dart' show PhoneRepository;

class HapticRepository extends PhoneRepository {
  HapticRepository() {
    value['phone']['groups'].add({
      'id': 'haptics',
      'title': '触感陪伴',
      'tools': ['vibrate_pattern', 'cancel_vibration'],
    });
  }

  @override
  Future<void> connectPhone() async {
    await super.connectPhone();
    value['catalog']['droid'].addAll([
      {'name': 'vibrate_pattern', 'description': '短拍'},
      {'name': 'cancel_vibration', 'description': '停止'},
    ]);
  }
}

void main() {
  test(
    'reply expression grants only haptics and obeys group revocation',
    () async {
      final repository = HapticRepository();
      final controller = AutomationController(
        () => repository,
        onActionComplete: () async {},
      );
      addTearDown(repository.close);
      addTearDown(controller.dispose);
      await controller.connectPhone();
      expect(controller.state!.config['reply_haptics_enabled'], isNot(true));
      final before = controller.state!.phoneServer!['tools']['set_volume'];
      await controller.setReplyHaptics(true);
      expect(controller.state!.config['reply_haptics_enabled'], true);
      expect(controller.state!.phonePermission('vibrate_pattern'), 'allow');
      expect(controller.state!.phonePermission('cancel_vibration'), 'allow');
      expect(controller.state!.phonePermission('query_screen'), 'off');
      expect(controller.state!.phoneServer!['tools']['set_volume'], before);
      expect(controller.state!.phoneComfortConfig['enabled'], isNot(true));
      await controller.setPhoneGroupPermission('haptics', 'ask');
      expect(controller.state!.config['reply_haptics_enabled'], false);
      expect(controller.state!.phonePermission('vibrate_pattern'), 'ask');
      await controller.setReplyHaptics(true);
      final rules = controller.state!.phoneServer!['tools'];
      await controller.setReplyHaptics(false);
      expect(controller.state!.config['reply_haptics_enabled'], false);
      expect(controller.state!.phoneServer!['tools'], rules);
    },
  );

  test(
    'missing device capability leaves switch off with a useful error',
    () async {
      final repository = PhoneRepository();
      final controller = AutomationController(
        () => repository,
        onActionComplete: () async {},
      );
      addTearDown(repository.close);
      addTearDown(controller.dispose);
      await controller.connectPhone();
      await controller.setReplyHaptics(true);
      expect(controller.state!.config['reply_haptics_enabled'], isNot(true));
      expect(controller.error, contains('支持触感'));
    },
  );

  for (final width in [320.0, 768.0, 1024.0, 1440.0]) {
    testWidgets(
      'reply haptics switch supports keyboard and semantics at $width',
      (tester) async {
        await tester.binding.setSurfaceSize(Size(width, 900));
        addTearDown(() => tester.binding.setSurfaceSize(null));
        final semantics = tester.ensureSemantics();
        try {
          final repository = HapticRepository();
          final controller = AutomationController(
            () => repository,
            onActionComplete: () async {},
          );
          addTearDown(repository.close);
          addTearDown(controller.dispose);
          await controller.connectPhone();
          await tester.pumpWidget(
            MaterialApp(
              home: Scaffold(
                body: ListenableBuilder(
                  listenable: controller,
                  builder: (_, _) => ReplyHapticsCard(
                    controller: controller,
                    disabled: controller.busy,
                  ),
                ),
              ),
            ),
          );
          expect(find.bySemanticsLabel(RegExp('随回复表达触感')), findsWidgets);
          await tester.sendKeyEvent(LogicalKeyboardKey.tab);
          await tester.sendKeyEvent(LogicalKeyboardKey.space);
          await tester.pumpAndSettle();
          expect(controller.state!.config['reply_haptics_enabled'], true);
          expect(find.textContaining('至少间隔 20 秒'), findsOneWidget);
          final switchTile = find.byKey(const Key('reply-haptics-enabled'));
          expect(tester.getSize(switchTile).height, greaterThanOrEqualTo(48));
          await tester.tap(switchTile);
          await tester.pumpAndSettle();
          expect(controller.state!.config['reply_haptics_enabled'], false);
          expect(tester.takeException(), isNull);
        } finally {
          semantics.dispose();
        }
      },
    );
  }
}

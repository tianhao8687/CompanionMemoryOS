import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';

import 'settings_navigation.dart';

void main() {
  testWidgets('music comfort can be disabled and saved from a narrow phone', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 740);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller = CompanionController();
    addTearDown(controller.dispose);
    await tester.pumpWidget(XinYuApp(controller: controller));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('open-settings')));
    await tester.pumpAndSettle();
    await settingsSection(tester, '陪伴');
    await settingsGroup(tester, '聊天节奏');
    final control = find.byKey(const Key('comfort-music'));
    await Scrollable.ensureVisible(tester.element(control), alignment: 0.2);
    await tester.pumpAndSettle();
    expect(tester.widget<SwitchListTile>(control).value, isTrue);
    await tester.tap(control);
    await tester.pumpAndSettle();
    expect(tester.widget<SwitchListTile>(control).value, isFalse);
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('保存设置'));
    await tester.pumpAndSettle();
    expect(controller.settings['comfort_music_enabled'], isFalse);
    await tester.pumpWidget(const SizedBox());
  });
}

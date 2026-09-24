import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';

void main() {
  for (final size in [
    const Size(320, 640),
    const Size(390, 844),
    const Size(1920, 1080),
  ]) {
    testWidgets('Chat and settings fit ${size.width}x${size.height}', (
      tester,
    ) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(const XinYuApp());
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('message-input')), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.tap(find.byKey(const Key('open-settings')));
      await tester.pumpAndSettle();
      expect(find.text('让这里，更像我们'), findsOneWidget);
      await tester.tap(find.text('连接与数据'));
      await tester.pumpAndSettle();
      expect(find.text('连接服务'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    });
  }

  testWidgets('Demo send, setting save and large text with keyboard', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller = CompanionController();
    addTearDown(controller.dispose);
    await tester.pumpWidget(XinYuApp(controller: controller));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('message-input')), '测试流式回复');
    await tester.pump();
    await tester.tap(find.byKey(const Key('send-message')));
    // Fixed virtual-time steps exercise the timer-driven stream, not a fake
    // synchronous reply. pumpAndSettle alone need not wait for pending timers.
    for (var i = 0; i < 60; i++) {
      await tester.pump(const Duration(milliseconds: 40));
    }
    expect(controller.messages.last.text, contains('这是原型的示例回复'));
    expect(controller.messages.where((m) => m.text == '测试流式回复'), hasLength(1));
    await tester.tap(find.byKey(const Key('open-settings')));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextFormField, '怎么称呼 TA'), '小夏');
    await tester.tap(find.text('保存设置'));
    await tester.pumpAndSettle();
    expect(controller.companionName, '小夏');
    tester.view.viewInsets = const FakeViewPadding(bottom: 300);
    addTearDown(tester.view.resetViewInsets);
    tester.platformDispatcher.textScaleFactorTestValue = 1.5;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('Long conversation stays lazy and remains scrollable', (
    tester,
  ) async {
    final controller = CompanionController();
    addTearDown(controller.dispose);
    await tester.pumpWidget(XinYuApp(controller: controller));
    await tester.pumpAndSettle();
    await controller.benchmark();
    await tester.pumpAndSettle();
    expect(controller.messages, hasLength(200));
    expect(find.byType(BackdropFilter).evaluate().length, lessThan(40));
    await tester.drag(find.byKey(const Key('chat-list')), const Offset(0, 600));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}

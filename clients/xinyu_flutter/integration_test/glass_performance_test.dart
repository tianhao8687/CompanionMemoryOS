import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/state/frame_probe.dart';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('Long chat scroll, text entry and glass settings', (
    tester,
  ) async {
    final controller = CompanionController();
    final probe = FrameProbe();
    await tester.pumpWidget(XinYuApp(controller: controller, probe: probe));
    await tester.pumpAndSettle();
    await controller.benchmark();
    await tester.pumpAndSettle();
    probe.reset();
    await binding.traceAction(() async {
      for (var i = 0; i < 8; i++) {
        await tester.fling(
          find.byKey(const Key('chat-list')),
          Offset(0, i.isEven ? 600 : -600),
          1300,
        );
        await tester.pumpAndSettle();
      }
      await tester.enterText(
        find.byKey(const Key('message-input')),
        '全玻璃输入与滚动性能测试。',
      );
      await tester.pumpAndSettle();
      for (var i = 0; i < 4; i++) {
        await tester.tap(find.byKey(const Key('open-settings')));
        await tester.pumpAndSettle();
        await tester.tap(find.byTooltip('关闭设置'));
        await tester.pumpAndSettle();
      }
    }, reportKey: 'glass_timeline');
    binding.reportData ??= {};
    binding.reportData!['glass_summary'] = {
      ...probe.summary(),
      'physical_width': tester.view.physicalSize.width,
      'physical_height': tester.view.physicalSize.height,
      'device_pixel_ratio': tester.view.devicePixelRatio,
      'messages': controller.messages.length,
    };
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
    probe.dispose();
  });
}

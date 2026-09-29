import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/demo_repository.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';

class LocalVoiceRepository extends DemoRepository {
  @override
  bool get isDemo => false;
}

void main() {
  for (final width in [320.0, 390.0]) {
    testWidgets('Custom voice saves, reopens and cancels at width $width', (
      tester,
    ) async {
      tester.view.physicalSize = Size(width, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final repo = LocalVoiceRepository();
      await repo.saveSettings({
        ...(await repo.bootstrap()).settings,
        'style': 'custom',
        'custom_style': '温顺随和。',
        'font_size': 'extra_large',
      });
      final controller = CompanionController(repository: repo);
      addTearDown(controller.dispose);
      await tester.pumpWidget(XinYuApp(controller: controller));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('open-settings')));
      await tester.pumpAndSettle();
      final scroll = find
          .descendant(
            of: find.byKey(const Key('settings-scroll')),
            matching: find.byType(Scrollable),
          )
          .first;
      final examples = find.byKey(const Key('custom-style-examples'));
      final avoid = find.byKey(const Key('custom-style-avoid'));
      await tester.scrollUntilVisible(examples, 200, scrollable: scroll);
      await tester.enterText(examples, '你选的这部电影，今晚慢慢看。');
      await tester.scrollUntilVisible(avoid, 200, scrollable: scroll);
      await tester.enterText(avoid, '不要每轮用同一种安慰开场。');
      expect(find.byKey(const Key('custom-style-demo-notice')), findsOneWidget);
      await tester.tap(find.text('保存设置'));
      await tester.pumpAndSettle();
      expect(controller.settings['custom_style_examples'], '你选的这部电影，今晚慢慢看。');
      expect(controller.settings['custom_style_avoid'], '不要每轮用同一种安慰开场。');
      await tester.tap(find.byKey(const Key('open-settings')));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(examples, 200, scrollable: scroll);
      expect(
        tester.widget<TextFormField>(examples).controller!.text,
        '你选的这部电影，今晚慢慢看。',
      );
      await tester.enterText(examples, '这份修改不保存。');
      await tester.tap(find.byTooltip('关闭设置'));
      await tester.pumpAndSettle();
      expect(controller.settings['custom_style_examples'], '你选的这部电影，今晚慢慢看。');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }
  testWidgets(
    'Voice drafts hide outside custom mode and remain available when returning',
    (tester) async {
      final controller = CompanionController();
      addTearDown(controller.dispose);
      await tester.pumpWidget(XinYuApp(controller: controller));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('open-settings')));
      await tester.pumpAndSettle();
      final scroll = find
          .descendant(
            of: find.byKey(const Key('settings-scroll')),
            matching: find.byType(Scrollable),
          )
          .first;
      await tester.scrollUntilVisible(
        find.text('自定义'),
        200,
        scrollable: scroll,
      );
      await tester.tap(find.text('自定义'));
      await tester.pumpAndSettle();
      final examples = find.byKey(const Key('custom-style-examples'));
      await tester.scrollUntilVisible(examples, 200, scrollable: scroll);
      await tester.enterText(examples, '暂时保留的说话示例。');
      await tester.scrollUntilVisible(
        find.text('温柔细腻'),
        -200,
        scrollable: scroll,
      );
      await tester.tap(find.text('温柔细腻'));
      await tester.pumpAndSettle();
      expect(examples, findsNothing);
      await tester.tap(find.text('自定义'));
      await tester.pumpAndSettle();
      expect(
        tester.widget<TextFormField>(examples).controller!.text,
        '暂时保留的说话示例。',
      );
      await tester.pumpWidget(const SizedBox());
    },
  );
}

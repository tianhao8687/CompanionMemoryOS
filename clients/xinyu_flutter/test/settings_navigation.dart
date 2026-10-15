import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Future<void> settingsSection(WidgetTester tester, String title) async {
  if (find.byTooltip('返回设置').evaluate().isNotEmpty) {
    await tester.tap(find.byTooltip('返回设置'));
    await tester.pumpAndSettle();
  }
  const sections = {'陪伴': 0, '连接': 1, '外观': 2, '隐私与数据': 4};
  await tester.tap(find.byKey(ValueKey('settings-section-${sections[title]}')));
  await tester.pumpAndSettle();
}

Future<void> settingsGroup(WidgetTester tester, String title) async {
  final item = find.widgetWithText(ExpansionTile, title);
  await Scrollable.ensureVisible(tester.element(item), alignment: 0);
  await tester.pumpAndSettle();
  await tester.tap(find.text(title).first);
  await tester.pumpAndSettle();
}

Future<void> closeSettings(WidgetTester tester) async {
  if (find.byTooltip('返回设置').evaluate().isNotEmpty) {
    await tester.tap(find.byTooltip('返回设置'));
    await tester.pumpAndSettle();
  }
  if (find.byTooltip('返回').evaluate().isNotEmpty) {
    await tester.tap(find.byTooltip('返回'));
  } else {
    await tester.tap(find.byTooltip('关闭设置'));
  }
  await tester.pumpAndSettle();
}

Future<void> composeAction(WidgetTester tester, String action) async {
  if (find.byKey(const Key('compose-more')).evaluate().isNotEmpty) {
    await tester.tap(find.byKey(const Key('compose-more')));
    await tester.pumpAndSettle();
    await tester.tap(
      find
          .text(
            {
              'open-focus': '陪我专注',
              'attach-image': '添加图片',
              'open-music': '一起听',
            }[action]!,
          )
          .last,
    );
  } else {
    await tester.tap(find.byKey(Key(action)));
  }
  if (action == 'open-music') {
    // A playing record intentionally never settles. Finish route and lyric futures.
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pump(const Duration(milliseconds: 100));
  } else {
    await tester.pumpAndSettle();
  }
}

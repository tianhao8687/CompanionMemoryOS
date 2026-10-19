import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/automation.dart';
import 'package:xinyu_flutter/data/phone_actions.dart';
import 'package:xinyu_flutter/state/automation_controller.dart';
import 'package:xinyu_flutter/ui/connected_phone.dart';

import 'phone_test.dart' show PhoneRepository;

class MessageRepository extends PhoneRepository {
  MessageRepository() {
    (value['phone']['groups'] as List).add({
      'id': 'chat_notifications',
      'title': '陪我看消息',
      'description': '每次确认后读取指定应用的通知预览。内容会进入当前对话并交给配置的模型。',
      'tools': ['read_chat_notifications'],
    });
  }

  @override
  Future<void> connectPhone() async {
    await super.connectPhone();
    (value['catalog']['droid'] as List).add({
      'name': 'read_chat_notifications',
      'description': '陪我看消息。读取通知预览。',
    });
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'new preview permission is off and cannot silently become allow',
    () async {
      final repository = MessageRepository();
      final controller = AutomationController(
        () => repository,
        onActionComplete: () async {},
      );
      addTearDown(controller.dispose);
      addTearDown(repository.close);
      await controller.connectPhone();
      expect(
        controller.state!.phonePermission('read_chat_notifications'),
        'off',
      );
      await controller.setPhoneGroupPermission('chat_notifications', 'allow');
      expect(
        controller.state!.phonePermission('read_chat_notifications'),
        'ask',
      );
      expect(
        controller
            .state!
            .phoneServer!['tools']['read_chat_notifications']['mode'],
        'ask',
      );
      expect(controller.state!.phonePermission('query_screen'), 'off');
      await controller.setPhoneGroupPermission('chat_notifications', 'off');
      expect(
        controller.state!.phonePermission('read_chat_notifications'),
        'off',
      );
    },
  );

  test('imported allow configuration is shown as per-read approval', () {
    final state = AutomationState({
      'config': {
        'servers': [
          {
            'id': 'droid',
            'tools': {
              'read_chat_notifications': {'mode': 'allow'},
            },
          },
        ],
      },
    });
    expect(state.phonePermission('read_chat_notifications'), 'ask');
  });

  test('approval describes exact app, person, scope and data use', () {
    final text = phoneActionDescription('read_chat_notifications', {
      'package_name': 'com.tencent.mm',
      'title_filter': '小雨',
      'limit': 2,
    });
    expect(text, contains('微信'));
    expect(text, contains('标题含“小雨”'));
    expect(text, contains('最新 2 条'));
    expect(text, contains('配置的模型'));
    expect(text, contains('不发送消息'));
  });

  for (final width in [320.0, 768.0, 1024.0, 1440.0]) {
    testWidgets(
      'preview settings and separate permission work at width $width',
      (tester) async {
        await tester.binding.setSurfaceSize(Size(width, 1100));
        addTearDown(() => tester.binding.setSurfaceSize(null));
        final repository = MessageRepository();
        final controller = AutomationController(
          () => repository,
          onActionComplete: () async {},
        );
        addTearDown(controller.dispose);
        addTearDown(repository.close);
        final calls = <MethodCall>[];
        tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          const MethodChannel('xinyu/phone'),
          (call) async {
            calls.add(call);
            return null;
          },
        );
        addTearDown(
          () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
            const MethodChannel('xinyu/phone'),
            null,
          ),
        );
        await controller.connectPhone();
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: SingleChildScrollView(
                child: ListenableBuilder(
                  listenable: controller,
                  builder: (_, _) => PhoneConnectionCard(
                    controller: controller,
                    disabled: controller.busy,
                  ),
                ),
              ),
            ),
          ),
        );
        final menu = find.byKey(
          const Key('phone-permission-chat_notifications'),
        );
        await tester.ensureVisible(menu);
        final semantics = tester.ensureSemantics();
        try {
          await tester.pump();
          expect(
            tester.getSemantics(menu).getSemanticsData().tooltip,
            '更改陪我看消息权限',
          );
          bool focused() {
            var found = false;
            FocusManager.instance.primaryFocus?.context?.visitAncestorElements((
              element,
            ) {
              found =
                  element.widget.key ==
                  const Key('phone-permission-chat_notifications');
              return !found;
            });
            return found;
          }

          for (var i = 0; i < 15 && !focused(); i++) {
            await tester.sendKeyEvent(LogicalKeyboardKey.tab);
            await tester.pump();
          }
          expect(focused(), true);
          await tester.sendKeyEvent(LogicalKeyboardKey.enter);
          await tester.pumpAndSettle();
          expect(find.text('每次读取前确认'), findsOneWidget);
          await tester.sendKeyEvent(LogicalKeyboardKey.escape);
          await tester.pumpAndSettle();
        } finally {
          semantics.dispose();
        }
        await tester.tap(menu);
        await tester.pumpAndSettle();
        expect(find.text('按要求直接执行'), findsNothing);
        await tester.tap(find.text('每次读取前确认'));
        await tester.pumpAndSettle();
        expect(
          controller.state!.phonePermission('read_chat_notifications'),
          'ask',
        );
        await tester.ensureVisible(find.text('手机权限与使用说明'));
        await tester.tap(find.text('手机权限与使用说明'));
        await tester.pumpAndSettle();
        final grant = find.byKey(const Key('phone-grant-chat_notifications'));
        await tester.ensureVisible(grant);
        await tester.tap(grant);
        await tester.pumpAndSettle();
        expect(calls.single.method, 'openPermissionSettings');
        expect(calls.single.arguments, {'permission': 'chat_notifications'});
        expect(tester.takeException(), isNull);
      },
    );
  }
}

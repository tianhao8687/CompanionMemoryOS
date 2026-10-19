import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/automation.dart';
import 'package:xinyu_flutter/state/automation_controller.dart';
import 'package:xinyu_flutter/ui/connected_phone.dart';

import 'automation_test.dart' show MusicRepository, copy;

class PhoneRepository extends MusicRepository {
  int restores = 0;
  bool failControl = false;
  final controls = <String>[];
  List<String> keptIds = [];
  PhoneRepository() {
    value['phone'] = {
      'supported': true,
      'permissions': {'accessibility': false, 'dnd': true},
      'groups': [
        {
          'id': 'comfort',
          'title': '声音与亮度',
          'description': '调整媒体音量和屏幕亮度。',
          'tools': ['set_volume'],
        },
        {
          'id': 'accessibility',
          'title': '界面操作',
          'description': '读取当前应用的界面文字、点击、输入和滚动。界面内容会交给当前配置的模型。',
          'tools': ['query_screen'],
        },
      ],
    };
  }
  @override
  Future<Map<String, dynamic>> phoneTemplate() async => {
    'id': 'droid',
    'enabled': false,
    'transport': 'native',
    'tools': {
      'set_volume': {
        'mode': 'ask',
        'arguments': {
          'stream': ['media'],
        },
      },
      'query_screen': {'mode': 'off'},
    },
  };
  @override
  Future<void> connectPhone() async {
    connections++;
    value['catalog'] = {
      'droid': [
        {'name': 'get_settings', 'description': '读取音量和亮度。'},
        {'name': 'set_volume', 'description': '调整媒体音量。'},
        {'name': 'set_brightness', 'description': '调整屏幕亮度。'},
        {'name': 'get_light_level', 'description': '读取环境光。'},
        {'name': 'get_proximity', 'description': '读取接近状态。'},
        {'name': 'get_dnd_status', 'description': '读取勿扰状态。'},
        {'name': 'set_dnd_mode', 'description': '调整勿扰。'},
        {'name': 'query_screen', 'description': '读取当前界面。'},
      ],
    };
  }

  @override
  Future<Map<String, dynamic>> restorePhoneComfort() async {
    restores++;
    value['phone_comfort'] = {'active': []};
    return {'status': 'succeeded', 'verified': true};
  }

  @override
  Future<Map<String, dynamic>> controlPhoneComfort(
    String action, {
    List<String> actionIds = const [],
  }) async {
    if (failControl) throw Exception('synthetic control failure');
    controls.add(action);
    if (action == 'keep') {
      keptIds = actionIds;
      value['phone_comfort'] = {'active': []};
    } else {
      final config = automationMap(value['config']);
      config['phone_comfort'] = {
        ...automationMap(config['phone_comfort']),
        'paused_until': action == 'pause'
            ? DateTime.now()
                  .toUtc()
                  .add(const Duration(minutes: 15))
                  .toIso8601String()
            : null,
      };
      value['config'] = config;
    }
    return {'status': 'succeeded', 'message': '操作已保存。'};
  }
}

void main() {
  test('companionship grants only selected settings and preserves UI permission and constraints', () async {
    final repository = PhoneRepository();
    final controller = AutomationController(
      () => repository,
      onActionComplete: () async {},
    );
    addTearDown(controller.dispose);
    addTearDown(repository.close);
    await controller.connectPhone();
    await controller.setPhoneComfort('enabled', true);
    expect(controller.state!.phoneComfortConfig['enabled'], true);
    expect(controller.state!.phonePermission('set_volume'), 'allow');
    expect(controller.state!.phonePermission('set_brightness'), 'ask');
    expect(controller.state!.phonePermission('get_light_level'), 'ask');
    expect(controller.state!.phonePermission('query_screen'), 'off');
    expect(controller.state!.phoneServer!['tools']['set_volume']['arguments'], {
      'stream': ['media'],
    });
    expect(
      automationList(controller.state!.config['servers']).first['id'],
      'notes',
    );
    await controller.setPhoneComfort('screen', true);
    expect(controller.state!.phonePermission('set_brightness'), 'allow');
    expect(controller.state!.phonePermission('get_light_level'), 'allow');
    expect(controller.state!.phonePermission('get_proximity'), 'allow');
    expect(controller.state!.phonePermission('set_dnd_mode'), 'ask');
    await controller.setPhoneComfort('enabled', false);
    expect(controller.state!.phoneComfortConfig['enabled'], false);
    expect(controller.state!.phonePermission('query_screen'), 'off');
  });

  for (final width in [320.0, 768.0, 1024.0, 1440.0]) {
    testWidgets('companionship switches and restore work at width $width', (
      tester,
    ) async {
      await tester.binding.setSurfaceSize(Size(width, 1600));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final repository = PhoneRepository();
      final controller = AutomationController(
        () => repository,
        onActionComplete: () async {},
      );
      addTearDown(controller.dispose);
      addTearDown(repository.close);
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
      await tester.tap(find.byKey(const Key('phone-comfort-enabled')));
      await tester.pumpAndSettle();
      expect(find.text('声音轻一点'), findsOneWidget);
      await tester.ensureVisible(find.byKey(const Key('phone-comfort-screen')));
      await tester.tap(find.byKey(const Key('phone-comfort-screen')));
      await tester.pumpAndSettle();
      expect(controller.state!.phoneComfortConfig['screen'], true);
      expect(
        tester
            .widget<ChoiceChip>(
              find.byKey(const Key('phone-comfort-cooldown-3')),
            )
            .selected,
        true,
      );
      final rules = copy(controller.state!.config)['servers'];
      await tester.ensureVisible(
        find.byKey(const Key('phone-comfort-cooldown-1')),
      );
      await tester.tap(find.byKey(const Key('phone-comfort-cooldown-1')));
      await tester.pumpAndSettle();
      expect(controller.state!.phoneComfortConfig['cooldown_minutes'], 1);
      expect(controller.state!.config['servers'], rules);
      await tester.ensureVisible(find.byKey(const Key('pause-phone-comfort')));
      await tester.tap(find.byKey(const Key('pause-phone-comfort')));
      await tester.pumpAndSettle();
      expect(find.text('现在恢复联动'), findsOneWidget);
      expect(controller.state!.phoneComfortConfig['enabled'], true);
      await tester.tap(find.byKey(const Key('pause-phone-comfort')));
      await tester.pumpAndSettle();
      expect(find.text('暂停联动 15 分钟'), findsOneWidget);
      expect(repository.controls, ['pause', 'resume']);
      repository.value['phone_comfort'] = {
        'active': [
          {
            'channel': 'screen',
            'title': '屏幕亮度',
            'status': 'applied',
            'action_id': 'displayed-action',
          },
        ],
      };
      await controller.refresh();
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('keep-phone-comfort')));
      await tester.tap(find.byKey(const Key('keep-phone-comfort')));
      await tester.pumpAndSettle();
      expect(repository.keptIds, ['displayed-action']);
      expect(repository.restores, 0);
      expect(find.byKey(const Key('keep-phone-comfort')), findsNothing);
      repository.value['phone_comfort'] = {
        'active': [
          {'channel': 'screen', 'title': '屏幕亮度'},
        ],
      };
      await controller.refresh();
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const Key('restore-phone-comfort')),
      );
      await tester.tap(find.byKey(const Key('restore-phone-comfort')));
      await tester.pumpAndSettle();
      expect(repository.restores, 1);
      expect(find.byKey(const Key('restore-phone-comfort')), findsNothing);
      expect(tester.takeException(), isNull);
    });
  }

  test('timing preferences do not expand permissions and failed pause stays unchanged', () async {
    final repository = PhoneRepository();
    final controller = AutomationController(
      () => repository,
      onActionComplete: () async {},
    );
    addTearDown(controller.dispose);
    addTearDown(repository.close);
    await controller.connectPhone();
    final before = copy(controller.state!.config);
    await controller.setPhoneComfortCooldown(5);
    expect(controller.state!.phoneComfortConfig['cooldown_minutes'], 5);
    expect(controller.state!.config['servers'], before['servers']);
    expect(controller.state!.config['loop'], before['loop']);
    expect(controller.state!.phoneComfortConfig['enabled'], isNot(true));
    repository.failControl = true;
    await controller.controlPhoneComfort('pause');
    expect(controller.error, isNotNull);
    expect(controller.state!.phoneComfortConfig['paused_until'], isNull);
    expect(controller.busy, false);
    repository.failControl = false;
    await controller.controlPhoneComfort('pause');
    expect(controller.state!.phoneComfortConfig['paused_until'], isNotNull);
    await controller.setPhoneComfort('enabled', true);
    expect(controller.state!.phoneComfortConfig['paused_until'], isNull);
  });

  testWidgets(
    'unconfirmed adjustment cannot be kept and pause controls have keyboard access',
    (tester) async {
      final repository = PhoneRepository();
      final controller = AutomationController(
        () => repository,
        onActionComplete: () async {},
      );
      addTearDown(controller.dispose);
      addTearDown(repository.close);
      await controller.connectPhone();
      await controller.setPhoneComfort('enabled', true);
      repository.value['phone_comfort'] = {
        'active': [
          {
            'channel': 'screen',
            'title': '屏幕亮度',
            'status': 'uncertain',
            'action_id': 'uncertain',
          },
        ],
      };
      await controller.refresh();
      await tester.binding.setSurfaceSize(const Size(768, 1800));
      addTearDown(() => tester.binding.setSurfaceSize(null));
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
      final keepButton = find.byKey(const Key('keep-phone-comfort'));
      expect(tester.widget<TextButton>(keepButton).onPressed, isNull);
      expect(find.textContaining('调整结果尚未确认'), findsOneWidget);
      final pause = find.byKey(const Key('pause-phone-comfort'));
      await tester.ensureVisible(pause);
      Focus.of(
        tester.element(
          find.descendant(of: pause, matching: find.byType(Text)).first,
        ),
      ).requestFocus();
      await tester.pump();
      await tester.sendKeyEvent(LogicalKeyboardKey.space);
      await tester.pumpAndSettle();
      expect(repository.controls, ['pause']);
      expect(find.text('现在恢复联动'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  test('new UI and haptic tools stay off in an existing phone connection', () {
    final state = AutomationState({
      'config': {
        'servers': [
          {
            'id': 'droid',
            'tools': {
              'tap': {'mode': 'allow'},
            },
          },
        ],
      },
      'phone': {
        'groups': [
          {
            'id': 'accessibility',
            'tools': ['tap', 'gesture', 'long_click_node'],
          },
          {
            'id': 'haptics',
            'tools': ['vibrate_pattern', 'cancel_vibration'],
          },
        ],
      },
    });
    expect(state.phonePermission('tap'), 'allow');
    expect(state.phonePermission('gesture'), 'off');
    expect(state.phonePermission('long_click_node'), 'off');
    expect(state.phonePermission('vibrate_pattern'), 'off');
    expect(state.phonePermission('cancel_vibration'), 'off');
    expect(state.phonePermission('set_volume'), 'ask');
  });

  test('phone connection and group edits preserve unrelated providers and constraints', () async {
    final repository = PhoneRepository();
    final controller = AutomationController(
      () => repository,
      onActionComplete: () async {},
    );
    addTearDown(controller.dispose);
    addTearDown(repository.close);
    await controller.connectPhone();
    expect(controller.state!.phoneServer!['enabled'], true);
    expect(controller.state!.phonePermission('query_screen'), 'off');
    expect(controller.state!.config['loop']['enabled'], false);
    expect(
      automationList(controller.state!.config['servers']).first['id'],
      'notes',
    );
    await controller.setPhoneGroupPermission('comfort', 'allow');
    expect(controller.state!.phoneServer!['tools']['set_volume'], {
      'mode': 'allow',
      'arguments': {
        'stream': ['media'],
      },
    });
    expect(controller.state!.phonePermission('query_screen'), 'off');
    await controller.disablePhone();
    expect(controller.state!.phoneServer!['enabled'], false);
    await controller.connectPhone();
    expect(controller.state!.phonePermission('set_volume'), 'allow');
    expect(repository.connections, 2);
  });

  for (final width in [320.0, 768.0, 1024.0, 1440.0]) {
    testWidgets('phone permissions remain usable at width $width', (
      tester,
    ) async {
      await tester.binding.setSurfaceSize(Size(width, 1600));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final repository = PhoneRepository();
      final controller = AutomationController(
        () => repository,
        onActionComplete: () async {},
      );
      addTearDown(controller.dispose);
      addTearDown(repository.close);
      await controller.refresh();
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
      await tester.tap(find.byKey(const Key('connect-phone')));
      await tester.pumpAndSettle();
      expect(find.text('已连接 · 在这台手机上执行'), findsOneWidget);
      expect(find.text('关闭'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('phone-permission-comfort')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('按要求直接执行'));
      await tester.pumpAndSettle();
      expect(controller.state!.phonePermission('set_volume'), 'allow');
      await tester.tap(find.text('手机权限与使用说明'));
      await tester.pumpAndSettle();
      expect(find.text('已授权，可在系统设置中撤销'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('permission button uses only explicit native settings method', (
    tester,
  ) async {
    final repository = PhoneRepository();
    final controller = AutomationController(
      () => repository,
      onActionComplete: () async {},
    );
    addTearDown(controller.dispose);
    addTearDown(repository.close);
    MethodCall? seen;
    const channel = MethodChannel('xinyu/phone');
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
      call,
    ) async {
      seen = call;
      return null;
    });
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        channel,
        null,
      ),
    );
    await controller.openPhonePermission('accessibility');
    expect(seen?.method, 'openPermissionSettings');
    expect(seen?.arguments, {'permission': 'accessibility'});
    seen = null;
    await controller.openPhonePermission('execute_shell');
    expect(seen, isNull);
  });

  test('unsupported phone cannot connect; phone result labels are independent of music', () async {
    final repository = PhoneRepository();
    repository.value['phone']['supported'] = false;
    final controller = AutomationController(
      () => repository,
      onActionComplete: () async {},
    );
    addTearDown(controller.dispose);
    addTearDown(repository.close);
    await controller.connectPhone();
    expect(repository.connections, 0);
    expect(controller.error, contains('Android 9'));
    final state = AutomationState(
      copy({
        'tools': [
          {
            'name': 'mcp_droid_fixture',
            'server_id': 'droid',
            'remote_name': 'set_volume',
          },
        ],
        'catalog': {
          'droid': [
            {'name': 'set_volume', 'description': '调整媒体音量。更多说明'},
          ],
        },
      }),
    );
    expect(state.actionTitle({'tool_name': 'mcp_droid_fixture'}), '调整媒体音量');
    expect(automationStatus('uncertain'), isNot(contains('网易云')));
  });
}

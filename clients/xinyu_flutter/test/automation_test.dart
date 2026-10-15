import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/automation.dart';
import 'package:xinyu_flutter/data/local_repository.dart';
import 'package:xinyu_flutter/data/models.dart';
import 'package:xinyu_flutter/state/automation_controller.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/ui/connected_apps.dart';

Map<String, dynamic> copy(Map<String, dynamic> value) =>
    jsonDecode(jsonEncode(value)) as Map<String, dynamic>;

class MusicRepository extends LocalRepository {
  MusicRepository() : super('http://127.0.0.1:8765');
  Map<String, dynamic> value = {
    'capabilities': {'interactive_tools': true, 'netease': true},
    'config': {
      'loop': {'enabled': false, 'max_steps': 3},
      'servers': [
        {
          'id': 'notes',
          'enabled': true,
          'tools': {
            'save': {'mode': 'ask'},
          },
        },
      ],
    },
    'catalog': <String, dynamic>{},
    'tools': [],
    'actions': [],
  };
  int templateReads = 0, connections = 0;
  String? decision;
  bool failConnect = false;

  @override
  Future<Map<String, dynamic>> automation() async => copy(value);
  @override
  Future<Map<String, dynamic>> neteaseTemplate() async {
    templateReads++;
    return {'id': 'netease', 'enabled': false, 'tools': <String, dynamic>{}};
  }

  @override
  Future<void> saveAutomation(Map<String, dynamic> config) async {
    value['config'] = copy(config);
  }

  @override
  Future<void> connectNetease() async {
    connections++;
    if (failConnect) throw const CompanionException('网易云连接失败');
    value['catalog'] = {
      'netease': [
        {'name': 'next_track', 'description': '切换到下一首歌曲'},
      ],
    };
  }

  @override
  Future<Map<String, dynamic>> decideAutomation(
    String id,
    String selected,
  ) async {
    decision = selected;
    final action = (value['actions'] as List)
        .cast<Map<String, dynamic>>()
        .single;
    action['status'] = selected == 'deny' ? 'denied' : 'succeeded';
    return {
      'continuation_error': selected == 'approve' ? '操作已执行，回复暂未完成' : null,
    };
  }
}

void main() {
  test(
    'optional tools tolerate a native connection that is not ready',
    () async {
      final controller = AutomationController(
        () => throw const CompanionException('本机引擎尚未就绪，请重新连接。'),
        onActionComplete: () async {},
      );
      addTearDown(controller.dispose);
      expect(controller.reset, returnsNormally);
      await controller.refresh(silent: true);
      expect(controller.state, isNull);
      expect(controller.loading, isFalse);
      expect(controller.busy, isFalse);
    },
  );

  test(
    'connection merges server without changing loop or existing permissions',
    () async {
      final repository = MusicRepository();
      final controller = AutomationController(
        () => repository,
        onActionComplete: () async {},
      );
      addTearDown(controller.dispose);
      addTearDown(repository.close);
      await controller.connectNetease();
      final config = repository.value['config'] as Map;
      expect(config['loop'], {'enabled': false, 'max_steps': 3});
      expect((config['servers'] as List).first['id'], 'notes');
      expect(controller.state!.permission('next_track'), 'ask');
      await controller.setPermission('next_track', 'off');
      await controller.connectNetease();
      expect(controller.state!.permission('next_track'), 'off');
      expect(repository.templateReads, 1);
      expect(repository.connections, 2);
      await controller.disableNetease();
      expect(controller.state!.netease!['enabled'], false);
      expect(controller.state!.permission('next_track'), 'off');
    },
  );

  test(
    'permission changes preserve argument allowlists and other tools',
    () async {
      final repository = MusicRepository();
      (repository.value['config']['servers'] as List).add({
        'id': 'netease',
        'enabled': true,
        'tools': {
          'next_track': {
            'mode': 'ask',
            'arguments': {
              'device': ['local'],
            },
          },
          'pause': {'mode': 'off'},
        },
      });
      repository.value['catalog'] = {
        'netease': [
          {'name': 'next_track'},
        ],
      };
      final controller = AutomationController(
        () => repository,
        onActionComplete: () async {},
      );
      addTearDown(controller.dispose);
      addTearDown(repository.close);
      await controller.setPermission('next_track', 'allow');
      final rules = controller.state!.netease!['tools'] as Map;
      expect(rules['next_track'], {
        'mode': 'allow',
        'arguments': {
          'device': ['local'],
        },
      });
      expect(rules['pause']['mode'], 'off');
    },
  );

  test(
    'failed discovery remains visible and unsupported engines cannot connect',
    () async {
      final repository = MusicRepository()..failConnect = true;
      final controller = AutomationController(
        () => repository,
        onActionComplete: () async {},
      );
      addTearDown(controller.dispose);
      addTearDown(repository.close);
      await controller.connectNetease();
      expect(controller.error, contains('连接失败'));
      expect(controller.state!.netease!['enabled'], true);
      expect(controller.state!.neteaseTools, isEmpty);
      repository.value['capabilities'] = {'netease': false};
      await controller.connectNetease();
      expect(repository.connections, 1);
      expect(controller.error, contains('Windows'));
    },
  );

  for (final decision in ['approve', 'deny', 'resume']) {
    test(
      '$decision refreshes queue and chat without another tool invocation',
      () async {
        final repository = MusicRepository();
        repository.value['actions'] = [
          {'id': 'action-1', 'status': 'pending', 'arguments': {}},
        ];
        var refreshed = 0;
        final controller = AutomationController(
          () => repository,
          onActionComplete: () async {
            refreshed++;
          },
        );
        addTearDown(controller.dispose);
        addTearDown(repository.close);
        await controller.refresh();
        expect(controller.state!.pending, hasLength(1));
        await controller.decide('action-1', decision);
        expect(repository.decision, decision);
        expect(controller.state!.pending, isEmpty);
        expect(refreshed, 1);
        expect(controller.busy, false);
        if (decision == 'approve') {
          expect(controller.notice, contains('回复暂未完成'));
        }
      },
    );
  }

  for (final width in [320.0, 768.0, 1024.0, 1440.0]) {
    testWidgets('connected apps shows approval parameters at width $width', (
      tester,
    ) async {
      await tester.binding.setSurfaceSize(Size(width, 900));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final repository = MusicRepository();
      repository.value['actions'] = [
        {
          'id': 'action-1',
          'tool_name': 'mcp_netease_next',
          'status': 'pending',
          'arguments': {'song_id': '1234567890'},
        },
      ];
      repository.value['tools'] = [
        {'name': 'mcp_netease_next', 'remote_name': 'next_track'},
      ];
      final companion = CompanionController(repository: repository);
      addTearDown(companion.dispose);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: ConnectedAppsSheet(controller: companion)),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('网易云音乐'), findsOneWidget);
      expect(find.textContaining('1234567890'), findsOneWidget);
      expect(find.byKey(const ValueKey('approve-action-1')), findsOneWidget);
      expect(tester.takeException(), isNull);
    }, variant: TargetPlatformVariant({TargetPlatform.windows}));
  }

  testWidgets(
    'Android exposes its local connection and system media permission help',
    (tester) async {
      final repository = MusicRepository();
      final companion = CompanionController(repository: repository);
      addTearDown(companion.dispose);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: ConnectedAppsSheet(controller: companion)),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('连接帮助'));
      await tester.pumpAndSettle();
      expect(find.textContaining('通知使用权'), findsOneWidget);
      final button = tester.widget<TextButton>(
        find.byKey(const Key('connect-netease')),
      );
      expect(button.onPressed, isNotNull);
      await tester.tap(find.byKey(const Key('connect-netease')));
      await tester.pumpAndSettle();
      expect(repository.connections, 1);
    },
    variant: TargetPlatformVariant({TargetPlatform.android}),
  );

  testWidgets('pending actions expose an entry directly in chat', (
    tester,
  ) async {
    final repository = MusicRepository();
    final companion = CompanionController(repository: repository);
    addTearDown(companion.dispose);
    companion.automation.state = AutomationState({
      'actions': [
        {'status': 'pending'},
      ],
    });
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: PendingAppActions(controller: companion)),
      ),
    );
    expect(find.text('1 个应用操作等你确认 · 查看详情'), findsOneWidget);
  });

  for (final decision in ['approve', 'deny']) {
    testWidgets(
      'approval sheet $decision button updates its authoritative queue',
      (tester) async {
        final repository = MusicRepository();
        repository.value['actions'] = [
          {
            'id': 'action-1',
            'tool_name': 'mcp_netease_next',
            'status': 'pending',
            'arguments': {'action': 'pause'},
          },
        ];
        repository.value['tools'] = [
          {'name': 'mcp_netease_next', 'remote_name': 'netease_control'},
        ];
        final companion = CompanionController(repository: repository);
        addTearDown(companion.dispose);
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(body: ConnectedAppsSheet(controller: companion)),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('暂停网易云音乐'), findsOneWidget);
        final button = find.byKey(ValueKey('$decision-action-1'));
        await tester.ensureVisible(button);
        await tester.tap(button);
        await tester.pumpAndSettle();
        expect(repository.decision, decision);
        expect(companion.automation.state!.pending, isEmpty);
        expect(find.byKey(const ValueKey('approve-action-1')), findsNothing);
        expect(find.byKey(const ValueKey('deny-action-1')), findsNothing);
        expect(companion.busy, false);
      },
    );
  }
}

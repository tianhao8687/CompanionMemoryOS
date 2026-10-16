import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/state/music_controller.dart';
import 'package:xinyu_flutter/ui/music_screen.dart';

import 'focus_presence_test.dart' show PresenceRepository;
import 'settings_navigation.dart';

class ListeningRepository extends PresenceRepository {
  final openRequests = <Map<String, dynamic>>[];
  @override
  Future<Map<String, dynamic>> openMusic(Map<String, dynamic> request) async {
    openRequests.add({...request});
    return {
      'status': 'succeeded',
      'delivery': 'requested',
      'playback_verified': false,
    };
  }

  final musicRequests = <Map<String, dynamic>>[];
  Completer<Map<String, dynamic>>? pendingPoll;
  Completer<Map<String, dynamic>>? pendingStart;
  Map<String, dynamic> musicState = {
    'active': true,
    'id': 'music-1',
    'conversation_id': 'test',
    'started_at': DateTime.now().toUtc().toIso8601String(),
    'quiet': false,
    'media': {
      'available': true,
      'title': '晚风里的小路',
      'artist': '示例歌手',
      'album': '心隅 · 界面测试',
      'track_key': 'synthetic-track',
      'position_ms': 36000,
      'duration_ms': 228000,
      'sampled_at_ms': DateTime.now().millisecondsSinceEpoch,
      'playback': 'playing',
      'permission': true,
      'controls': {
        'play': true,
        'pause': true,
        'next': true,
        'previous': true,
        'seek': true,
      },
    },
  };
  Map<String, dynamic> copyState() => jsonDecode(jsonEncode(musicState));
  final lyricRequests = <Map<String, dynamic>>[];
  Completer<Map<String, dynamic>>? pendingLyrics;
  @override
  Future<Map<String, dynamic>> musicLyrics(Map<String, dynamic> request) async {
    lyricRequests.add({...request});
    if (pendingLyrics != null) return pendingLyrics!.future;
    // Original synthetic text; screenshots never embed a commercial song's lyrics.
    return {
      'track_key': request['track_key'],
      'status': 'ready',
      'song_id': '123',
      'song': {'duration_ms': 228000},
      'timed': true,
      'source': '网易云音乐',
      'candidates': <Map<String, dynamic>>[],
      'lines': [
        {'time_ms': 0, 'text': '天边最后一朵云'},
        {'time_ms': 18000, 'text': '慢慢落进了黄昏'},
        {'time_ms': 35000, 'text': '晚风把今天轻轻放下'},
        {'time_ms': 52000, 'text': '陪你走过这段小路'},
        {'time_ms': 68000, 'text': '灯还亮着，不必赶路'},
        {'time_ms': 82000, 'text': '让此刻再停留一会'},
        {'time_ms': 98000, 'text': '等月光落在肩头'},
      ],
    };
  }

  @override
  Future<Map<String, dynamic>> music(Map<String, dynamic> request) async {
    musicRequests.add({...request});
    if (request['action'] == 'start' && pendingStart != null) {
      return pendingStart!.future;
    }
    if (request['action'] == 'poll' && pendingPoll != null) {
      return pendingPoll!.future;
    }
    if (request['action'] == 'quiet') musicState['quiet'] = request['quiet'];
    if (request['action'] == 'end') musicState = {'active': false};
    if (request['action'] == 'pause') {
      musicState['media']['playback'] = 'paused';
    }
    if (request['action'] == 'seek') {
      musicState['media']['position_ms'] = request['position_ms'];
      musicState['media']['sampled_at_ms'] =
          DateTime.now().millisecondsSinceEpoch;
    }
    return copyState();
  }

  @override
  Future<Map<String, dynamic>> automation() async => {
    'capabilities': {'interactive_tools': true, 'netease': true},
    'config': {
      'loop': {'enabled': true},
      'servers': [
        {'id': 'netease', 'label': '网易云音乐', 'enabled': true, 'tools': {}},
      ],
    },
    'catalog': {
      'netease': [
        {'name': 'netease_playback_state'},
        {'name': 'netease_control'},
        {'name': 'netease_search_songs'},
        {'name': 'netease_open_song'},
      ],
    },
    'tools': [],
    'actions': [],
  };
}

void main() {
  test('entering together listening reconciles a receipt already confirmed on start', () async {
    final repo = ListeningRepository();
    repo.musicState['receipt_revision'] = 1;
    var refreshes = 0;
    final c = MusicController(
      () => repo,
      () => 'test',
      composing: () => false,
      onMessage: () async {
        refreshes++;
      },
    );
    addTearDown(c.dispose);
    addTearDown(repo.close);
    await c.act('start');
    expect(refreshes, 1);
    await c.poll();
    expect(refreshes, 1);
    expect(repo.openRequests, isEmpty);
  });

  test(
    'late playback receipt refreshes song cards once without another chat',
    () async {
      final repo = ListeningRepository();
      var refreshes = 0;
      final c = MusicController(
        () => repo,
        () => 'test',
        composing: () => false,
        onMessage: () async {
          refreshes++;
        },
      );
      addTearDown(c.dispose);
      addTearDown(repo.close);
      await c.act('start');
      await c.poll();
      expect(refreshes, 0);
      repo.musicState['receipt_revision'] = 1;
      await c.poll();
      expect(refreshes, 1);
      await c.poll();
      expect(refreshes, 1);
      expect(repo.sent, isEmpty);
      expect(repo.openRequests, isEmpty);
    },
  );

  test('stale poll cannot undo quiet or resurrect an ended activity', () async {
    final repo = ListeningRepository();
    final c = MusicController(
      () => repo,
      () => 'test',
      composing: () => false,
      onMessage: () async {},
    );
    addTearDown(c.dispose);
    addTearDown(repo.close);
    await c.act('start');
    for (final action in ['quiet', 'end']) {
      final old = repo.copyState();
      repo.pendingPoll = Completer();
      final future = c.poll();
      await c.act(action, silent: true);
      repo.pendingPoll!.complete(old);
      await future;
      if (action == 'quiet') expect(c.quiet, true);
      if (action == 'end') expect(c.active, false);
    }
  });

  test(
    'background does not poll; input reports presence without a chat call',
    () async {
      final repo = ListeningRepository();
      final c = MusicController(
        () => repo,
        () => 'test',
        composing: () => false,
        onMessage: () async {},
      );
      addTearDown(c.dispose);
      addTearDown(repo.close);
      await c.act('start');
      c.composingHere = true;
      expect(repo.musicRequests.last['action'], 'activity');
      expect(repo.musicRequests.last['composing'], true);
      c.setForeground(false);
      final count = repo.musicRequests.length;
      await c.poll();
      expect(repo.musicRequests.length, count);
      expect(repo.musicRequests.last['action'], 'suspend');
      expect(repo.sent, isEmpty);
    },
  );

  for (final size in [
    (320.0, 640.0, 2.0),
    (390.0, 844.0, 1.0),
    (1280.0, 800.0, 1.0),
  ]) {
    testWidgets(
      'music controls, quiet and keyboard fit $size',
      (t) async {
        t.view.physicalSize = Size(size.$1, size.$2);
        t.view.devicePixelRatio = 1;
        t.platformDispatcher.textScaleFactorTestValue = size.$3;
        addTearDown(t.view.resetPhysicalSize);
        addTearDown(t.view.resetDevicePixelRatio);
        addTearDown(t.platformDispatcher.clearTextScaleFactorTestValue);
        final repo = ListeningRepository();
        final c = CompanionController(repository: repo);
        addTearDown(c.dispose);
        await t.pumpWidget(XinYuApp(controller: c));
        await t.pumpAndSettle();
        await composeAction(t, 'open-music');
        expect(repo.openRequests, hasLength(1));
        expect(find.text('晚风里的小路'), findsOneWidget);
        expect(repo.sent, isEmpty);
        await t.ensureVisible(find.byKey(const Key('music-pause')));
        await t.tap(find.byKey(const Key('music-pause')));
        await t.pumpAndSettle();
        expect(c.music.playing, false);
        await t.ensureVisible(find.byKey(const Key('music-quiet')));
        await t.tap(find.byKey(const Key('music-quiet')));
        await t.pumpAndSettle();
        expect(c.music.quiet, true);
        c.music.setForeground(false);
        c.music.setForeground(true);
        await t.pumpAndSettle();
        expect(repo.openRequests, hasLength(1));
        expect(find.text('可以说点话'), findsOneWidget);
        t.view.viewInsets = const FakeViewPadding(bottom: 260);
        addTearDown(t.view.resetViewInsets);
        await t.pumpAndSettle();
        await t.enterText(find.byKey(const Key('music-message')), '这首歌陪我坐一会儿。');
        await t.tap(find.byKey(const Key('music-send')));
        await t.pumpAndSettle();
        expect(repo.sent.single['text'], '这首歌陪我坐一会儿。');
        expect(t.takeException(), isNull);
        await c.music.act('end');
        c.focus.connect(false);
        await t.pumpWidget(const SizedBox());
      },
      variant: TargetPlatformVariant({
        size.$1 < 600 ? TargetPlatform.android : TargetPlatform.windows,
      }),
    );
  }

  for (final platform in [TargetPlatform.android, TargetPlatform.windows]) {
    testWidgets('open player once per route entry on $platform', (t) async {
      final repo = ListeningRepository();
      final c = CompanionController(repository: repo);
      addTearDown(c.dispose);
      await t.pumpWidget(XinYuApp(controller: c));
      await t.pumpAndSettle();
      expect(repo.openRequests, isEmpty);
      await composeAction(t, 'open-music');
      expect(repo.openRequests, hasLength(1));
      await c.music.poll();
      await t.pump(const Duration(milliseconds: 100));
      expect(repo.openRequests, hasLength(1));
      await t.tap(find.byTooltip('返回聊天'));
      await t.pumpAndSettle();
      expect(c.music.active, isTrue);
      await composeAction(t, 'open-music');
      expect(repo.openRequests, hasLength(2));
      expect(
        repo.musicRequests.where((r) => r['action'] == 'start'),
        hasLength(1),
      );
      expect(
        repo.openRequests[0]['request_id'],
        isNot(repo.openRequests[1]['request_id']),
      );
      await c.music.act('end');
      c.focus.connect(false);
      await t.pumpWidget(const SizedBox());
    }, variant: TargetPlatformVariant({platform}));
  }

  testWidgets('leaving during startup does not launch the external player', (
    t,
  ) async {
    final repo = ListeningRepository()..pendingStart = Completer();
    final c = CompanionController(repository: repo);
    addTearDown(c.dispose);
    await t.pumpWidget(XinYuApp(controller: c));
    await t.pumpAndSettle();
    final context = t.element(find.byType(Scaffold).first);
    final route = showMusicScreen(context, c);
    await t.pumpAndSettle();
    await t.tap(find.byTooltip('返回聊天'));
    await t.pumpAndSettle();
    await route;
    repo.pendingStart!.complete(repo.copyState());
    await t.pumpAndSettle();
    expect(repo.openRequests, isEmpty);
    await c.music.act('end');
    c.focus.connect(false);
    await t.pumpWidget(const SizedBox());
  });
}

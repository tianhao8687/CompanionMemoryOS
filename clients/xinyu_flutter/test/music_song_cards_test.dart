import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/models.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/ui/chat.dart';
import 'package:xinyu_flutter/ui/glass.dart';
import 'package:xinyu_flutter/ui/music_song_cards.dart';
import 'package:xinyu_flutter/ui/typography.dart';

import 'focus_presence_test.dart' show PresenceRepository;

const cards = [
  {
    'id': '123',
    'name': '月光落进小小纸船',
    'artists': ['合成歌手'],
    'album': '沿着晚风回家',
    'search_action_id': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'lyric_match': true,
    'state': 'candidate',
  },
  {
    'id': '124',
    'name': '月光落进小小纸船（现场版）',
    'artists': ['合成歌手'],
    'album': '一次小小的音乐会',
    'search_action_id': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'lyric_match': true,
    'state': 'candidate',
  },
];

class SongRepository extends PresenceRepository {
  final picks = <Map<String, dynamic>>[];
  final decisions = <String>[];
  Completer<Map<String, dynamic>>? gatePick;
  @override
  Future<Map<String, dynamic>> automation() async => {};
  @override
  Future<Map<String, dynamic>> pickMusic(Map<String, dynamic> request) async {
    picks.add(request);
    return gatePick == null
        ? {
            'operation': {'status': 'succeeded'},
            'state': 'requested',
          }
        : await gatePick!.future;
  }

  @override
  Future<Map<String, dynamic>> decideAutomation(
    String id,
    String decision,
  ) async {
    decisions.add('$id:$decision');
    return {};
  }

  @override
  Future<MessagePage> messages(String conversation, {int? before}) async =>
      const MessagePage([]);
}

Future<CompanionController> mount(
  WidgetTester tester,
  SongRepository repo, {
  double width = 390,
  double scale = 1,
  List<Map<String, dynamic>> values = cards,
  GlobalKey? boundary,
}) async {
  tester.view.physicalSize = Size(width, 1000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final c = CompanionController(repository: repo);
  addTearDown(c.dispose);
  await c.initialize();
  c.focus.connect(false);
  final line = ChatLine.fromJson({
    'id': 'song-reply',
    'content': '找到这首了，你想听哪个版本？',
    'role': 'assistant',
    'sequence': 2,
    'music_cards': values,
  });
  expect(line.withBookmark(true).musicCards, values);
  await tester.pumpWidget(
    MaterialApp(
      theme: ThemeData(
        fontFamily: XinYuTypography.family,
        textTheme: XinYuTypography.forPlatform(
          width < 768 ? TargetPlatform.android : TargetPlatform.windows,
        ),
        colorScheme: ColorScheme.fromSeed(seedColor: XinYuColors.accent)
            .copyWith(
              surface: XinYuColors.canvas,
              onSurface: XinYuColors.ink,
              primary: XinYuColors.accent,
            ),
      ),
      home: MediaQuery(
        data: MediaQueryData(
          size: Size(width, 1000),
          textScaler: TextScaler.linear(scale),
        ),
        child: Scaffold(
          body: RepaintBoundary(
            key: boundary,
            child: ColoredBox(
              color: XinYuColors.canvas,
              child: ListenableBuilder(
                listenable: c,
                builder: (context, _) => SingleChildScrollView(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: MessageBubble(line: line, controller: c, name: '小禾'),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
  return c;
}

void main() {
  testWidgets('unconfirmed playback is distinct from permission approval', (
    tester,
  ) async {
    final repo = SongRepository();
    await mount(
      tester,
      repo,
      values: [
        {...cards.first, 'state': 'not_started'},
        {...cards.last, 'state': 'paused'},
      ],
    );
    expect(find.text('网易云仍在其他歌曲 · 这首尚未开始'), findsOneWidget);
    expect(find.text('已切到这首歌 · 网易云处于暂停状态'), findsOneWidget);
    expect(find.textContaining('待确认'), findsNothing);
    expect(find.text('确认播放'), findsNothing);
    expect(repo.picks, isEmpty);
  });

  TestWidgetsFlutterBinding.ensureInitialized();
  const destination = String.fromEnvironment('MUSIC_REVIEW_DIR');
  setUpAll(() async {
    if (destination.isEmpty) return;
    await (FontLoader(
      XinYuTypography.family,
    )..addFont(rootBundle.load(XinYuTypography.fontAsset))).load();
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  });
  for (final width in [320.0, 768.0, 1024.0, 1440.0]) {
    testWidgets('song cards fit $width and doubled text', (tester) async {
      await mount(tester, SongRepository(), width: width, scale: 2);
      expect(find.text('月光落进小小纸船'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
  testWidgets('click picks exact candidate once and does not send chat', (
    tester,
  ) async {
    final repo = SongRepository()..gatePick = Completer();
    await mount(tester, repo);
    final button = find.byKey(const ValueKey('play-song-123'));
    await tester.tap(button);
    await tester.pump();
    expect(find.text('正在交给网易云…'), findsOneWidget);
    await tester.tap(button);
    expect(repo.picks, hasLength(1));
    expect(repo.picks.single['song_id'], '123');
    expect(repo.picks.single['conversation_id'], 'test');
    expect(repo.sent, isEmpty);
    repo.gatePick!.complete({
      'operation': {'status': 'succeeded'},
      'state': 'requested',
    });
    await tester.pumpAndSettle();
  });
  testWidgets(
    'comfort card shows one chosen song without another playback on render',
    (tester) async {
      final repo = SongRepository();
      await mount(
        tester,
        repo,
        width: 320,
        scale: 2,
        values: [
          {...cards.first, 'state': 'verified', 'comfort': true},
        ],
      );
      expect(find.text('陪你缓一缓'), findsOneWidget);
      expect(find.text('已确认开始播放'), findsOneWidget);
      expect(repo.picks, isEmpty);
      expect(repo.decisions, isEmpty);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('pending card confirms existing action without a second open', (
    tester,
  ) async {
    final repo = SongRepository();
    await mount(
      tester,
      repo,
      values: [
        {...cards.first, 'state': 'pending', 'pending_action_id': 'pending-1'},
      ],
    );
    await tester.tap(find.text('确认播放'));
    await tester.pumpAndSettle();
    expect(repo.decisions, ['pending-1:approve']);
    expect(repo.picks, isEmpty);
  });
  testWidgets('uncertain playback cannot be retried by card', (tester) async {
    final repo = SongRepository();
    await mount(
      tester,
      repo,
      values: [
        {...cards.first, 'state': 'uncertain'},
      ],
    );
    expect(find.text('结果待核对，请先查看网易云'), findsOneWidget);
    expect(
      tester
          .widget<TextButton>(find.byKey(const ValueKey('play-song-123')))
          .onPressed,
      isNull,
    );
    expect(songReceipt('requested'), isNot(contains('已确认')));
  });
  testWidgets('real bundled font song card review', (tester) async {
    if (destination.isEmpty) return;
    final key = GlobalKey();
    await mount(tester, SongRepository(), boundary: key);
    await tester.runAsync(() async {
      final render =
          key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
      final image = await render.toImage(pixelRatio: 1.5);
      final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
      await Directory(destination).create(recursive: true);
      await File('$destination/song-card-phone.png')
          .writeAsBytes(bytes!.buffer.asUint8List());
      image.dispose();
    });
  });
}

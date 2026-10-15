import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/state/music_lyric_clock.dart';
import 'package:xinyu_flutter/ui/music_lyrics.dart';
import 'package:xinyu_flutter/ui/music_transport.dart';

import 'music_test.dart' show ListeningRepository;
import 'music_playback_test.dart' show controller;

void main() {
  testWidgets(
    'native timeline scrolls to the current lyric and manual browsing can resume following',
    (t) async {
      final repo = ListeningRepository();
      final music = controller(repo);
      addTearDown(music.dispose);
      addTearDown(repo.close);
      await music.act('start');
      await t.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Center(
              child: SizedBox(
                width: 350,
                height: 280,
                child: ListenableBuilder(
                  listenable: music,
                  builder: (_, _) => MusicLyrics(music: music),
                ),
              ),
            ),
          ),
        ),
      );
      await t.pumpAndSettle();
      repo.musicState['media']['position_ms'] = 98000;
      await music.poll();
      await t.pumpAndSettle();
      final list = find.byKey(const Key('music-lyrics-scroll'));
      final scroller = t.widget<SingleChildScrollView>(list).controller!;
      expect(scroller.offset, greaterThan(150));
      final current = t.getCenter(find.byKey(const Key('music-lyric-6')));
      expect(
        current.dy,
        inInclusiveRange(t.getTopLeft(list).dy, t.getBottomRight(list).dy),
      );
      // A real position read from the Windows fallback has identical sync behavior,
      // including an external backward seek; it does not require a lyric tap.
      repo.musicState['media']['timeline_source'] = 'netease_local_clock';
      repo.musicState['media']['position_ms'] = 36000;
      repo.musicState['media']['playback'] = 'paused';
      await music.poll();
      await t.pumpAndSettle();
      expect(scroller.offset, lessThan(150));
      expect(find.textContaining('歌词自动跟随'), findsOneWidget);
      expect(find.textContaining('手动对齐'), findsNothing);
      await t.drag(list, const Offset(0, 120));
      await t.pumpAndSettle();
      expect(find.text('回到当前歌词'), findsOneWidget);
      await t.tap(find.text('回到当前歌词'));
      await t.pumpAndSettle();
      expect(find.text('回到当前歌词'), findsNothing);
      await music.act('end');
      await t.pumpWidget(const SizedBox());
    },
  );

  test('user-aligned clock follows play/pause and clears on another track or disconnect', () {
    var now = 0;
    final clock = MusicLyricClock(milliseconds: () => now);
    clock.observe('song-a', true);
    expect(clock.position, isNull);
    clock.align(35000);
    now = 6000;
    expect(clock.position, 41000);
    clock.observe('song-a', false);
    now = 16000;
    expect(clock.position, 41000);
    clock.observe('song-a', true);
    now = 19000;
    expect(clock.position, 44000);
    clock.observe('song-b', true);
    expect(clock.position, isNull);
    clock.align(10000);
    clock.observe(null, false);
    expect(clock.position, isNull);
  });

  testWidgets(
    'calibrating lyrics never changes playback and selecting lyrics never sends a chat',
    (t) async {
      final repo = ListeningRepository();
      repo.musicState['media'].remove('position_ms');
      final c = controller(repo);
      addTearDown(c.dispose);
      addTearDown(repo.close);
      await c.act('start');
      String? draft;
      await t.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Center(
              child: SizedBox(
                width: 400,
                height: 400,
                child: ListenableBuilder(
                  listenable: c,
                  builder: (_, _) =>
                      MusicLyrics(music: c, onQuote: (v) => draft = v),
                ),
              ),
            ),
          ),
        ),
      );
      await t.pumpAndSettle();
      expect(find.text('暂未同步到进度 · 可点歌词手动对齐'), findsOneWidget);
      await t.ensureVisible(find.byKey(const Key('music-lyric-2')));
      await t.tap(find.byKey(const Key('music-lyric-2')));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('music-align-lyric')));
      await t.pumpAndSettle();
      expect(c.lyricsPositionMs(), greaterThanOrEqualTo(35000));
      expect(c.positionMs(), isNull);
      expect(repo.musicRequests.any((r) => r['action'] == 'seek'), false);
      await t.tap(find.byKey(const Key('music-lyric-2')));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('music-quote-lyric')));
      await t.pumpAndSettle();
      expect(draft, contains('晚风把今天轻轻放下'));
      expect(repo.sent, isEmpty);
      repo.musicState['media']['track_key'] = 'other';
      await c.poll();
      expect(c.lyricsPositionMs(), isNull);
      await c.act('end');
      await t.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'seek slider submits one current-track action and disappears without capability',
    (t) async {
      final repo = ListeningRepository();
      final music = controller(repo);
      addTearDown(music.dispose);
      addTearDown(repo.close);
      await music.act('start');
      await t.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Center(
              child: SizedBox(
                width: 400,
                child: ListenableBuilder(
                  listenable: music,
                  builder: (_, _) => MusicTransport(music: music),
                ),
              ),
            ),
          ),
        ),
      );
      await t.pump();
      final slider = find.byKey(const Key('music-seek'));
      await t.drag(slider, const Offset(70, 0));
      await t.pumpAndSettle();
      final calls = repo.musicRequests
          .where((r) => r['action'] == 'seek')
          .toList();
      expect(calls, hasLength(1));
      expect(calls.single['track_key'], 'synthetic-track');
      expect(calls.single['position_ms'], inInclusiveRange(0, 228000));
      repo.musicState['media']['controls']['seek'] = false;
      await music.poll();
      await t.pump();
      expect(slider, findsNothing);
      expect(find.text('播放进度请在网易云内调整'), findsOneWidget);
      await music.act('end');
      await t.pumpWidget(const SizedBox());
    },
  );
}

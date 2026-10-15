import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/state/music_controller.dart';
import 'package:xinyu_flutter/ui/music_record.dart';

import 'music_test.dart' show ListeningRepository;

MusicController controller(ListeningRepository repo) => MusicController(
  () => repo,
  () => 'test',
  composing: () => false,
  onMessage: () async {},
);

void main() {
  testWidgets(
    'record rotates only while playing and resumes from its stopped angle',
    (t) async {
      Future<void> scene({
        bool playing = true,
        bool reduced = false,
        bool visible = true,
      }) async {
        await t.pumpWidget(
          MaterialApp(
            home: MediaQuery(
              data: MediaQueryData(disableAnimations: reduced),
              child: TickerMode(
                enabled: visible,
                child: MusicRecord(size: 260, playing: playing),
              ),
            ),
          ),
        );
      }

      double angle() => t
          .widget<RotationTransition>(
            find.byKey(const Key('music-record-rotation')),
          )
          .turns
          .value;
      await scene();
      await t.pump(const Duration(seconds: 2));
      final playing = angle();
      expect(playing, greaterThan(0));
      await scene(playing: false);
      await t.pump(const Duration(seconds: 2));
      expect(angle(), playing);
      await scene();
      await t.pump(const Duration(seconds: 1));
      expect(angle(), greaterThan(playing));
      final resumed = angle();
      await scene(reduced: true);
      await t.pump(const Duration(seconds: 1));
      expect(angle(), resumed);
      await scene(visible: false);
      await t.pump(const Duration(seconds: 1));
      expect(angle(), resumed);
      await t.pumpWidget(const SizedBox());
    },
  );

  test(
    'late lyrics cannot replace the next song or reappear after ending',
    () async {
      final repo = ListeningRepository();
      final music = controller(repo);
      addTearDown(music.dispose);
      addTearDown(repo.close);
      final first = Completer<Map<String, dynamic>>();
      repo.pendingLyrics = first;
      await music.act('start');
      final second = Completer<Map<String, dynamic>>();
      repo.pendingLyrics = second;
      repo.musicState['media']['track_key'] = 'second';
      await music.poll();
      second.complete({
        'track_key': 'second',
        'status': 'ready',
        'song_id': '456',
      });
      await Future<void>.delayed(Duration.zero);
      first.complete({
        'track_key': 'synthetic-track',
        'status': 'ready',
        'song_id': '123',
      });
      await Future<void>.delayed(Duration.zero);
      expect(music.lyrics.value['song_id'], '456');
      final count = repo.lyricRequests.length;
      await music.poll();
      expect(repo.lyricRequests.length, count);
      final late = Completer<Map<String, dynamic>>();
      repo.pendingLyrics = late;
      final fetch = music.lyrics.fetch();
      await music.act('end');
      late.complete({
        'track_key': 'second',
        'status': 'ready',
        'song_id': '456',
      });
      await fetch;
      expect(music.lyrics.value, isEmpty);
    },
  );

  test('real timeline interpolation stops on pause and expires if the provider stops updating', () async {
    final repo = ListeningRepository();
    final c = controller(repo);
    addTearDown(c.dispose);
    addTearDown(repo.close);
    await c.act('start');
    final sample = DateTime.fromMillisecondsSinceEpoch(
      c.media['sampled_at_ms'] as int,
    );
    expect(c.positionMs(sample.add(const Duration(seconds: 2))), 38000);
    expect(c.positionMs(sample.add(const Duration(seconds: 30))), isNull);
    await c.act('pause');
    expect(c.positionMs(sample.add(const Duration(seconds: 2))), 36000);
    repo.musicState['media']['playback'] = 'playing';
    await c.poll();
    c.setForeground(false);
    expect(c.visualPlaying, false);
    repo.musicState['media'].remove('position_ms');
    c.state = repo.copyState();
    expect(c.positionMs(sample), isNull);
  });
}

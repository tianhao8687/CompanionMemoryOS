import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/demo_repository.dart';
import 'package:xinyu_flutter/data/local_speech_input.dart';
import 'package:xinyu_flutter/data/speech_models.dart';
import 'package:xinyu_flutter/data/speech_input.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/state/voice_input.dart';
import 'package:xinyu_flutter/ui/chat.dart';
import 'package:xinyu_flutter/ui/voice_input_sheet.dart';
import 'package:xinyu_flutter/ui/typography.dart';

class FakeModels extends SpeechModels {
  int checks = 0, downloads = 0;
  @override
  Future<void> inspect() async {
    checks++;
    phase = SpeechModelPhase.missing;
    notifyListeners();
  }

  @override
  Future<void> download() async {
    downloads++;
    phase = SpeechModelPhase.ready;
    notifyListeners();
  }
}

class FakeSpeech implements SpeechInput {
  int initializations = 0, starts = 0, stops = 0, cancels = 0;
  bool available = true;
  Completer<bool>? permission;
  SpeechResult? result;
  void Function(String)? status, error;
  String? requestedLocale;
  @override
  Future<bool> initialize({
    required void Function(String) onStatus,
    required void Function(String) onError,
  }) async {
    initializations++;
    status = onStatus;
    error = onError;
    return permission?.future ?? available;
  }

  @override
  Future<List<({String id, String name})>> languages() async => [
    (id: 'en_US', name: 'English'),
    (id: 'zh_CN', name: '普通话'),
  ];
  @override
  Future<void> listen({
    required String? locale,
    required SpeechResult onResult,
  }) async {
    starts++;
    requestedLocale = locale;
    result = onResult;
  }

  @override
  Future<void> stop() async {
    stops++;
  }

  @override
  Future<void> cancel() async {
    cancels++;
  }
}

Future<CompanionController> composer(
  WidgetTester tester,
  FakeSpeech speech,
) async {
  final controller = CompanionController(
    repository: DemoRepository(),
    speechInput: speech,
  );
  await controller.initialize();
  await tester.pumpWidget(
    MaterialApp(
      theme: ThemeData(fontFamily: XinYuTypography.family),
      home: Scaffold(
        body: Align(
          alignment: Alignment.bottomCenter,
          child: Composer(controller: controller),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
  return controller;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    if (Platform.environment['XINYU_VOICE_PREVIEW'] == null) return;
    await (FontLoader(
      XinYuTypography.family,
    )..addFont(rootBundle.load(XinYuTypography.fontAsset))).load();
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  });

  testWidgets(
    'local resources require an explicit download, no API key or automatic recording',
    (tester) async {
      final models = FakeModels();
      final voice = VoiceInput(input: LocalSpeechInput(models: models))
        ..text = '今天想说的话';
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: VoiceInputSheet(voice: voice, insert: (_) => null),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(models.checks, 1);
      expect(models.downloads, 0);
      expect(find.textContaining('API Key'), findsNothing);
      expect(find.byKey(const Key('voice-api-key')), findsNothing);
      expect(
        tester
            .widget<FilledButton>(find.byKey(const Key('voice-listen')))
            .onPressed,
        isNull,
      );
      await tester.tap(find.byKey(const Key('voice-download')));
      await tester.pumpAndSettle();
      expect(models.downloads, 1);
      expect(voice.phase, VoicePhase.ready);
      expect(voice.text, '今天想说的话');
      expect(
        tester
            .widget<FilledButton>(find.byKey(const Key('voice-listen')))
            .onPressed,
        isNotNull,
      );
      expect(find.text('离线语音已就绪 · 中英文'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      voice.dispose();
    },
  );
  testWidgets(
    'partial results replace; edits and subsequent segments are retained',
    (tester) async {
      final speech = FakeSpeech();
      final voice = VoiceInput(input: speech);
      await voice.start();
      expect(speech.requestedLocale, 'zh_CN');
      speech.result!('今天', false);
      speech.result!('今天有点累', true);
      expect(voice.text, '今天有点累');
      expect(voice.phase, VoicePhase.review);
      voice.edit('今天有点累，但也很开心。');
      final previous = speech.result!;
      await voice.start();
      previous('迟到的旧结果', true);
      expect(voice.phase, VoicePhase.listening);
      speech.result!('想和你聊聊', true);
      expect(voice.text, '今天有点累，但也很开心。\n想和你聊聊');
      voice.dispose();
    },
  );

  testWidgets(
    'closing during permission wait never starts microphone afterwards',
    (tester) async {
      final speech = FakeSpeech()..permission = Completer<bool>();
      final voice = VoiceInput(input: speech);
      final started = voice.start();
      await tester.pump();
      voice.close();
      speech.permission!.complete(true);
      await started;
      expect(speech.starts, 0);
      expect(voice.text, isEmpty);
      voice.dispose();
    },
  );

  testWidgets(
    'missing recognizer and errors retain editable text; no automatic retry',
    (tester) async {
      final speech = FakeSpeech()..available = false;
      final voice = VoiceInput(input: speech)..edit('已有的语音草稿');
      await voice.start();
      expect(voice.phase, VoicePhase.error);
      expect(voice.text, '已有的语音草稿');
      expect(speech.starts, 0);
      speech.available = true;
      await voice.start();
      speech.error!('voice_decode');
      expect(voice.message, contains('本地语音'));
      expect(voice.text, '已有的语音草稿');
      await tester.pump(const Duration(seconds: 5));
      expect(speech.starts, 1);
      voice.dispose();
    },
  );

  testWidgets('stop waits for final result and bounds a missing callback', (
    tester,
  ) async {
    final speech = FakeSpeech();
    final voice = VoiceInput(input: speech);
    await voice.start();
    speech.result!('晚安', false);
    await voice.stop();
    expect(voice.phase, VoicePhase.finishing);
    speech.result!('晚安，明天见。', true);
    expect(voice.text, '晚安，明天见。');
    await voice.start();
    speech.result!('再补一句', false);
    speech.status!('notListening');
    await tester.pump(const Duration(seconds: 21));
    expect(voice.phase, VoicePhase.error);
    expect(voice.message, contains('未能识别完成'));
    expect(voice.text, endsWith('再补一句'));
    voice.dispose();
  });

  testWidgets(
    'microphone entry is lazy; reviewed text inserts at selection without sending',
    (tester) async {
      final speech = FakeSpeech();
      final c = await composer(tester, speech);
      await tester.enterText(find.byKey(const Key('message-input')), '今天的事');
      final input = tester
          .widget<TextField>(find.byKey(const Key('message-input')))
          .controller!;
      input.selection = const TextSelection.collapsed(offset: 2);
      final history = c.messages.length;
      await tester.tap(find.byKey(const Key('voice-input')));
      await tester.pumpAndSettle();
      expect(speech.initializations, 0);
      await tester.tap(find.byKey(const Key('voice-listen')));
      await tester.pumpAndSettle();
      speech.result!('很开心', false);
      await tester.pump();
      expect(c.composerText, '今天的事');
      expect(
        tester
            .widget<OutlinedButton>(find.byKey(const Key('voice-insert')))
            .onPressed,
        isNull,
      );
      speech.result!('很开心', true);
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('voice-preview')), '最开心');
      await tester.tap(find.byKey(const Key('voice-insert')));
      await tester.pumpAndSettle();
      expect(c.composerText, '今天最开心的事');
      expect(c.messages.length, history);
      expect(c.collecting, isFalse);
      await tester.pumpWidget(const SizedBox());
      c.dispose();
    },
  );

  testWidgets(
    'background stops recognition; late callbacks cannot overwrite preview',
    (tester) async {
      final speech = FakeSpeech();
      final c = await composer(tester, speech);
      await tester.tap(find.byKey(const Key('voice-input')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('voice-listen')));
      await tester.pumpAndSettle();
      speech.result!('保留这句话', false);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump();
      speech.result!('不应写入', true);
      expect(c.voice.text, '保留这句话');
      expect(c.voice.active, isFalse);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      expect(speech.starts, 1);
      await tester.pumpWidget(const SizedBox());
      c.dispose();
    },
  );

  testWidgets(
    'changed conversation or draft does not receive stale voice text',
    (tester) async {
      final speech = FakeSpeech();
      final c = await composer(tester, speech);
      await tester.enterText(find.byKey(const Key('message-input')), '原草稿');
      await tester.tap(find.byKey(const Key('voice-input')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('voice-listen')));
      await tester.pumpAndSettle();
      speech.result!('补充', true);
      await tester.pumpAndSettle();
      c.updateComposer('从其他入口更新的草稿');
      await tester.tap(find.byKey(const Key('voice-insert')));
      await tester.pumpAndSettle();
      expect(c.composerText, '从其他入口更新的草稿');
      expect(find.textContaining('对话或草稿已经变化'), findsOneWidget);
      expect(c.voice.text, '补充');
      await tester.pumpWidget(const SizedBox());
      c.dispose();
    },
  );

  testWidgets(
    'narrow large-text sheet scrolls without overflow; real widget preview',
    (tester) async {
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final voice = VoiceInput(input: FakeSpeech())
        ..edit('今天开会的时候有点紧张，\n不过最后还是把自己的想法说出来了。');
      final boundary = GlobalKey();
      await tester.pumpWidget(
        MaterialApp(
          theme: ThemeData(fontFamily: XinYuTypography.family),
          home: MediaQuery(
            data: const MediaQueryData(
              size: Size(360, 800),
              textScaler: TextScaler.linear(1.8),
            ),
            child: Scaffold(
              body: RepaintBoundary(
                key: boundary,
                child: Align(
                  alignment: Alignment.bottomCenter,
                  child: VoiceInputSheet(voice: voice, insert: (_) => null),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      final output = Platform.environment['XINYU_VOICE_PREVIEW'];
      if (output != null) {
        await tester.runAsync(() async {
          final image =
              await (boundary.currentContext!.findRenderObject()!
                      as RenderRepaintBoundary)
                  .toImage();
          final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
          await File(output).writeAsBytes(bytes!.buffer.asUint8List());
          image.dispose();
        });
      }
      await tester.pumpWidget(const SizedBox());
      voice.dispose();
    },
  );

  testWidgets('local download panel fits a narrow large-text screen', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(360, 800));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final models = FakeModels();
    final voice = VoiceInput(input: LocalSpeechInput(models: models));
    final boundary = GlobalKey();
    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(fontFamily: XinYuTypography.family),
        home: MediaQuery(
          data: const MediaQueryData(
            size: Size(360, 800),
            textScaler: TextScaler.linear(1.8),
          ),
          child: Scaffold(
            body: RepaintBoundary(
              key: boundary,
              child: Align(
                alignment: Alignment.bottomCenter,
                child: VoiceInputSheet(voice: voice, insert: (_) => null),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final output = Platform.environment['XINYU_VOICE_PREVIEW'];
    if (output != null) {
      await tester.runAsync(() async {
        final render =
            boundary.currentContext!.findRenderObject()!
                as RenderRepaintBoundary;
        final image = await render.toImage();
        final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
        await File(output.replaceFirst('.png', '-local.png'))
            .writeAsBytes(bytes!.buffer.asUint8List());
        image.dispose();
      });
    }
    await tester.ensureVisible(find.byKey(const Key('voice-download')));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    voice.dispose();
  });
}

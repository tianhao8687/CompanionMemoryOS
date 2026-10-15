import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:xinyu_flutter/data/local_repository.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';

// Manual acceptance only. The caller owns a bounded, explicitly authorized
// ManagedInstance. This entry point has no daily-data or offline fallback.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const endpoint = String.fromEnvironment('XINYU_LIVE_ENDPOINT');
  const evidence = String.fromEnvironment('XINYU_LIVE_EVIDENCE');
  const resume = bool.fromEnvironment('XINYU_LIVE_RESUME');
  const afterNoAdvice = bool.fromEnvironment('XINYU_LIVE_AFTER_NO_ADVICE');
  testWidgets(
    'focus controls use real current-conversation replies',
    (t) async {
      final uri = Uri.parse(endpoint);
      expect(uri.host, '127.0.0.1');
      final c = CompanionController(repository: LocalRepository(endpoint));
      final rows = <Map<String, Object?>>[];
      Future<void> save() async =>
          File(evidence)
              .writeAsString(const JsonEncoder.withIndent('  ').convert(rows));
      Future<void> waitFor(bool Function() ready) async {
        final watch = Stopwatch()..start();
        while (!ready() && watch.elapsed.inSeconds < 85) {
          await t.pump(const Duration(milliseconds: 100));
          await Future<void>.delayed(const Duration(milliseconds: 100));
        }
        expect(
          ready(),
          isTrue,
          reason: c.error ?? 'UI operation exceeded 85 s',
        );
        await t.pump(const Duration(milliseconds: 300));
      }

      Future<void> tap(String key) async {
        await t.pumpAndSettle();
        final f = find.byKey(Key(key));
        await t.ensureVisible(f);
        await t.pumpAndSettle();
        await t.tap(f);
        await t.pump(const Duration(milliseconds: 400));
      }

      Future<void> reply(String name, Future<void> Function() action) async {
        final count = c.messages.length;
        final watch = Stopwatch()..start();
        try {
          await action();
          await waitFor(() => !c.busy);
          expect(c.error, isNull);
          expect(c.messages.length, greaterThan(count));
          expect(c.messages.last.isUser, isFalse);
          rows.add({
            'case': name,
            'seconds': watch.elapsedMilliseconds / 1000,
            'messages': c.messages
                .skip(count)
                .map(
                  (m) => {
                    'id': m.id,
                    'role': m.isUser ? 'user' : 'assistant',
                    'content': m.text,
                  },
                )
                .toList(),
            'phase': c.focus.session?.phase,
          });
          await save();
        } catch (error) {
          rows.add({'case': name, 'status': 'failed', 'reason': '$error'});
          await save();
          rethrow;
        }
      }

      Future<void> discuss(String name, String text) async {
        await t.ensureVisible(find.byKey(const Key('focus-chat-input')));
        await t.pumpAndSettle();
        await t.tap(find.byKey(const Key('focus-chat-input')));
        await t.pumpAndSettle();
        await t.enterText(find.byKey(const Key('focus-chat-input')), text);
        await t.pumpAndSettle();
        expect(
          t
              .widget<TextField>(find.byKey(const Key('focus-chat-input')))
              .controller!
              .text,
          text,
        );
        expect(
          t
              .widget<FilledButton>(find.byKey(const Key('focus-chat-send')))
              .onPressed,
          isNotNull,
        );
        await reply(name, () => tap('focus-chat-send'));
      }

      try {
        await t.pumpWidget(XinYuApp(controller: c));
        await waitFor(() => c.active != null && !c.loading);
        if (!resume) {
          await t.enterText(
            find.byKey(const Key('message-input')),
            '今天要写手作杯子的商品介绍，但我一直盯着空白页。别给我打鸡血，跟我正常聊就好。',
          );
          await reply('opening', () => tap('send-message'));
          await tap('open-focus');
          await t.enterText(find.byKey(const Key('focus-task')), '写手作杯子的商品介绍');
          await tap('focus-start');
          await waitFor(() => c.focus.session != null && !c.focus.busy);
          await reply('touch', () => tap('focus-touch'));
        } else {
          await tap('open-focus');
          await waitFor(() => c.focus.session != null && !c.focus.busy);
        }
        await tap('focus-choose-step');
        await t.enterText(
          find.byKey(const Key('focus-step-input')),
          '写一句杯沿的触感',
        );
        await reply(
          resume ? 'reselect_after_reopen' : 'choose_step',
          () => tap('focus-step-save'),
        );
        await tap('focus-stuck');
        await waitFor(
          () => find.byKey(const Key('focus-chat-input')).evaluate().isNotEmpty,
        );
        expect(c.focus.session!.paused, isTrue);
        if (!resume) {
          await discuss(
            'specific_obstacle',
            '不是不知道怎么写，是我刚写的“每一口都很温暖”看着好傻，自己都不信。',
          );
        }
        if (!afterNoAdvice) {
          await discuss('no_advice', '先别替我改，也别给步骤。我现在就想跟你待一会儿。');
        }
        await discuss(
          'one_sentence',
          '刚写出来了：杯沿做得薄一点，喝热茶的时候嘴唇会舒服些。就这一句，整篇还没写完。',
        );
        await tap('focus-chat-close');
        await reply('complete_step', () => tap('focus-step-done'));
        await reply('breathe', () => tap('focus-breathe'));
        expect(c.focus.session!.paused, isTrue);
        await tap('focus-break-return');
        await tap('focus-stuck');
        await waitFor(
          () => find.byKey(const Key('focus-chat-input')).evaluate().isNotEmpty,
        );
        await discuss('stop_for_today', '今天就写这一句了，我要去洗澡。别催我回来接着写。');
        await tap('focus-chat-close');
        await tap('focus-finish');
        await waitFor(() => c.focus.session!.closed);
        expect(t.takeException(), isNull);
      } finally {
        await t.pumpWidget(const SizedBox.shrink());
        c.dispose();
      }
    },
    skip: endpoint.isEmpty || evidence.isEmpty,
    timeout: const Timeout(Duration(minutes: 15)),
  );
}

import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import 'music_companion_header.dart';
import 'music_style.dart';
import 'music_song_cards.dart';

class MusicCompanionPanel extends StatelessWidget {
  const MusicCompanionPanel({
    super.key,
    required this.controller,
    required this.input,
    required this.focus,
    required this.send,
  });
  final CompanionController controller;
  final TextEditingController input;
  final FocusNode focus;
  final VoidCallback send;

  @override
  Widget build(BuildContext context) {
    final c = controller;
    final started = DateTime.tryParse(
      c.music.state?['started_at'] as String? ?? '',
    );
    final messages = c.messages
        .where(
          (m) =>
              m.id == c.music.state?['reply_id'] ||
              (started != null &&
                  m.createdAt != null &&
                  !m.createdAt!.isBefore(started)),
        )
        .toList()
        .reversed
        .toList();
    return DecoratedBox(
      key: const Key('music-companion-panel'),
      decoration: BoxDecoration(
        color: const Color(0x10424e49),
        border: Border.all(color: MusicStyle.line),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            MusicCompanionHeader(controller: c),
            const SizedBox(height: 8),
            const Divider(color: MusicStyle.line, height: 1),
            Expanded(
              child: messages.isEmpty
                  ? const Center(
                      child: Padding(
                        padding: EdgeInsets.symmetric(vertical: 12),
                        child: Text(
                          '点一句歌词，聊聊它让你想到的事。',
                          textAlign: TextAlign.center,
                          style: MusicStyle.note,
                        ),
                      ),
                    )
                  : Align(
                      alignment: Alignment.topCenter,
                      child: ListView.builder(
                        key: const Key('music-conversation'),
                        shrinkWrap: true,
                        reverse: true,
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        itemCount: messages.length,
                        itemBuilder: (context, i) {
                          final message = messages[i];
                          return Align(
                            alignment: message.isUser
                                ? Alignment.centerRight
                                : Alignment.centerLeft,
                            child: Container(
                              margin: const EdgeInsets.only(bottom: 14),
                              padding: const EdgeInsets.symmetric(
                                horizontal: 14,
                                vertical: 10,
                              ),
                              constraints: const BoxConstraints(maxWidth: 420),
                              decoration: BoxDecoration(
                                color: message.isUser
                                    ? const Color(0x1feadcc3)
                                    : const Color(0x09ffffff),
                                borderRadius: BorderRadius.circular(12),
                              ),
                              child: Column(
                                mainAxisSize: MainAxisSize.min,
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  SelectableText(
                                    message.text,
                                    style: const TextStyle(
                                      fontSize: 16,
                                      height: 1.65,
                                      color: MusicStyle.ink,
                                    ),
                                  ),
                                  if (message.musicCards.isNotEmpty)
                                    MusicSongCards(
                                      cards: message.musicCards,
                                      controller: c,
                                    ),
                                ],
                              ),
                            ),
                          );
                        },
                      ),
                    ),
            ),
            if (c.sending)
              const Padding(
                padding: EdgeInsets.only(bottom: 8),
                child: Text('正在回应…', style: MusicStyle.note),
              ),
            const SizedBox(height: 8),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: TextField(
                    key: const Key('music-message'),
                    controller: input,
                    focusNode: focus,
                    style: const TextStyle(
                      fontSize: 16,
                      height: 1.5,
                      color: MusicStyle.ink,
                    ),
                    minLines: 1,
                    maxLines: MediaQuery.textScalerOf(context).scale(16) > 24
                        ? 1
                        : 3,
                    maxLength: 6000,
                    decoration: const InputDecoration(
                      hintText: '说点什么',
                      counterText: '',
                    ),
                    onSubmitted: (_) => send(),
                  ),
                ),
                const SizedBox(width: 6),
                IconButton(
                  key: const Key('music-send'),
                  tooltip: '发送消息',
                  onPressed: c.busy ? null : send,
                  icon: const Icon(Icons.arrow_upward_rounded),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

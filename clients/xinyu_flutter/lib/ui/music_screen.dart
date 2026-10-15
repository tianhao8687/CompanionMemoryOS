import 'dart:async';

import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import 'connected_apps.dart';
import 'glass.dart';
import 'music_layout.dart';
import 'music_style.dart';
import 'ui_standard.dart';

Future<void> showMusicScreen(
  BuildContext context,
  CompanionController controller,
) => Navigator.of(context).push<void>(
  MaterialPageRoute(
    builder: (_) => TogetherMusicScreen(controller: controller),
  ),
);

class TogetherMusicScreen extends StatefulWidget {
  const TogetherMusicScreen({super.key, required this.controller});
  final CompanionController controller;
  @override
  State<TogetherMusicScreen> createState() => _TogetherMusicScreenState();
}

class _TogetherMusicScreenState extends State<TogetherMusicScreen> {
  final input = TextEditingController();
  final inputFocus = FocusNode();
  void _quote(String text) {
    input.text = input.text.isEmpty ? text : '${input.text}\n$text';
    input.selection = TextSelection.collapsed(offset: input.text.length);
    inputFocus.requestFocus();
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && !widget.controller.music.active) {
        unawaited(widget.controller.music.act('start'));
      }
    });
    input.addListener(_typing);
  }

  void _typing() =>
      widget.controller.music.composingHere = input.text.isNotEmpty;
  @override
  void dispose() {
    input.removeListener(_typing);
    input.dispose();
    inputFocus.dispose();
    widget.controller.music.composingHere = false;
    super.dispose();
  }

  Future<void> _say() async {
    final c = widget.controller, text = input.text.trim();
    if (text.isEmpty || c.busy || !c.checkChatSetup()) return;
    input.clear();
    await c.send(text, useComposerAttachments: false);
  }

  Future<void> _connect() async {
    await showConnectedApps(context, widget.controller);
    if (mounted) await widget.controller.music.act('start');
  }

  @override
  Widget build(BuildContext context) => Theme(
    data: MusicStyle.theme(context),
    child: ListenableBuilder(
      listenable: widget.controller,
      builder: (context, _) {
        final c = widget.controller, music = c.music;
        final wide =
            !XinYuLayout.mobile(context) &&
            MediaQuery.sizeOf(context).width >= 960;
        return Scaffold(
          backgroundColor: MusicStyle.background,
          resizeToAvoidBottomInset: true,
          body: DecoratedBox(
            decoration: const BoxDecoration(gradient: MusicStyle.gradient),
            child: SafeArea(
              child: Column(
                children: [
                  Padding(
                    padding: EdgeInsets.symmetric(
                      horizontal: wide ? 28 : 8,
                      vertical: 4,
                    ),
                    child: Row(
                      children: [
                        IconButton(
                          tooltip: '返回聊天',
                          onPressed: () => Navigator.pop(context),
                          icon: Icon(
                            wide
                                ? Icons.arrow_back_rounded
                                : Icons.keyboard_arrow_down_rounded,
                          ),
                        ),
                        const Expanded(
                          child: Text(
                            '一起听',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w500,
                              color: MusicStyle.ink,
                              letterSpacing: 2,
                            ),
                          ),
                        ),
                        PopupMenuButton<String>(
                          tooltip: '听歌选项',
                          onSelected: (value) async {
                            if (value == 'connection') await _connect();
                            if (value == 'end') {
                              await music.act('end');
                              if (context.mounted) Navigator.pop(context);
                            }
                          },
                          itemBuilder: (_) => const [
                            PopupMenuItem(
                              value: 'connection',
                              child: Text('网易云连接'),
                            ),
                            PopupMenuItem(value: 'end', child: Text('结束一起听')),
                          ],
                        ),
                      ],
                    ),
                  ),
                  Expanded(
                    child: MusicListeningLayout(
                      controller: c,
                      input: input,
                      focus: inputFocus,
                      send: _say,
                      connect: _connect,
                      quote: _quote,
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    ),
  );
}

class MusicMiniPlayer extends StatelessWidget {
  const MusicMiniPlayer({super.key, required this.controller});
  final CompanionController controller;
  @override
  Widget build(BuildContext context) {
    final music = controller.music;
    if (!music.active) return const SizedBox.shrink();
    return Material(
      color: XinYuColors.canvas,
      child: InkWell(
        onTap: () => showMusicScreen(context, controller),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Row(
            children: [
              const Icon(
                Icons.headphones_rounded,
                size: 20,
                color: XinYuColors.accent,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  music.available
                      ? '${music.media['title']} · 一起听'
                      : '一起听 · 播放状态待更新',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: XinYuLayout.note,
                ),
              ),
              const Icon(Icons.chevron_right_rounded, size: 20),
            ],
          ),
        ),
      ),
    );
  }
}

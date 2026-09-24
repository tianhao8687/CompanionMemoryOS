import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show ScrollCacheExtent;
import 'package:flutter/services.dart';

import '../data/models.dart';
import '../state/companion_controller.dart';
import 'glass.dart';

class ConversationView extends StatefulWidget {
  const ConversationView({super.key, required this.controller});
  final CompanionController controller;
  @override
  State<ConversationView> createState() => _ConversationViewState();
}

class _ConversationViewState extends State<ConversationView> {
  final scroll = ScrollController();
  String? conversation;
  bool _scrollScheduled = false;
  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_updated);
  }

  void _updated() {
    final changed = conversation != widget.controller.active;
    conversation = widget.controller.active;
    if (!_scrollScheduled &&
        (changed ||
            (widget.controller.sending &&
                scroll.hasClients &&
                scroll.offset < 100))) {
      _scrollScheduled = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _scrollScheduled = false;
        if (mounted && scroll.hasClients) scroll.jumpTo(0);
      });
    }
  }

  @override
  void dispose() {
    widget.controller.removeListener(_updated);
    scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = widget.controller;
    if (controller.messages.isEmpty && !controller.sending) {
      return Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            children: [
              const CompanionAvatar(size: 80),
              const SizedBox(height: 23),
              const Text(
                '留一盏灯，',
                style: TextStyle(
                  fontSize: 28,
                  fontWeight: FontWeight.w600,
                  height: 1.5,
                ),
              ),
              const Text(
                '听你慢慢说。',
                style: TextStyle(
                  fontSize: 28,
                  color: Color(0xff9b7057),
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 19),
              Text(
                '我是${controller.companionName}。\n开心的、乱糟糟的，或只是平常的一天，\n都可以在这里，慢慢说。',
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 13,
                  height: 1.9,
                  color: XinYuColors.muted,
                ),
              ),
            ],
          ),
        ),
      );
    }
    final extra = controller.sending ? 1 : 0;
    return RepaintBoundary(
      child: Scrollbar(
        controller: scroll,
        child: ListView.builder(
          key: const Key('chat-list'),
          controller: scroll,
          reverse: true,
          padding: EdgeInsets.fromLTRB(
            MediaQuery.sizeOf(context).width < 600 ? 2 : 18,
            16,
            MediaQuery.sizeOf(context).width < 600 ? 2 : 18,
            14,
          ),
          scrollCacheExtent: const ScrollCacheExtent.pixels(240),
          itemCount: controller.messages.length + extra + 1,
          itemBuilder: (context, index) {
            if (index == controller.messages.length + extra) {
              return Padding(
                padding: const EdgeInsets.fromLTRB(8, 18, 8, 28),
                child: Column(
                  children: [
                    if (controller.hasMore)
                      TextButton(
                        onPressed: controller.busy
                            ? null
                            : controller.loadOlder,
                        child: const Text('查看更早的对话'),
                      ),
                    Text(
                      controller.isDemo ? '示例对话 · 给今天留一点空白' : '属于我们的片刻',
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        color: XinYuColors.muted,
                        fontSize: 11,
                        letterSpacing: 1,
                      ),
                    ),
                  ],
                ),
              );
            }
            if (extra == 1 && index == 0) {
              return _MessageBubble(
                line: ChatLine(
                  id: 'draft',
                  text: controller.draft.isEmpty
                      ? '${controller.status}…'
                      : controller.draft,
                  isUser: false,
                ),
                name: controller.companionName,
                draft: true,
              );
            }
            final message = controller
                .messages[controller.messages.length - 1 - (index - extra)];
            return _MessageBubble(
              key: ValueKey('${controller.active}-${message.id}'),
              line: message,
              name: controller.companionName,
            );
          },
        ),
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({
    super.key,
    required this.line,
    required this.name,
    this.draft = false,
  });
  final ChatLine line;
  final String name;
  final bool draft;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 22),
    child: LayoutBuilder(
      builder: (context, constraints) => Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: line.isUser
            ? MainAxisAlignment.end
            : MainAxisAlignment.start,
        children: [
          if (!line.isUser) ...[
            CompanionAvatar(size: 32, label: name.characters.last),
            const SizedBox(width: 10),
          ],
          ConstrainedBox(
            constraints: BoxConstraints(
              maxWidth: (constraints.maxWidth - 48).clamp(0, 640),
            ),
            child: Column(
              crossAxisAlignment: line.isUser
                  ? CrossAxisAlignment.end
                  : CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.only(left: 3, right: 3, bottom: 7),
                  child: Text(
                    line.isUser
                        ? '你'
                        : draft
                        ? '$name · 正在回应'
                        : name,
                    style: const TextStyle(
                      fontSize: 10,
                      color: XinYuColors.muted,
                    ),
                  ),
                ),
                GlassSurface(
                  radius: 20,
                  blur: 24,
                  tint: line.isUser
                      ? const Color(0x6091b8a5)
                      : const Color(0x78ffffff),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 18,
                    vertical: 14,
                  ),
                  child: Text(
                    line.text,
                    style: const TextStyle(
                      fontSize: 14,
                      height: 1.85,
                      color: XinYuColors.ink,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    ),
  );
}

class Composer extends StatefulWidget {
  const Composer({
    super.key,
    required this.controller,
    required this.openSettings,
  });
  final CompanionController controller;
  final VoidCallback openSettings;
  @override
  State<Composer> createState() => _ComposerState();
}

class _ComposerState extends State<Composer> {
  final text = TextEditingController();
  final focus = FocusNode();
  Future<void> _send() async {
    if (widget.controller.busy ||
        text.text.trim().isEmpty ||
        text.value.composing.isValid) {
      return;
    }
    if (!widget.controller.ready) {
      widget.openSettings();
      return;
    }
    final value = text.text;
    text.clear();
    unawaited(widget.controller.send(value));
    focus.requestFocus();
  }

  @override
  void dispose() {
    text.dispose();
    focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => GlassSurface(
    radius: 27,
    padding: const EdgeInsets.fromLTRB(15, 11, 12, 9),
    tint: const Color(0x65ffffff),
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Shortcuts(
          shortcuts: const {
            SingleActivator(LogicalKeyboardKey.enter, control: true):
                ActivateIntent(),
            SingleActivator(LogicalKeyboardKey.enter, meta: true):
                ActivateIntent(),
          },
          child: Actions(
            actions: {
              ActivateIntent: CallbackAction<ActivateIntent>(
                onInvoke: (_) {
                  _send();
                  return null;
                },
              ),
            },
            child: TextField(
              key: const Key('message-input'),
              controller: text,
              focusNode: focus,
              minLines: 1,
              maxLines: 5,
              maxLength: 6000,
              textInputAction: TextInputAction.newline,
              keyboardType: TextInputType.multiline,
              style: const TextStyle(fontSize: 15, height: 1.65),
              decoration: const InputDecoration(
                hintText: '今天，想和我说些什么？',
                filled: false,
                counterText: '',
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
                contentPadding: EdgeInsets.symmetric(
                  horizontal: 3,
                  vertical: 8,
                ),
              ),
            ),
          ),
        ),
        Row(
          children: [
            Icon(
              Icons.spa_outlined,
              size: 17,
              color: XinYuColors.muted.withValues(alpha: .85),
            ),
            const SizedBox(width: 7),
            Expanded(
              child: Text(
                widget.controller.isDemo
                    ? '演示空间 · 不调用模型'
                    : widget.controller.sending
                    ? '正在回应，稍等片刻'
                    : '安心做自己，我在这里',
                style: const TextStyle(fontSize: 10, color: XinYuColors.muted),
              ),
            ),
            ValueListenableBuilder<TextEditingValue>(
              valueListenable: text,
              builder: (_, value, _) => IconButton.filled(
                key: const Key('send-message'),
                tooltip: '发送消息（Ctrl / ⌘ + Enter）',
                onPressed: widget.controller.busy || value.text.trim().isEmpty
                    ? null
                    : _send,
                style: IconButton.styleFrom(
                  backgroundColor: XinYuColors.accent,
                  foregroundColor: Colors.white,
                  disabledBackgroundColor: const Color(0x35617b69),
                ),
                icon: Icon(
                  widget.controller.sending
                      ? Icons.more_horiz_rounded
                      : Icons.arrow_upward_rounded,
                  size: 21,
                ),
              ),
            ),
          ],
        ),
      ],
    ),
  );
}

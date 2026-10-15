import 'package:flutter/material.dart';

import '../data/models.dart';
import '../state/companion_controller.dart';
import 'focus_presence.dart';
import 'focus_style.dart';

Future<void> showFocusChat(
  BuildContext context,
  CompanionController controller,
) => showDialog<void>(
  context: context,
  builder: (_) => _FocusChat(controller: controller),
);

class _FocusChat extends StatefulWidget {
  const _FocusChat({required this.controller});
  final CompanionController controller;
  @override
  State<_FocusChat> createState() => _FocusChatState();
}

class _FocusChatState extends State<_FocusChat> {
  late final conversation = widget.controller.active;
  late final previous = widget.controller.messages
      .map((line) => line.id)
      .toSet();
  late final text = TextEditingController(text: _invitation());
  bool sent = false;

  String _invitation() {
    final focus = widget.controller.focus;
    final task = focus.session?.intention ?? '';
    final step = focus.presence.step;
    return [
      task.isEmpty ? '我刚才在专注，现在有点卡住了。' : '我刚才在做「$task」，现在有点卡住了。',
      if (step != null) '我选的小步骤是「$step」。',
      '陪我商量一下接下来先做什么吧。',
    ].join('\n');
  }

  Future<void> _send() async {
    final c = widget.controller;
    if (c.active != conversation || c.busy || text.text.trim().isEmpty) return;
    if (!c.checkChatSetup()) return;
    final value = text.text.trim();
    if (value.length > 6000) return;
    setState(() {
      sent = true;
      text.clear();
    });
    await c.send(value, useComposerAttachments: false);
  }

  @override
  void dispose() {
    text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Dialog(
    key: const Key('focus-chat'),
    insetPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 560, maxHeight: 680),
      child: ListenableBuilder(
        listenable: widget.controller,
        builder: (context, _) {
          final c = widget.controller;
          final sameConversation = c.active == conversation;
          final lines = sameConversation
              ? c.messages.where((line) => !previous.contains(line.id)).toList()
              : <ChatLine>[];
          return SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        '和${c.companionDisplayName}商量一下',
                        style: FocusStyle.heading,
                      ),
                    ),
                    IconButton(
                      key: const Key('focus-chat-close'),
                      tooltip: '回到专注',
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                const Text('把卡住的地方说给我听。消息会留在当前聊天。', style: FocusStyle.caption),
                if (c.settings['model_mode'] == 'offline') ...[
                  const SizedBox(height: 8),
                  const Text('当前是离线演示，回复使用规则示例。', style: FocusStyle.caption),
                ],
                const SizedBox(height: 16),
                for (final line in lines)
                  _message(
                    line.isUser ? '你' : c.companionDisplayName,
                    line.text,
                    line.isUser,
                  ),
                if (sameConversation && c.sending)
                  _message(
                    c.companionDisplayName,
                    c.draft.isEmpty ? '正在回应…' : c.draft,
                    false,
                  ),
                if (sent && sameConversation && c.error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Semantics(
                      liveRegion: true,
                      child: Text(
                        c.error!,
                        style: FocusStyle.body.copyWith(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ),
                  ),
                if (!sameConversation)
                  const Text('聊天已切换，请回到专注后重新打开。')
                else ...[
                  Padding(
                    padding: const EdgeInsets.only(left: 4, bottom: 8),
                    child: Text(
                      sent ? '想接着说什么' : '想对 TA 说的话（可修改）',
                      style: FocusStyle.caption,
                    ),
                  ),
                  TextField(
                    key: const Key('focus-chat-input'),
                    controller: text,
                    minLines: 2,
                    maxLines: 6,
                    maxLength: 6000,
                    style: FocusStyle.body,
                    decoration: const InputDecoration(counterText: ''),
                    onChanged: (_) => setState(() {}),
                  ),
                  const SizedBox(height: 12),
                  Wrap(
                    alignment: WrapAlignment.end,
                    spacing: 12,
                    runSpacing: 8,
                    children: [
                      if (c.sending)
                        TextButton(
                          onPressed: c.cancel,
                          child: const Text('停止回复'),
                        ),
                      if (sent && c.canRetry)
                        TextButton(
                          key: const Key('focus-chat-retry'),
                          onPressed: c.retry,
                          child: const Text('重试'),
                        ),
                      FilledButton(
                        key: const Key('focus-chat-send'),
                        onPressed: c.busy || text.text.trim().isEmpty
                            ? null
                            : _send,
                        child: Text(c.sending ? '正在回应…' : '发送'),
                      ),
                    ],
                  ),
                ],
                const SizedBox(height: 16),
                ListenableBuilder(
                  listenable: c.focus,
                  builder: (context, _) {
                    final canStep = const {
                      'focus',
                      'focus_paused',
                    }.contains(c.focus.session?.phase);
                    return Wrap(
                      alignment: WrapAlignment.center,
                      spacing: 12,
                      runSpacing: 8,
                      children: [
                        if (canStep)
                          TextButton.icon(
                            key: const Key('focus-chat-step'),
                            onPressed: () => showFocusStep(context, c),
                            icon: const Icon(Icons.add_rounded, size: 18),
                            label: const Text('定下一小步'),
                          ),
                        TextButton(
                          onPressed: () => Navigator.pop(context),
                          child: const Text('回到专注'),
                        ),
                      ],
                    );
                  },
                ),
              ],
            ),
          );
        },
      ),
    ),
  );

  Widget _message(String name, String content, bool user) => Padding(
    padding: const EdgeInsets.only(bottom: 16),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(name, style: FocusStyle.caption),
        const SizedBox(height: 8),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: user
                ? const Color(0xffe4eaf3)
                : Colors.white.withValues(alpha: .6),
            borderRadius: BorderRadius.circular(16),
          ),
          child: SelectableText(content, style: FocusStyle.body),
        ),
      ],
    ),
  );
}

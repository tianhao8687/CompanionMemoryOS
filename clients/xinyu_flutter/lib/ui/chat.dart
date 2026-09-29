import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../data/models.dart';
import '../state/companion_controller.dart';
import 'glass.dart';
import 'message_surface.dart';
import 'local_image.dart';
import 'stickers.dart';
import 'journal_sheet.dart';
import 'message_context.dart';
import 'character_home.dart';
import 'typography.dart';
export 'chat_reader.dart' show ConversationView;

class MessageBubble extends StatelessWidget {
  const MessageBubble({
    super.key,
    required this.line,
    required this.controller,
    required this.name,
    this.draft = false,
    this.interactive = true,
    this.continuesGroup = false,
  });
  final ChatLine line;
  final CompanionController controller;
  final String name;
  final bool draft;
  final bool interactive;
  final bool continuesGroup;
  bool get actionable =>
      interactive &&
      !draft &&
      !line.notice &&
      line.sequence > 0 &&
      (controller.hasJournal || controller.hasExperience) &&
      !controller.loading;
  Future<void> _actions(BuildContext context) async {
    if (!actionable) return;
    final action = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: Colors.transparent,
      elevation: 0,
      useSafeArea: true,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: GlassSurface(
            grouped: false,
            tint: XinYuColors.sheet,
            padding: const EdgeInsets.all(12),
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (!controller.busy && controller.hasJournal)
                    ListTile(
                      leading: const Icon(Icons.reply_rounded),
                      title: const Text('引用回复'),
                      onTap: () => Navigator.pop(context, 'quote'),
                    ),
                  if (!controller.busy && controller.hasJournal)
                    ListTile(
                      leading: const Icon(Icons.photo_album_outlined),
                      title: const Text('保存为共同回忆'),
                      onTap: () => Navigator.pop(context, 'moment'),
                    ),
                  ListTile(
                    leading: const Icon(Icons.copy_rounded),
                    title: const Text('复制文字'),
                    onTap: () => Navigator.pop(context, 'copy'),
                  ),
                  if (controller.hasExperience)
                    ListTile(
                      leading: Icon(
                        line.bookmarked
                            ? Icons.bookmark_remove_outlined
                            : Icons.bookmark_add_outlined,
                      ),
                      title: Text(line.bookmarked ? '取消收藏' : '收藏'),
                      onTap: () => Navigator.pop(context, 'bookmark'),
                    ),
                  if (controller.hasExperience)
                    ListTile(
                      leading: const Icon(Icons.checklist_rounded),
                      title: const Text('多选'),
                      onTap: () => Navigator.pop(context, 'select'),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
    if (!context.mounted) return;
    if (action == 'quote') controller.quoteMessage(line);
    if (action == 'moment') await saveChatMoment(context, controller, line);
    if (action == 'copy') {
      final copied = await controller.copyText(line.text);
      if (context.mounted && copied) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('已复制文字')));
      }
    }
    if (action == 'select') controller.startSelection(line);
    if (action == 'bookmark') {
      try {
        await controller.bookmarkMessages([line.id], !line.bookmarked);
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(line.bookmarked ? '已取消收藏' : '已收藏，保存在角色主页的收藏夹'),
            ),
          );
        }
      } catch (e) {
        if (context.mounted) {
          controller.reportFailure(e, title: '收藏操作未完成');
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) => GestureDetector(
    onTap: controller.selecting && actionable
        ? () => controller.toggleSelection(line.id)
        : null,
    onLongPress: actionable ? () => _actions(context) : null,
    onSecondaryTap: actionable ? () => _actions(context) : null,
    child: Padding(
      padding: EdgeInsets.only(top: continuesGroup ? 6 : 14),
      child: LayoutBuilder(
        builder: (context, constraints) => Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: line.isUser
              ? MainAxisAlignment.end
              : MainAxisAlignment.start,
          children: [
            if (controller.selecting && line.sequence > 0)
              SizedBox(
                width: 40,
                child: Checkbox(
                  key: ValueKey('select-${line.id}'),
                  value: controller.selectedMessages.contains(line.id),
                  onChanged: (_) => controller.toggleSelection(line.id),
                ),
              ),
            if (!line.isUser) ...[
              SizedBox(
                width: MediaQuery.sizeOf(context).width < 880 ? 36 : 48,
                child: continuesGroup
                    ? null
                    : InkWell(
                        borderRadius: BorderRadius.circular(9),
                        onTap: controller.selecting
                            ? null
                            : () => showCharacterHome(context, controller),
                        child: ProfileAvatar(
                          controller: controller,
                          size: MediaQuery.sizeOf(context).width < 880
                              ? 36
                              : 48,
                        ),
                      ),
              ),
              SizedBox(width: MediaQuery.sizeOf(context).width < 880 ? 10 : 16),
            ],
            ConstrainedBox(
              constraints: BoxConstraints(
                maxWidth:
                    (constraints.maxWidth -
                            (controller.selecting ? 40 : 0) -
                            (line.isUser
                                ? 32
                                : MediaQuery.sizeOf(context).width < 880
                                ? 50
                                : 68))
                        .clamp(0, 620),
              ),
              child: Column(
                crossAxisAlignment: line.isUser
                    ? CrossAxisAlignment.end
                    : CrossAxisAlignment.start,
                children: [
                  if (line.notice)
                    const Padding(
                      padding: EdgeInsets.only(bottom: 6),
                      child: Text(
                        '约定提醒',
                        style: TextStyle(
                          fontSize: 12,
                          color: XinYuColors.muted,
                        ),
                      ),
                    ),
                  for (final (partIndex, part) in _parts.indexed)
                    if ((part.isNotEmpty &&
                            !(line.imageIds.isNotEmpty &&
                                line.text == '[图片]') &&
                            !(line.sticker != null && line.text == '[表情包]')) ||
                        (line.quote != null && partIndex == 0))
                      Padding(
                        padding: EdgeInsets.only(
                          bottom: partIndex < _parts.length - 1 ? 6 : 0,
                        ),
                        child: MessageSurface(
                          isUser: line.isUser,
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (line.quote != null && partIndex == 0)
                                InkWell(
                                  key: ValueKey('quote-${line.id}'),
                                  onTap:
                                      !controller.selecting &&
                                          line.quote!.available &&
                                          controller.active != null
                                      ? () => showMessageContext(
                                          context,
                                          controller,
                                          controller.active!,
                                          line.quote!.id,
                                        )
                                      : null,
                                  child: Container(
                                    margin: const EdgeInsets.only(bottom: 10),
                                    padding: const EdgeInsets.all(10),
                                    decoration: BoxDecoration(
                                      color: line.isUser
                                          ? const Color(0x50ffffff)
                                          : const Color(0x80eef1f5),
                                      borderRadius: BorderRadius.circular(8),
                                    ),
                                    child: Text(
                                      line.quote!.available
                                          ? '${line.quote!.isUser ? (controller.userName.isEmpty ? '你' : controller.userName) : name}：${line.quote!.text}'
                                          : '原消息已不可用',
                                      maxLines: 3,
                                      overflow: TextOverflow.ellipsis,
                                      style: const TextStyle(
                                        fontSize: 13,
                                        height: 1.5,
                                        color: XinYuColors.muted,
                                      ),
                                    ),
                                  ),
                                ),
                              if (part.isNotEmpty &&
                                  !(line.imageIds.isNotEmpty &&
                                      line.text == '[图片]') &&
                                  !(line.sticker != null &&
                                      line.text == '[表情包]'))
                                Text(
                                  part,
                                  style: XinYuTypography.message(
                                    compact:
                                        MediaQuery.sizeOf(context).width < 880,
                                  ).copyWith(color: XinYuColors.ink),
                                ),
                            ],
                          ),
                        ),
                      ),
                  for (final id in line.imageIds)
                    Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: ChatPhoto(controller: controller, id: id),
                    ),
                  if (line.sticker != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: StickerView(
                        item: line.sticker!,
                        controller: controller,
                      ),
                    ),
                  if (line.bookmarked)
                    const Padding(
                      padding: EdgeInsets.only(top: 4, left: 5),
                      child: Icon(
                        Icons.bookmark_rounded,
                        size: 14,
                        color: XinYuColors.accent,
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    ),
  );

  List<String> get _parts {
    if (line.isUser ||
        !controller.naturalChat ||
        line.text.contains('```') ||
        RegExp(r'(^|\n)\s*(?:[-*#]|\d+[.)])\s').hasMatch(line.text)) {
      return [line.text];
    }
    // Only display paragraph boundaries already authored by the model; keep the
    // original message, source ID, questions and words intact in storage.
    return line.text.split(RegExp(r'\n\s*\n'));
  }
}

class Composer extends StatefulWidget {
  const Composer({super.key, required this.controller});
  final CompanionController controller;
  @override
  State<Composer> createState() => _ComposerState();
}

class _ComposerState extends State<Composer> {
  final text = TextEditingController();
  final focus = FocusNode();
  int revision = -1;
  String? conversation;
  bool restoring = false;

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_updated);
    text.addListener(_changed);
    focus.onKeyEvent = _key;
    _updated();
  }

  void _changed() {
    if (!restoring) widget.controller.updateComposer(text.text);
  }

  void _updated() {
    final c = widget.controller;
    if (conversation != c.active || revision != c.composerRevision) {
      conversation = c.active;
      revision = c.composerRevision;
      restoring = true;
      text.value = TextEditingValue(
        text: c.composerText,
        selection: TextSelection.collapsed(offset: c.composerText.length),
      );
      restoring = false;
    }
  }

  KeyEventResult _key(FocusNode node, KeyEvent event) {
    final platform = Theme.of(context).platform;
    final desktop =
        platform == TargetPlatform.windows ||
        platform == TargetPlatform.macOS ||
        platform == TargetPlatform.linux;
    if (event.logicalKey != LogicalKeyboardKey.enter ||
        HardwareKeyboard.instance.isShiftPressed ||
        text.value.composing.isValid ||
        (!desktop &&
            !HardwareKeyboard.instance.isControlPressed &&
            !HardwareKeyboard.instance.isMetaPressed)) {
      return KeyEventResult.ignored;
    }
    if (event is KeyDownEvent) unawaited(_send());
    return KeyEventResult.handled;
  }

  Future<void> _send() async {
    if (widget.controller.loading ||
        widget.controller.sending ||
        (text.text.trim().isEmpty && widget.controller.pendingImages.isEmpty) ||
        text.value.composing.isValid) {
      return;
    }
    final accepted = await widget.controller.submit(text.text);
    if (!mounted) return;
    if (accepted) text.clear();
    focus.requestFocus();
  }

  Future<void> _emoji() async {
    focus.unfocus();
    final chosen = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: Colors.transparent,
      useSafeArea: true,
      builder: (context) => Padding(
        padding: const EdgeInsets.all(12),
        child: GlassSurface(
          grouped: false,
          tint: XinYuColors.sheet,
          padding: const EdgeInsets.all(16),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  children: [
                    const Expanded(
                      child: Text('表情', style: TextStyle(fontSize: 18)),
                    ),
                    IconButton(
                      tooltip: '关闭表情',
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
                Wrap(
                  children: [
                    for (final emoji in const [
                      '🙂',
                      '😊',
                      '🥰',
                      '❤️',
                      '🤗',
                      '😂',
                      '🥹',
                      '😴',
                      '🌙',
                      '✨',
                      '🌷',
                      '🌿',
                      '☕',
                      '🎉',
                      '👍',
                      '🐈',
                    ])
                      SizedBox(
                        width: 56,
                        height: 52,
                        child: TextButton(
                          key: ValueKey('emoji-$emoji'),
                          onPressed: () => Navigator.pop(context, emoji),
                          child: Text(
                            emoji,
                            textScaler: TextScaler.noScaling,
                            style: const TextStyle(fontSize: 25),
                          ),
                        ),
                      ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
    if (!mounted || chosen == null) return;
    final value = text.value;
    final start = value.selection.isValid
        ? value.selection.start
        : value.text.length;
    final end = value.selection.isValid
        ? value.selection.end
        : value.text.length;
    text.value = TextEditingValue(
      text: value.text.replaceRange(start, end, chosen),
      selection: TextSelection.collapsed(offset: start + chosen.length),
    );
    focus.requestFocus();
  }

  @override
  void dispose() {
    widget.controller.removeListener(_updated);
    text.removeListener(_changed);
    text.dispose();
    focus.dispose();
    super.dispose();
  }

  Widget _field(bool compact) => Semantics(
    identifier: widget.controller.connected && !widget.controller.isDemo
        ? 'xinyu-local-ready'
        : 'xinyu-message-input',
    label: '消息输入',
    child: TextField(
      key: const Key('message-input'),
      controller: text,
      focusNode: focus,
      minLines: 1,
      maxLines: compact ? 4 : 5,
      maxLength: 6000,
      textInputAction: TextInputAction.newline,
      keyboardType: TextInputType.multiline,
      style: XinYuTypography.message(compact: compact)
          .copyWith(color: XinYuColors.ink),
      decoration: InputDecoration(
        filled: false,
        counterText: '',
        border: InputBorder.none,
        enabledBorder: InputBorder.none,
        focusedBorder: InputBorder.none,
        contentPadding: EdgeInsets.symmetric(
          horizontal: compact ? 4 : 8,
          vertical: 12,
        ),
      ),
    ),
  );

  Widget _sendButton() => ValueListenableBuilder<TextEditingValue>(
    valueListenable: text,
    builder: (_, value, _) {
      final c = widget.controller;
      final VoidCallback? send = c.sending && !c.isDemo
          ? c.cancel
          : c.loading ||
                c.sending ||
                (value.text.trim().isEmpty && c.pendingImages.isEmpty)
          ? null
          : _send;
      return IconButton.filled(
        key: const Key('send-message'),
        tooltip: c.sending ? '停止回复' : '发送消息',
        onPressed: send,
        style: IconButton.styleFrom(
          backgroundColor: XinYuColors.accent,
          foregroundColor: Colors.white,
          disabledBackgroundColor: const Color(0xffd8e0e9),
          disabledForegroundColor: XinYuColors.muted,
        ),
        icon: Icon(c.sending ? Icons.stop_rounded : Icons.arrow_upward_rounded),
      );
    },
  );

  Widget _toolButton({
    required Key key,
    required String label,
    required IconData icon,
    required VoidCallback? onPressed,
  }) => IconButton.filledTonal(
    key: key,
    tooltip: label,
    onPressed: onPressed,
    style: IconButton.styleFrom(
      backgroundColor: const Color(0x66ffffff),
      foregroundColor: XinYuColors.accent,
      disabledBackgroundColor: const Color(0x30ffffff),
      side: const BorderSide(color: Color(0xccdce3eb)),
    ),
    icon: Icon(icon),
  );

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    final compact = MediaQuery.sizeOf(context).width < 880;
    return GlassSurface(
      key: const Key('chat-composer'),
      radius: 28,
      padding: const EdgeInsets.all(6),
      tint: const Color(0x8cffffff),
      child: Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(22),
          border: Border.all(color: const Color(0x90d5deea), width: .8),
          gradient: const LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xb3ffffff), Color(0x70f4f8ff)],
          ),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (c.collecting)
              Row(
                children: [
                  const Spacer(),
                  TextButton(
                    key: const Key('send-collected'),
                    onPressed: c.sendCollected,
                    child: const Text('现在回应'),
                  ),
                  IconButton(
                    tooltip: '收回到草稿',
                    onPressed: c.cancelCollected,
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
            if (c.pendingQuote != null)
              Container(
                key: const Key('quote-preview'),
                margin: const EdgeInsets.only(left: 8, bottom: 8),
                padding: const EdgeInsets.only(left: 10),
                decoration: BoxDecoration(
                  color: const Color(0x80eef1f5),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        '回复${c.pendingQuote!.isUser ? '你' : c.companionDisplayName}：${c.pendingQuote!.text}',
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: XinYuColors.muted,
                          fontSize: 13,
                        ),
                      ),
                    ),
                    IconButton(
                      key: const Key('cancel-quote'),
                      tooltip: '取消引用',
                      onPressed: () => c.quoteMessage(null),
                      icon: const Icon(Icons.close),
                    ),
                  ],
                ),
              ),
            if (c.pendingImages.isNotEmpty)
              SizedBox(
                height: 84,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  children: [
                    for (final id in c.pendingImages)
                      Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: Stack(
                          children: [
                            ClipRRect(
                              borderRadius: BorderRadius.circular(12),
                              child: LocalImage(
                                controller: c,
                                id: id,
                                width: 80,
                                height: 76,
                              ),
                            ),
                            Positioned(
                              right: 0,
                              top: 0,
                              child: IconButton.filledTonal(
                                tooltip: '移除图片',
                                icon: const Icon(Icons.close),
                                onPressed: c.busy
                                    ? null
                                    : () => c.removeImage(id),
                              ),
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
            if (!compact) ...[_field(false), const SizedBox(height: 4)],
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                _toolButton(
                  key: const Key('attach-image'),
                  label: '添加图片',
                  onPressed: c.busy ? null : c.attachImage,
                  icon: compact ? Icons.add_rounded : Icons.image_outlined,
                ),
                const SizedBox(width: 4),
                if (compact) Expanded(child: _field(true)),
                _toolButton(
                  key: const Key('insert-emoji'),
                  label: '表情',
                  onPressed: c.loading ? null : _emoji,
                  icon: Icons.sentiment_satisfied_alt_rounded,
                ),
                if (!compact) const Spacer(),
                const SizedBox(width: 4),
                _sendButton(),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

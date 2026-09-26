import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../data/models.dart';
import '../state/companion_controller.dart';
import 'glass.dart';
import 'local_image.dart';
import 'stickers.dart';
import 'journal_sheet.dart';
import 'message_context.dart';
import 'character_home.dart';
export 'chat_reader.dart' show ConversationView;

class MessageBubble extends StatelessWidget {
  const MessageBubble({
    super.key,
    required this.line,
    required this.controller,
    required this.name,
    this.draft = false,
    this.interactive = true,
  });
  final ChatLine line;
  final CompanionController controller;
  final String name;
  final bool draft;
  final bool interactive;
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
            tint: const Color(0xdaf4faf5),
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
      padding: const EdgeInsets.only(bottom: 22),
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
              InkWell(
                onTap: controller.selecting
                    ? null
                    : () => showCharacterHome(context, controller),
                child: ProfileAvatar(controller: controller),
              ),
              const SizedBox(width: 10),
            ],
            ConstrainedBox(
              constraints: BoxConstraints(
                maxWidth:
                    (constraints.maxWidth - (controller.selecting ? 88 : 48))
                        .clamp(0, 640),
              ),
              child: Column(
                crossAxisAlignment: line.isUser
                    ? CrossAxisAlignment.end
                    : CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: const EdgeInsets.only(
                      left: 3,
                      right: 3,
                      bottom: 7,
                    ),
                    child: Text(
                      line.notice
                          ? '心隅 · 约定提醒'
                          : line.isUser
                          ? (controller.userName.isEmpty
                                ? '你'
                                : controller.userName)
                          : draft
                          ? '$name · 正在回应'
                          : name,
                      style: const TextStyle(
                        fontSize: 10,
                        color: XinYuColors.muted,
                      ),
                    ),
                  ),
                  for (final (partIndex, part) in _parts.indexed)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 7),
                      child: GlassSurface(
                        radius: 20,
                        blur: 24,
                        tint: line.isUser
                            ? const Color(0x6091b8a5)
                            : const Color(0x78ffffff),
                        padding: const EdgeInsets.symmetric(
                          horizontal: 18,
                          vertical: 14,
                        ),
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
                                  width: double.infinity,
                                  margin: const EdgeInsets.only(bottom: 10),
                                  padding: const EdgeInsets.all(10),
                                  decoration: BoxDecoration(
                                    color: const Color(0x40ffffff),
                                    borderRadius: BorderRadius.circular(10),
                                    border: const Border(
                                      left: BorderSide(
                                        color: XinYuColors.accent,
                                        width: 3,
                                      ),
                                    ),
                                  ),
                                  child: Text(
                                    line.quote!.available
                                        ? '${line.quote!.isUser ? (controller.userName.isEmpty ? '你' : controller.userName) : name}：${line.quote!.text}'
                                        : '原消息已不可用',
                                    maxLines: 3,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                      fontSize: 12,
                                      height: 1.5,
                                      color: XinYuColors.muted,
                                    ),
                                  ),
                                ),
                              ),
                            if (partIndex == 0)
                              for (final id in line.imageIds)
                                ChatPhoto(controller: controller, id: id),
                            if (part.isNotEmpty &&
                                !(line.imageIds.isNotEmpty &&
                                    line.text == '[图片]') &&
                                !(line.sticker != null && line.text == '[表情包]'))
                              Text(
                                part,
                                style: const TextStyle(
                                  fontSize: 14,
                                  height: 1.85,
                                  color: XinYuColors.ink,
                                ),
                              ),
                            if (line.sticker != null &&
                                partIndex == _parts.length - 1)
                              StickerView(
                                item: line.sticker!,
                                controller: controller,
                              ),
                          ],
                        ),
                      ),
                    ),
                  if (line.bookmarked)
                    const Padding(
                      padding: EdgeInsets.only(left: 5),
                      child: Icon(
                        Icons.bookmark_rounded,
                        size: 14,
                        color: XinYuColors.accent,
                      ),
                    ),
                ],
              ),
            ),
            if (line.isUser) ...[
              const SizedBox(width: 10),
              InkWell(
                onTap: controller.selecting
                    ? null
                    : () =>
                          showCharacterHome(context, controller, isUser: true),
                child: ProfileAvatar(controller: controller, isUser: true),
              ),
            ],
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
  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_updated);
    text.addListener(_changed);
    _updated();
  }

  bool restoring = false;
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

  Future<void> _send() async {
    if (widget.controller.loading ||
        widget.controller.sending ||
        (text.text.trim().isEmpty && widget.controller.pendingImages.isEmpty) ||
        text.value.composing.isValid) {
      return;
    }
    final value = text.text;
    final accepted = await widget.controller.submit(value);
    if (!mounted) return;
    if (accepted) text.clear();
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

  @override
  Widget build(BuildContext context) => GlassSurface(
    radius: 27,
    padding: const EdgeInsets.fromLTRB(15, 11, 12, 9),
    tint: const Color(0x65ffffff),
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (widget.controller.collecting)
          Row(
            children: [
              const Expanded(
                child: Text(
                  '可以继续说，稍后一起回应',
                  style: TextStyle(fontSize: 11, color: XinYuColors.muted),
                ),
              ),
              TextButton(
                key: const Key('send-collected'),
                onPressed: widget.controller.sendCollected,
                child: const Text('现在回应'),
              ),
              IconButton(
                tooltip: '收回到草稿',
                onPressed: widget.controller.cancelCollected,
                icon: const Icon(Icons.close, size: 17),
              ),
            ],
          ),
        if (widget.controller.pendingQuote != null)
          Container(
            key: const Key('quote-preview'),
            padding: const EdgeInsets.only(left: 10),
            decoration: const BoxDecoration(
              border: Border(
                left: BorderSide(color: XinYuColors.accent, width: 3),
              ),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    '回复${widget.controller.pendingQuote!.isUser ? '你' : widget.controller.companionName}：${widget.controller.pendingQuote!.text}',
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: XinYuColors.muted,
                      fontSize: 12,
                    ),
                  ),
                ),
                IconButton(
                  key: const Key('cancel-quote'),
                  tooltip: '取消引用',
                  onPressed: () => widget.controller.quoteMessage(null),
                  icon: const Icon(Icons.close, size: 18),
                ),
              ],
            ),
          ),
        if (widget.controller.pendingImages.isNotEmpty)
          SizedBox(
            height: 84,
            child: ListView(
              scrollDirection: Axis.horizontal,
              children: [
                for (final id in widget.controller.pendingImages)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: Stack(
                      children: [
                        ClipRRect(
                          borderRadius: BorderRadius.circular(12),
                          child: LocalImage(
                            controller: widget.controller,
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
                            icon: const Icon(Icons.close, size: 16),
                            onPressed: widget.controller.busy
                                ? null
                                : () => widget.controller.removeImage(id),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
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
            IconButton(
              key: const Key('attach-image'),
              tooltip: '添加图片（最多 4 张）',
              onPressed: widget.controller.busy
                  ? null
                  : widget.controller.attachImage,
              icon: const Icon(Icons.add_photo_alternate_outlined, size: 21),
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
                tooltip: widget.controller.sending
                    ? '停止回复'
                    : '发送消息（Ctrl / ⌘ + Enter）',
                onPressed:
                    widget.controller.sending && !widget.controller.isDemo
                    ? widget.controller.cancel
                    : widget.controller.loading ||
                          widget.controller.sending ||
                          (value.text.trim().isEmpty &&
                              widget.controller.pendingImages.isEmpty)
                    ? null
                    : _send,
                style: IconButton.styleFrom(
                  backgroundColor: XinYuColors.accent,
                  foregroundColor: Colors.white,
                  disabledBackgroundColor: const Color(0x35617b69),
                ),
                icon: Icon(
                  widget.controller.sending
                      ? Icons.stop_rounded
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

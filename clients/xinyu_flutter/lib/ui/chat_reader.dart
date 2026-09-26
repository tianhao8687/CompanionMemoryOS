import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show ScrollCacheExtent;
import 'package:flutter/services.dart';

import '../data/models.dart';
import '../state/companion_controller.dart';
import 'chat.dart' show MessageBubble;
import 'glass.dart';
import 'local_image.dart';

class ConversationView extends StatefulWidget {
  const ConversationView({super.key, required this.controller});
  final CompanionController controller;
  @override
  State<ConversationView> createState() => _ConversationViewState();
}

class _ConversationViewState extends State<ConversationView> {
  final scroll = ScrollController();
  final viewport = GlobalKey();
  final rows = <String, GlobalKey>{};
  String? conversation;
  List<String> previousIds = [];
  int revision = 0, unseen = 0, restoreGeneration = 0;
  bool follow = true, scheduled = false, restoring = false, remembering = false;
  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_updated);
    _updated();
  }

  Map<String, dynamic> _position() {
    final box = viewport.currentContext?.findRenderObject();
    String? id;
    double y = 0;
    if (box is RenderBox && box.hasSize && !follow) {
      final origin = box.localToGlobal(Offset.zero).dy;
      double closest = double.infinity;
      for (final entry in rows.entries) {
        final item = entry.value.currentContext?.findRenderObject();
        if (item is! RenderBox || !item.hasSize || !item.attached) continue;
        final top = item.localToGlobal(Offset.zero).dy - origin;
        if (top + item.size.height > 0 &&
            top < box.size.height &&
            top.abs() < closest) {
          closest = top.abs();
          id = entry.key;
          y = top;
        }
      }
    }
    final persisted = widget.controller.messages
        .where((m) => m.sequence > 0)
        .toList();
    // Optimistic messages have no source ID and cannot be saved as reader anchors.
    if (!persisted.any((m) => m.id == id)) id = null;
    return {
      'anchor_id': id,
      'anchor_y': y,
      'scroll_offset': follow || !scroll.hasClients
          ? 0.0
          : scroll.offset.clamp(0, double.infinity),
      'last_sequence': persisted.isEmpty ? 0 : persisted.last.sequence,
    };
  }

  void _updated() {
    final c = widget.controller;
    final changed = conversation != c.active;
    final outgoing = revision != c.outgoingRevision;
    final ids = c.messages.map((m) => m.id).toList();
    final added = c.messages
        .where(
          (m) => !previousIds.contains(m.id) && !m.isUser && m.sequence > 0,
        )
        .length;
    final position = !changed && !outgoing && !follow && !restoring
        ? _position()
        : null;
    if (changed) {
      conversation = c.active;
      rows.clear();
      unseen = 0;
      final saved = c.viewState;
      follow = (saved['scroll_offset'] as num? ?? 0) <= chatBottomTolerance;
      if (!follow) _restore(saved, initial: true);
    }
    if (outgoing) {
      follow = true;
      unseen = 0;
      restoring = false;
      restoreGeneration++;
    }
    if (!changed && !follow) unseen += added;
    revision = c.outgoingRevision;
    previousIds = ids;
    if (follow) {
      _bottom();
    } else if (position != null && added > 0) {
      _restore(position);
    }
    if (mounted) setState(() {});
  }

  void _bottom() {
    if (scheduled || !follow) return;
    scheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      scheduled = false;
      if (!mounted || !scroll.hasClients || !follow) return;
      if (scroll.offset != 0) scroll.jumpTo(0);
      widget.controller.setReadingPosition(_position());
    });
  }

  void _jumpToLatest() {
    setState(() {
      follow = true;
      unseen = 0;
      restoring = false;
      restoreGeneration++;
    });
    _bottom();
    unawaited(widget.controller.refreshUpdates());
  }

  Widget _bottomShortcut() => Padding(
    padding: const EdgeInsets.only(top: 2, right: 4, bottom: 4),
    child: Align(
      alignment: Alignment.centerRight,
      child: GlassSurface(
        radius: 999,
        padding: EdgeInsets.zero,
        tint: const Color(0x80ffffff),
        child: Tooltip(
          message:
              widget.controller.messages.isEmpty && !widget.controller.sending
              ? '还没有聊天消息'
              : '回到最新消息',
          child: TextButton.icon(
            key: const Key('back-to-bottom'),
            onPressed:
                widget.controller.messages.isEmpty && !widget.controller.sending
                ? null
                : _jumpToLatest,
            style: TextButton.styleFrom(
              minimumSize: const Size(0, 44),
              padding: const EdgeInsets.symmetric(horizontal: 14),
              shape: XinYuShapes.pill,
            ),
            icon: const Icon(
              Icons.keyboard_double_arrow_down_rounded,
              size: 18,
            ),
            label: Text(unseen > 0 ? '$unseen 条新消息' : '回到底部'),
          ),
        ),
      ),
    ),
  );

  void _restore(Map<String, dynamic> saved, {bool initial = false}) {
    final generation = ++restoreGeneration;
    restoring = true;
    final anchor = saved['anchor_id'] as String?;
    void attempt(int pass) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted || generation != restoreGeneration || !scroll.hasClients) {
          return;
        }
        final box = viewport.currentContext?.findRenderObject();
        final item = rows[anchor]?.currentContext?.findRenderObject();
        double target = scroll.offset;
        if (initial && pass == 0) {
          target = (saved['scroll_offset'] as num? ?? 0).toDouble();
        } else if (box is RenderBox && item is RenderBox && item.hasSize) {
          final current =
              item.localToGlobal(Offset.zero).dy -
              box.localToGlobal(Offset.zero).dy;
          target += (saved['anchor_y'] as num? ?? 0).toDouble() - current;
          if ((target - scroll.offset).abs() < 1) {
            restoring = false;
            _remember();
            return;
          }
        } else if (anchor != null) {
          final targetIndex = widget.controller.messages.indexWhere(
            (m) => m.id == anchor,
          );
          final built = rows.entries
              .where((e) => e.value.currentContext != null)
              .map(
                (e) =>
                    widget.controller.messages.indexWhere((m) => m.id == e.key),
              )
              .where((i) => i >= 0)
              .toList();
          if (targetIndex >= 0 && built.isNotEmpty) {
            final mid = built.reduce((a, b) => a + b) / built.length;
            target += (mid - targetIndex) * 140;
          }
        }
        scroll.jumpTo(target.clamp(0, scroll.position.maxScrollExtent));
        if (pass < 12 && anchor != null) {
          attempt(pass + 1);
        } else {
          restoring = false;
          _remember();
        }
        WidgetsBinding.instance.scheduleFrame();
      });
    }

    attempt(0);
  }

  void _remember() {
    if (remembering) return;
    remembering = true;
    final id = conversation;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      remembering = false;
      if (mounted &&
          !restoring &&
          id == conversation &&
          conversation == widget.controller.active &&
          scroll.hasClients) {
        widget.controller.setReadingPosition(_position());
      }
    });
    WidgetsBinding.instance.scheduleFrame();
  }

  Future<void> _selectionAction(bool copy) async {
    final c = widget.controller;
    final chosen = c.messages
        .where((m) => c.selectedMessages.contains(m.id))
        .toList();
    if (chosen.isEmpty) return;
    try {
      if (copy) {
        await Clipboard.setData(
          ClipboardData(
            text: chosen
                .map(
                  (m) =>
                      '${m.isUser ? (c.userName.isEmpty ? '你' : c.userName) : c.companionName}：${m.text.isNotEmpty ? m.text : '[图片]'}',
                )
                .join('\n\n'),
          ),
        );
      } else {
        await c.bookmarkMessages(chosen.map((m) => m.id).toList(), true);
      }
      c.endSelection();
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(copy ? '已复制所选消息' : '已收藏所选消息')));
      }
    } catch (e) {
      if (mounted) {
        c.reportFailure(e, title: copy ? '消息未能复制' : '收藏操作未完成');
      }
    }
  }

  @override
  void dispose() {
    widget.controller.removeListener(_updated);
    unawaited(widget.controller.flushChatState());
    restoreGeneration++;
    scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    if (c.messages.isEmpty && !c.sending) {
      return Column(
        children: [
          Expanded(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(24),
                child: Column(
                  children: [
                    ProfileAvatar(controller: c, size: 80),
                    const SizedBox(height: 23),
                    const Text(
                      '留一盏灯，\n听你慢慢说。',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 28, height: 1.5),
                    ),
                    const SizedBox(height: 19),
                    Text(
                      '我是${c.companionName}。\n今天，想和我说些什么？',
                      textAlign: TextAlign.center,
                    ),
                  ],
                ),
              ),
            ),
          ),
          _bottomShortcut(),
        ],
      );
    }
    final extra = c.sending ? 1 : 0;
    return Column(
      children: [
        if (c.selecting)
          GlassSurface(
            radius: XinYuShapes.cardRadius,
            padding: const EdgeInsets.symmetric(horizontal: 10),
            child: Wrap(
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text('已选 ${c.selectedMessages.length} / 100'),
                TextButton.icon(
                  key: const Key('copy-selected'),
                  onPressed: c.selectedMessages.isEmpty
                      ? null
                      : () => _selectionAction(true),
                  icon: const Icon(Icons.copy, size: 18),
                  label: const Text('复制'),
                ),
                TextButton.icon(
                  key: const Key('bookmark-selected'),
                  onPressed: c.selectedMessages.isEmpty
                      ? null
                      : () => _selectionAction(false),
                  icon: const Icon(Icons.bookmark_add_outlined, size: 18),
                  label: const Text('收藏'),
                ),
                IconButton(
                  tooltip: '退出多选',
                  onPressed: c.endSelection,
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
          ),
        Expanded(
          child: Stack(
            key: viewport,
            children: [
              NotificationListener<ScrollMetricsNotification>(
                onNotification: (event) {
                  if (event.depth == 0 &&
                      event.metrics.axis == Axis.vertical &&
                      !restoring) {
                    _bottom();
                  }
                  return false;
                },
                child: NotificationListener<ScrollNotification>(
                  onNotification: (event) {
                    if (event.depth != 0 ||
                        event.metrics.axis != Axis.vertical) {
                      return false;
                    }
                    if (event is ScrollStartNotification &&
                        event.dragDetails != null) {
                      restoring = false;
                      restoreGeneration++;
                    }
                    if (!restoring &&
                        (event is ScrollUpdateNotification ||
                            event is ScrollEndNotification)) {
                      final latest =
                          event.metrics.pixels <= chatBottomTolerance;
                      if (follow != latest) {
                        setState(() {
                          follow = latest;
                          if (latest) unseen = 0;
                        });
                      }
                      if (event is ScrollEndNotification) _remember();
                    }
                    return false;
                  },
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
                      itemCount: c.messages.length + extra + 1,
                      itemBuilder: (context, index) {
                        if (index == c.messages.length + extra) {
                          return Padding(
                            padding: const EdgeInsets.all(20),
                            child: Column(
                              children: [
                                if (c.hasMore)
                                  TextButton(
                                    onPressed: c.busy ? null : c.loadOlder,
                                    child: const Text('查看更早的对话'),
                                  ),
                                const Text(
                                  '属于我们的片刻',
                                  style: TextStyle(
                                    color: XinYuColors.muted,
                                    fontSize: 11,
                                  ),
                                ),
                              ],
                            ),
                          );
                        }
                        if (extra == 1 && index == 0) {
                          return MessageBubble(
                            line: ChatLine(
                              id: 'draft',
                              text: c.draft.isEmpty ? '${c.status}…' : c.draft,
                              isUser: false,
                            ),
                            controller: c,
                            name: c.companionName,
                            draft: true,
                          );
                        }
                        final line =
                            c.messages[c.messages.length - 1 - (index - extra)];
                        return Container(
                          key: rows.putIfAbsent(line.id, GlobalKey.new),
                          child: MessageBubble(
                            line: line,
                            controller: c,
                            name: c.companionName,
                          ),
                        );
                      },
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
        _bottomShortcut(),
      ],
    );
  }
}

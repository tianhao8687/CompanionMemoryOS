import 'package:flutter/material.dart';

import '../data/models.dart';
import '../state/companion_controller.dart';
import 'glass.dart';
import 'local_image.dart';
import 'message_context.dart';
import 'stickers.dart';

Future<void> showBookmarks(
  BuildContext context,
  CompanionController controller,
) => showDialog<void>(
  context: context,
  builder: (_) => _Bookmarks(controller: controller),
);

class _Bookmarks extends StatefulWidget {
  const _Bookmarks({required this.controller});
  final CompanionController controller;
  @override
  State<_Bookmarks> createState() => _BookmarksState();
}

class _BookmarksState extends State<_Bookmarks> {
  List<SearchHit> items = [];
  bool working = false, more = false;
  String? error;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load({bool append = false}) async {
    if (working) return;
    setState(() {
      working = true;
      error = null;
    });
    try {
      final result = await widget.controller.bookmarks(
        offset: append ? items.length : 0,
      );
      if (!mounted) return;
      final page = (result['items'] as List)
          .map((v) => SearchHit.fromJson(Map<String, dynamic>.from(v as Map)))
          .toList();
      setState(() {
        items = append ? [...items, ...page] : page;
        more = result['has_more'] == true;
      });
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '收藏夹暂时无法打开'),
        );
      }
    } finally {
      if (mounted) setState(() => working = false);
    }
  }

  Future<void> remove(String id) async {
    try {
      await widget.controller.bookmarkMessages([id], false);
      await load();
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '收藏操作未完成'),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) => Dialog(
    backgroundColor: Colors.transparent,
    insetPadding: const EdgeInsets.all(16),
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 650, maxHeight: 740),
      child: GlassSurface(
        tint: const Color(0xeef4faf5),
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text(
                    '收藏夹',
                    style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
                  ),
                ),
                IconButton(
                  tooltip: '刷新收藏',
                  onPressed: working ? null : load,
                  icon: const Icon(Icons.refresh),
                ),
                IconButton(
                  tooltip: '关闭收藏夹',
                  onPressed: () => Navigator.pop(context),
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
            const Align(
              alignment: Alignment.centerLeft,
              child: Text(
                '留住喜欢的话。收藏不会额外写入 AI 记忆。',
                style: TextStyle(fontSize: 12, color: XinYuColors.muted),
              ),
            ),
            if (error != null)
              Padding(padding: const EdgeInsets.all(12), child: Text(error!)),
            if (working) const LinearProgressIndicator(),
            Flexible(
              child: ListView(
                shrinkWrap: true,
                children: [
                  if (items.isEmpty && !working && error == null)
                    const Padding(
                      padding: EdgeInsets.all(30),
                      child: Text('长按聊天消息，可以收藏到这里。'),
                    ),
                  for (final hit in items)
                    Padding(
                      padding: const EdgeInsets.only(top: 12),
                      child: GlassSurface(
                        radius: XinYuShapes.cardRadius,
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '${hit.message.isUser ? (widget.controller.userName.isEmpty ? '你' : widget.controller.userName) : widget.controller.companionName} · ${hit.title}',
                              style: const TextStyle(
                                fontSize: 12,
                                color: XinYuColors.muted,
                              ),
                            ),
                            const SizedBox(height: 8),
                            if (hit.message.text.isNotEmpty)
                              SelectableText(
                                hit.message.text,
                                style: const TextStyle(height: 1.7),
                              ),
                            for (final id in hit.message.imageIds)
                              ChatPhoto(controller: widget.controller, id: id),
                            if (hit.message.sticker != null)
                              StickerView(
                                item: hit.message.sticker!,
                                controller: widget.controller,
                              ),
                            Wrap(
                              children: [
                                if (widget.controller.localConnection != null)
                                  TextButton(
                                    onPressed: () => showMessageContext(
                                      context,
                                      widget.controller,
                                      hit.conversation,
                                      hit.message.id,
                                    ),
                                    child: const Text('查看原消息'),
                                  ),
                                TextButton(
                                  onPressed: () async {
                                    final copied = await widget.controller
                                        .copyText(hit.message.text);
                                    if (context.mounted && copied) {
                                      ScaffoldMessenger.of(
                                        context,
                                      ).showSnackBar(
                                        const SnackBar(content: Text('已复制文字')),
                                      );
                                    }
                                  },
                                  child: const Text('复制'),
                                ),
                                TextButton(
                                  onPressed: working
                                      ? null
                                      : () => remove(hit.message.id),
                                  child: const Text('取消收藏'),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ),
                  if (more)
                    TextButton(
                      onPressed: working ? null : () => load(append: true),
                      child: const Text('更多收藏'),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

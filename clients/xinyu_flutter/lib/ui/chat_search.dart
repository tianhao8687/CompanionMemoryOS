import 'dart:async';

import 'package:flutter/material.dart';

import '../data/models.dart';
import '../state/companion_controller.dart';
import 'chat.dart';
import 'glass.dart';

Future<void> showChatSearch(
  BuildContext context,
  CompanionController controller,
) =>
    showDialog<void>(context: context, builder: (_) => _ChatSearch(controller));

class _ChatSearch extends StatefulWidget {
  const _ChatSearch(this.controller);
  final CompanionController controller;
  @override
  State<_ChatSearch> createState() => _ChatSearchState();
}

class _ChatSearchState extends State<_ChatSearch> {
  final field = TextEditingController();
  Timer? debounce;
  int generation = 0;
  bool all = false, loading = false, more = false;
  int? before;
  List<SearchHit> results = [];
  String? error;
  @override
  void dispose() {
    debounce?.cancel();
    field.dispose();
    super.dispose();
  }

  void _changed() {
    debounce?.cancel();
    generation++;
    setState(() {
      results = [];
      before = null;
      more = false;
      error = null;
      loading = field.text.trim().isNotEmpty;
    });
    debounce = Timer(const Duration(milliseconds: 350), () => _search());
  }

  Future<void> _search({bool append = false}) async {
    final query = field.text.trim();
    if (query.isEmpty) return;
    final version = ++generation;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final data = await widget.controller.localConnection!.search(
        query,
        conversation: all ? null : widget.controller.active,
        before: append ? before : null,
      );
      if (!mounted || version != generation) return;
      setState(() {
        final hits = (data['results'] as List)
            .map((v) => SearchHit.fromJson(Map<String, dynamic>.from(v as Map)))
            .toList();
        results = append ? [...results, ...hits] : hits;
        before = data['before'] as int?;
        more = data['has_more'] == true;
      });
    } catch (e) {
      if (mounted && version == generation) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '搜索未完成'),
        );
      }
    } finally {
      if (mounted && version == generation) setState(() => loading = false);
    }
  }

  Future<void> _open(SearchHit hit) async {
    try {
      final messages = await widget.controller.localConnection!.context(
        hit.conversation,
        hit.message.id,
      );
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (_) => _SearchContext(widget.controller, hit, messages),
      );
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(
            e,
            title: '聊天记录暂时无法打开',
            fallback: '记录已不可用，请重新搜索。',
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) => Dialog(
    backgroundColor: Colors.transparent,
    insetPadding: const EdgeInsets.all(16),
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 680, maxHeight: 720),
      child: GlassSurface(
        radius: XinYuShapes.panelRadius,
        tint: const Color(0xeef4faf5),
        padding: const EdgeInsets.all(20),
        child: Column(
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text(
                    '翻翻我们的聊天',
                    style: TextStyle(fontSize: 21, fontWeight: FontWeight.w600),
                  ),
                ),
                IconButton(
                  tooltip: '关闭搜索',
                  onPressed: () => Navigator.pop(context),
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
            const SizedBox(height: 12),
            TextField(
              key: const Key('chat-search-input'),
              controller: field,
              autofocus: true,
              maxLength: 100,
              onChanged: (_) => _changed(),
              decoration: const InputDecoration(
                prefixIcon: Icon(Icons.search),
                hintText: '搜索聊天里的文字',
                counterText: '',
              ),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                ChoiceChip(
                  label: const Text('当前对话'),
                  selected: !all,
                  onSelected: (_) {
                    setState(() => all = false);
                    _changed();
                  },
                ),
                const SizedBox(width: 8),
                ChoiceChip(
                  label: const Text('全部对话'),
                  selected: all,
                  onSelected: (_) {
                    setState(() => all = true);
                    _changed();
                  },
                ),
              ],
            ),
            const SizedBox(height: 8),
            if (loading) const LinearProgressIndicator(),
            if (error != null)
              Row(
                children: [
                  Expanded(child: Text(error!)),
                  TextButton(
                    onPressed: () => _search(),
                    child: const Text('重试'),
                  ),
                ],
              ),
            Expanded(
              child: results.isEmpty
                  ? Center(
                      child: Text(
                        loading
                            ? '正在查找…'
                            : field.text.trim().isEmpty
                            ? '输入关键词，找回聊过的小事'
                            : '没有找到相关记录',
                        style: const TextStyle(color: XinYuColors.muted),
                      ),
                    )
                  : ListView.builder(
                      itemCount: results.length + (more ? 1 : 0),
                      itemBuilder: (_, i) {
                        if (i == results.length) {
                          return TextButton(
                            onPressed: loading
                                ? null
                                : () => _search(append: true),
                            child: const Text('更多结果'),
                          );
                        }
                        final hit = results[i];
                        final date =
                            hit.message.createdAt
                                ?.toLocal()
                                .toString()
                                .substring(0, 16) ??
                            '';
                        return Card(
                          color: const Color(0x99ffffff),
                          elevation: 0,
                          child: ListTile(
                            onTap: () => _open(hit),
                            title: Text(
                              hit.excerpt,
                              maxLines: 3,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontSize: 14, height: 1.6),
                            ),
                            subtitle: Padding(
                              padding: const EdgeInsets.only(top: 6),
                              child: Text(
                                '${hit.message.isUser ? '我' : widget.controller.companionName} · ${hit.title}\n$date',
                                style: const TextStyle(
                                  fontSize: 11,
                                  color: XinYuColors.muted,
                                ),
                              ),
                            ),
                            trailing: const Icon(Icons.chevron_right, size: 18),
                          ),
                        );
                      },
                    ),
            ),
            const Text(
              '搜索本机保存的文字 · 点开查看前后对话',
              style: TextStyle(fontSize: 11, color: XinYuColors.muted),
            ),
          ],
        ),
      ),
    ),
  );
}

class _SearchContext extends StatefulWidget {
  const _SearchContext(this.controller, this.hit, this.messages);
  final CompanionController controller;
  final SearchHit hit;
  final List<ChatLine> messages;
  @override
  State<_SearchContext> createState() => _SearchContextState();
}

class _SearchContextState extends State<_SearchContext> {
  final anchor = GlobalKey();
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && anchor.currentContext != null) {
        Scrollable.ensureVisible(anchor.currentContext!, alignment: .35);
      }
    });
  }

  @override
  Widget build(BuildContext context) => Dialog(
    backgroundColor: Colors.transparent,
    insetPadding: const EdgeInsets.all(12),
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 680, maxHeight: 720),
      child: GlassSurface(
        radius: XinYuShapes.panelRadius,
        tint: const Color(0xf2f4faf5),
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    widget.hit.title,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                IconButton(
                  tooltip: '返回搜索',
                  onPressed: () => Navigator.pop(context),
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
            Expanded(
              child: SingleChildScrollView(
                child: Column(
                  children: [
                    for (final message in widget.messages)
                      Container(
                        key: message.id == widget.hit.message.id
                            ? anchor
                            : null,
                        padding: const EdgeInsets.all(6),
                        decoration: BoxDecoration(
                          color: message.id == widget.hit.message.id
                              ? const Color(0x35c8a85b)
                              : Colors.transparent,
                          borderRadius: XinYuShapes.cardCorners,
                        ),
                        child: MessageBubble(
                          interactive: false,
                          line: message,
                          controller: widget.controller,
                          name: widget.controller.companionName,
                        ),
                      ),
                  ],
                ),
              ),
            ),
            TextButton(
              onPressed: () async {
                await widget.controller.select(widget.hit.conversation);
                if (context.mounted) Navigator.pop(context);
              },
              child: const Text('切换到这段对话'),
            ),
          ],
        ),
      ),
    ),
  );
}

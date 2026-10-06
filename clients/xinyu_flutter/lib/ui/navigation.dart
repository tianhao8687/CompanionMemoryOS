import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import 'bookmarks.dart';
import 'glass.dart';
import 'local_image.dart';
import 'memory_sheet.dart';

class CompanionNavigation extends StatefulWidget {
  const CompanionNavigation({
    super.key,
    required this.controller,
    this.close,
    required this.openSettings,
  });
  final CompanionController controller;
  final VoidCallback? close;
  final VoidCallback openSettings;
  @override
  State<CompanionNavigation> createState() => _CompanionNavigationState();
}

class _CompanionNavigationState extends State<CompanionNavigation> {
  final search = TextEditingController();
  String query = '';
  @override
  void dispose() {
    search.dispose();
    super.dispose();
  }

  String _date(DateTime? value) {
    if (value == null) return '';
    final local = value.toLocal();
    final now = DateTime.now();
    final day = DateTime(local.year, local.month, local.day);
    final today = DateTime(now.year, now.month, now.day);
    if (day == today) {
      return '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
    }
    if (today.difference(day).inDays == 1) return '昨天';
    if (today.difference(day).inDays > 1 && today.difference(day).inDays < 7) {
      return const [
        '星期一',
        '星期二',
        '星期三',
        '星期四',
        '星期五',
        '星期六',
        '星期日',
      ][local.weekday - 1];
    }
    return '${local.month}/${local.day}';
  }

  Widget _inset(Widget child) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 10),
    child: child,
  );

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    final items = c.conversations.where(
      (item) => item.title.toLowerCase().contains(query.trim().toLowerCase()),
    );
    return GlassSurface(
      key: const Key('conversation-navigation'),
      radius: 24,
      tint: const Color(0x60ffffff),
      padding: const EdgeInsets.fromLTRB(12, 24, 12, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _inset(
            Row(
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: Image.asset(
                    'assets/branding/xinyu-logo.png',
                    width: 32,
                    height: 32,
                    semanticLabel: '心隅',
                  ),
                ),
                const SizedBox(width: 10),
                const Expanded(
                  child: Text(
                    '对话',
                    style: TextStyle(fontSize: 22, fontWeight: FontWeight.w500),
                  ),
                ),
                if (widget.close != null)
                  IconButton(
                    tooltip: '收起对话列表',
                    onPressed: widget.close,
                    icon: const Icon(Icons.close_rounded, size: 21),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          _inset(
            TextField(
              key: const Key('conversation-filter'),
              controller: search,
              onChanged: (value) => setState(() => query = value),
              style: const TextStyle(fontSize: 15),
              decoration: InputDecoration(
                hintText: '搜索对话',
                isDense: true,
                fillColor: const Color(0x38ffffff),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(18),
                  borderSide: const BorderSide(color: Color(0x90dbe2eb)),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(18),
                  borderSide: const BorderSide(color: XinYuColors.accent),
                ),
                prefixIcon: const Icon(Icons.search_rounded, size: 21),
                suffixIcon: query.isEmpty
                    ? null
                    : IconButton(
                        tooltip: '清除搜索',
                        onPressed: () {
                          search.clear();
                          setState(() => query = '');
                        },
                        icon: const Icon(Icons.close_rounded, size: 18),
                      ),
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 14,
                  vertical: 12,
                ),
              ),
            ),
          ),
          const SizedBox(height: 12),
          _inset(
            OutlinedButton.icon(
              key: const Key('new-conversation'),
              onPressed: c.busy
                  ? null
                  : () {
                      c.newConversation();
                      widget.close?.call();
                    },
              style: OutlinedButton.styleFrom(
                minimumSize: const Size.fromHeight(48),
                backgroundColor: const Color(0x80ffffff),
                side: const BorderSide(color: Color(0xffdce3eb), width: .8),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                ),
              ),
              icon: const Icon(Icons.add_rounded, size: 21),
              label: const Text('新对话', style: TextStyle(fontSize: 16)),
            ),
          ),
          const SizedBox(height: 24),
          _inset(
            const Text(
              '最近',
              style: TextStyle(fontSize: 14, color: XinYuColors.muted),
            ),
          ),
          const SizedBox(height: 10),
          Expanded(
            child: items.isEmpty
                ? Center(
                    child: Text(
                      query.isEmpty ? '从一段新对话开始' : '没有找到这段对话',
                      style: const TextStyle(
                        color: XinYuColors.muted,
                        fontSize: 13,
                      ),
                    ),
                  )
                : ListView(
                    padding: EdgeInsets.zero,
                    children: [
                      for (final item in items)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 6),
                          child: Material(
                            color: item.id == c.active
                                ? const Color(0xb3e1eaf5)
                                : Colors.transparent,
                            borderRadius: BorderRadius.circular(16),
                            child: InkWell(
                              key: ValueKey('conversation-${item.id}'),
                              borderRadius: BorderRadius.circular(16),
                              onTap: c.busy
                                  ? null
                                  : () {
                                      c.select(item.id);
                                      widget.close?.call();
                                    },
                              child: Padding(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 12,
                                  vertical: 12,
                                ),
                                child: Row(
                                  children: [
                                    ProfileAvatar(controller: c, size: 52),
                                    const SizedBox(width: 14),
                                    Expanded(
                                      child: Column(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.start,
                                        children: [
                                          Row(
                                            children: [
                                              Expanded(
                                                child: Text(
                                                  item.title,
                                                  maxLines: 1,
                                                  overflow:
                                                      TextOverflow.ellipsis,
                                                  style: TextStyle(
                                                    fontSize: 16,
                                                    height: 1.45,
                                                    fontWeight:
                                                        item.id == c.active
                                                        ? FontWeight.w500
                                                        : FontWeight.w400,
                                                  ),
                                                ),
                                              ),
                                              if (item.unread > 0) ...[
                                                const SizedBox(width: 6),
                                                Badge(
                                                  label: Text('${item.unread}'),
                                                ),
                                              ] else if (item.updatedAt !=
                                                  null) ...[
                                                const SizedBox(width: 8),
                                                Text(
                                                  _date(item.updatedAt),
                                                  style: const TextStyle(
                                                    fontSize: 12,
                                                    color: XinYuColors.muted,
                                                  ),
                                                ),
                                              ],
                                            ],
                                          ),
                                          if (item.id == c.active &&
                                              c.messages.isNotEmpty) ...[
                                            const SizedBox(height: 4),
                                            Text(
                                              c.messages.last.text.replaceAll(
                                                RegExp(r'\s+'),
                                                ' ',
                                              ),
                                              maxLines: 1,
                                              overflow: TextOverflow.ellipsis,
                                              style: const TextStyle(
                                                fontSize: 13,
                                                color: XinYuColors.muted,
                                              ),
                                            ),
                                          ],
                                        ],
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
          ),
          _inset(const Divider(color: Color(0xffdce2e8), height: 24)),
          Row(
            children: [
              _shortcut(
                '收藏',
                Icons.star_border_rounded,
                c.hasExperience ? () => showBookmarks(context, c) : null,
              ),
              _shortcut(
                '手账',
                Icons.book_outlined,
                c.busy || !c.connected ? null : () => showMemories(context, c),
              ),
              _shortcut('设置', Icons.settings_outlined, widget.openSettings),
            ],
          ),
        ],
      ),
    );
  }

  Widget _shortcut(String label, IconData icon, VoidCallback? onPressed) =>
      Expanded(
        child: TextButton(
          onPressed: onPressed,
          style: TextButton.styleFrom(
            padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 4),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 20),
              const SizedBox(height: 6),
              Text(label, style: const TextStyle(fontSize: 13)),
            ],
          ),
        ),
      );
}

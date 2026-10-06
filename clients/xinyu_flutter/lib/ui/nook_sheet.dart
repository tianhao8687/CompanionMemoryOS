import 'dart:async';

import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import 'nook_scene.dart';

Future<void> showMemoryNook(
  BuildContext context,
  CompanionController controller,
) => showDialog<void>(
  context: context,
  builder: (_) => NookSheet(controller: controller),
);

class NookSheet extends StatefulWidget {
  const NookSheet({super.key, required this.controller});
  final CompanionController controller;
  @override
  State<NookSheet> createState() => _NookSheetState();
}

class _NookSheetState extends State<NookSheet> {
  final sceneKey = GlobalKey<NookSceneState>();
  final detailKey = GlobalKey();
  Map<String, dynamic>? room;
  String? selected, at, error;
  Timer? timer;
  int generation = 0;
  bool working = false;
  List<Map<String, dynamic>> get items => (room?['items'] as List? ?? [])
      .map((v) => Map<String, dynamic>.from(v as Map))
      .toList();
  List<String> get timeline =>
      (room?['timeline'] as List? ?? []).cast<String>();
  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    timer?.cancel();
    generation++;
    super.dispose();
  }

  Future<void> _load() async {
    final current = ++generation;
    try {
      final result = await widget.controller.localConnection!.nook(at: at);
      if (!mounted || current != generation) return;
      setState(() {
        room = result;
        error = null;
        if (!items.any((o) => o['id'] == selected)) {
          selected = null;
        }
      });
      timer?.cancel();
      if (result['busy'] == true) {
        timer = Timer(const Duration(seconds: 2), _load);
      }
    } catch (e) {
      if (mounted && current == generation) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '小窝暂时无法读取'),
        );
      }
    }
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      working = true;
      error = null;
    });
    try {
      await action();
      await _load();
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '小窝操作未完成'),
        );
      }
    } finally {
      if (mounted) {
        setState(() => working = false);
      }
    }
  }

  Future<void> _settings(bool enabled, int limit) => _run(() async {
    await widget.controller.localConnection!.nookSettings(enabled, limit);
    widget.controller.settings.addAll({
      'nook_enabled': enabled,
      'nook_daily_limit': limit,
    });
  });
  void _choose(String id) {
    setState(() => selected = id);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || detailKey.currentContext == null) return;
      Scrollable.ensureVisible(
        detailKey.currentContext!,
        duration: MediaQuery.disableAnimationsOf(context)
            ? Duration.zero
            : const Duration(milliseconds: 240),
        alignment: .2,
      );
    });
  }

  void _backToRoom() {
    setState(() => selected = null);
    sceneKey.currentState?.showOverview();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || sceneKey.currentContext == null) return;
      Scrollable.ensureVisible(
        sceneKey.currentContext!,
        duration: MediaQuery.disableAnimationsOf(context)
            ? Duration.zero
            : const Duration(milliseconds: 240),
      );
    });
  }

  Widget _choices(bool displayed) => Wrap(
    spacing: 8,
    runSpacing: 8,
    children: [
      for (final item in items.where((o) => o['displayed'] == displayed))
        ChoiceChip(
          label: Text('${item['pinned'] == true ? '♡ ' : ''}${item['title']}'),
          selected: selected == item['id'],
          avatar: NookSprite(
            art: Map<String, dynamic>.from(item['art'] as Map),
            side: 28,
          ),
          onSelected: (_) => _choose(item['id'] as String),
        ),
    ],
  );
  Widget _detail(Map<String, dynamic> item) => Container(
    key: detailKey,
    width: double.infinity,
    margin: const EdgeInsets.only(top: 16),
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: const Color(0xfff1eadb),
      borderRadius: BorderRadius.circular(18),
    ),
    child: Material(
      type: MaterialType.transparency,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Center(
            child: Semantics(
              label: '${item['title']}，像素画放大近看',
              image: true,
              child: Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: const Color(0xfffcf7ed),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: NookSprite(
                  art: Map<String, dynamic>.from(item['art'] as Map),
                  side: ((item['art'] as Map)['rows'] as List).length * 4.0,
                ),
              ),
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item['title'] as String,
                      style: const TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                    Text(
                      item['reality_layer'] == 'roleplay'
                          ? '故事里的纪念品 · AI 原创'
                          : '回忆的纪念品 · AI 原创',
                      style: const TextStyle(
                        fontSize: 12,
                        color: Color(0xff65745b),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(item['meaning'] as String),
          if (item['pinned'] == true)
            const Padding(
              padding: EdgeInsets.only(top: 8),
              child: Text(
                '已珍藏：TA 会保留这一版和它的位置。',
                style: TextStyle(fontSize: 12, color: Color(0xff65745b)),
              ),
            ),
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: const Text('看看创作来源', style: TextStyle(fontSize: 13)),
            children: [
              for (final source in (item['evidence'] as List).cast<Map>())
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: SelectableText(
                    source['content'] as String,
                    style: const TextStyle(fontSize: 13),
                  ),
                  subtitle: Text((source['at'] as String).split('T').first),
                  trailing: source['conversation_id'] == null
                      ? null
                      : TextButton(
                          onPressed: widget.controller.busy
                              ? null
                              : () async {
                                  await widget.controller.select(
                                    source['conversation_id'] as String,
                                  );
                                  if (mounted &&
                                      widget.controller.error == null) {
                                    Navigator.of(context).pop();
                                  }
                                },
                          child: const Text('回到这段聊天'),
                        ),
                ),
            ],
          ),
          TextButton(onPressed: _backToRoom, child: const Text('回到小窝')),
          if (at == null)
            Wrap(
              spacing: 8,
              children: [
                FilledButton.tonal(
                  onPressed: working
                      ? null
                      : () {
                          if (widget.controller.composeKeepsakeChat(
                            item['title'] as String,
                          )) {
                            Navigator.of(context).pop();
                          }
                        },
                  child: const Text('聊聊这件'),
                ),
                TextButton(
                  onPressed: working
                      ? null
                      : () => _run(() async {
                          await widget.controller.localConnection!
                              .cherishNookObject(
                                item['id'] as String,
                                item['pinned'] != true,
                              );
                        }),
                  child: Text(item['pinned'] == true ? '取消珍藏' : '珍藏这一版'),
                ),
              ],
            ),
          if (at == null)
            TextButton(
              onPressed: working
                  ? null
                  : () => _run(() async {
                      await widget.controller.localConnection!
                          .displayNookObject(
                            item['id'] as String,
                            item['displayed'] != true,
                          );
                    }),
              child: Text(item['displayed'] == true ? '收进收纳盒' : '摆回小窝'),
            ),
        ],
      ),
    ),
  );
  @override
  Widget build(BuildContext context) {
    final current = items.where((o) => o['id'] == selected).firstOrNull;
    final enabled = room?['enabled'] == true;
    final limit = room?['daily_limit'] as int? ?? 3;
    final busy = working || room?['busy'] == true;
    return Dialog(
      backgroundColor: const Color(0xfffcf7ed),
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: 760,
          maxHeight: MediaQuery.sizeOf(context).height * .88,
        ),
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Expanded(
                    child: Text(
                      '回忆小窝',
                      style: TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                  IconButton(
                    tooltip: '关闭回忆小窝',
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
              const Text(
                '让聊过的小事，住进一间像素小屋。',
                style: TextStyle(color: Color(0xff65745b)),
              ),
              const SizedBox(height: 16),
              NookScene(
                key: sceneKey,
                items: items,
                selected: selected,
                onSelected: _choose,
              ),
              if (room == null && error == null)
                const Padding(
                  padding: EdgeInsets.all(16),
                  child: LinearProgressIndicator(),
                ),
              if (room != null && !items.any((o) => o['displayed'] == true))
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Text(
                    '小窝还空着。聊起喜欢的东西、有名字的小事，或刚完成的心愿，给 TA 一点灵感。',
                    style: TextStyle(fontSize: 13),
                  ),
                ),
              if (timeline.isNotEmpty) ...[
                const SizedBox(height: 14),
                Row(
                  children: [
                    const Text('回看小窝'),
                    const Spacer(),
                    Text(
                      at == null
                          ? '现在'
                          : at!.split('.').first.replaceFirst('T', ' '),
                      style: const TextStyle(fontSize: 11),
                    ),
                  ],
                ),
                Slider(
                  value: at == null
                      ? timeline.length.toDouble()
                      : timeline
                            .indexOf(at!)
                            .clamp(0, timeline.length)
                            .toDouble(),
                  max: timeline.length.toDouble(),
                  divisions: timeline.length,
                  label: at == null ? '现在' : at!.split('T').first,
                  onChanged: busy
                      ? null
                      : (value) {
                          setState(
                            () => at = value.round() < timeline.length
                                ? timeline[value.round()]
                                : null,
                          );
                          _load();
                        },
                ),
              ],
              _choices(true),
              if (current != null) _detail(current),
              ExpansionTile(
                tilePadding: EdgeInsets.zero,
                title: Text(
                  '收纳盒 · ${items.where((o) => o['displayed'] != true).length}',
                ),
                children: [_choices(false)],
              ),
              Semantics(
                liveRegion: true,
                child: Text(
                  error ?? room?['message'] as String? ?? '正在打开小窝…',
                  style: TextStyle(
                    fontSize: 13,
                    color: error == null
                        ? const Color(0xff65745b)
                        : Theme.of(context).colorScheme.error,
                  ),
                ),
              ),
              const SizedBox(height: 12),
              const Divider(),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('让 TA 自动创作'),
                subtitle: const Text('聊天后使用当前模型挑选回忆、绘制像素小物件，会使用额外模型额度。'),
                value: enabled,
                onChanged: working || room == null
                    ? null
                    : (v) => _settings(v, limit),
              ),
              Row(
                children: [
                  const Expanded(child: Text('每天最多创作次数')),
                  DropdownButton<int>(
                    value: limit,
                    items: [
                      for (var i = 1; i <= 12; i++)
                        DropdownMenuItem(value: i, child: Text('$i')),
                    ],
                    onChanged: working
                        ? null
                        : (v) {
                            if (v != null) _settings(enabled, v);
                          },
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 10,
                runSpacing: 8,
                children: [
                  FilledButton(
                    onPressed:
                        busy ||
                            !enabled ||
                            at != null ||
                            widget.controller.active == null
                        ? null
                        : () => _run(() async {
                            final result = await widget
                                .controller
                                .localConnection!
                                .createNookObject(widget.controller.active!);
                            if (result['status'] != 'drawing') {
                              throw StateError(result['message'] as String);
                            }
                          }),
                    child: Text(busy ? '正在创作…' : '让 TA 布置一下'),
                  ),
                  OutlinedButton(
                    onPressed: working ? null : _load,
                    child: const Text('刷新小窝'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

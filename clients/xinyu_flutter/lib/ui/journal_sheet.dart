import 'package:flutter/material.dart';

import '../data/models.dart';
import '../state/companion_controller.dart';
import 'glass.dart';
import 'local_image.dart';
import 'message_context.dart';

const journalCategories = {
  'all': '全部',
  'self': '关于我',
  'companion': '关于 TA',
  'together': '共同经历',
  'promises': '约定',
};
String journalDate(DateTime date) =>
    '${date.year.toString().padLeft(4, '0')}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
String journalRequest() => 'journal-${DateTime.now().microsecondsSinceEpoch}';

Future<void> showJournal(
  BuildContext context,
  CompanionController controller,
) => showDialog<void>(
  context: context,
  builder: (_) => JournalSheet(controller: controller),
);

Future<void> saveChatMoment(
  BuildContext context,
  CompanionController controller,
  ChatLine line,
) async {
  if (controller.busy || controller.active == null) return;
  await showDialog<bool>(
    context: context,
    builder: (_) => MomentEditor(controller: controller, source: line),
  );
  await controller.refreshUpdates();
}

class JournalSheet extends StatefulWidget {
  const JournalSheet({super.key, required this.controller});
  final CompanionController controller;
  @override
  State<JournalSheet> createState() => _JournalSheetState();
}

class _JournalSheetState extends State<JournalSheet> {
  int tab = 0, offset = 0, generation = 0;
  String category = 'all';
  bool loading = false, more = false, closed = false;
  List<Map<String, dynamic>> items = [];
  String? error;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load({bool append = false}) async {
    final version = ++generation;
    setState(() {
      loading = true;
      error = null;
      if (!append) {
        items = [];
        offset = 0;
        more = false;
      }
    });
    try {
      final repository = widget.controller.localConnection!;
      if (tab == 1) {
        final result = await repository.journalEvents();
        if (!mounted || version != generation) return;
        setState(() {
          items = result;
          more = false;
        });
      } else {
        final result = await repository.journal(
          moments: tab == 2,
          category: tab == 2 ? 'all' : category,
          offset: append ? offset : 0,
        );
        if (!mounted || version != generation) return;
        setState(() {
          final rows = (result['items'] as List)
              .map((v) => Map<String, dynamic>.from(v as Map))
              .toList();
          items = append ? [...items, ...rows] : rows;
          more = result['has_more'] == true;
          offset = result['offset'] as int;
        });
      }
    } catch (e) {
      if (mounted && version == generation) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '记忆手账暂时无法读取'),
        );
      }
    } finally {
      if (mounted && version == generation) setState(() => loading = false);
    }
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      await action();
      if (mounted) await _load();
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '手账操作未完成'),
        );
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _edit(Map<String, dynamic> record) async {
    final value = await showDialog<String>(
      context: context,
      builder: (_) => _CorrectionDialog(record['content'] as String),
    );
    if (value == null || !mounted) return;
    await _run(() async {
      await widget.controller.localConnection!.editMemory(
        record['id'] as String,
        value,
        widget.controller.active!,
      );
      await widget.controller.initialize();
    });
  }

  Future<void> _forget(Map<String, dynamic> record) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('忘记这段记忆？'),
        content: const Text('将按遗忘规则清理记忆、关联来源和图片。以前导出的备份不受影响。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('确认遗忘'),
          ),
        ],
      ),
    );
    if (yes != true || !mounted) return;
    await _run(() async {
      await widget.controller.localConnection!.forgetMemory(
        record['id'] as String,
      );
      await widget.controller.initialize();
    });
  }

  Future<void> _sources(Map<String, dynamic> item) async {
    final sources = (item['sources'] as List? ?? [])
        .cast<Map<String, dynamic>>();
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('这段记忆来自'),
        content: SizedBox(
          width: 500,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (sources.isEmpty) const Text('这条旧记忆没有可打开的消息来源。'),
                for (final source in sources)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(
                      source['excerpt'] as String,
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                    ),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => showMessageContext(
                      context,
                      widget.controller,
                      source['conversation_id'] as String,
                      source['id'] as String,
                    ),
                  ),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('关闭'),
          ),
        ],
      ),
    );
  }

  Future<void> _changeCategory(Map<String, dynamic> item) async {
    final chosen = await showDialog<String>(
      context: context,
      builder: (context) => SimpleDialog(
        title: const Text('放在哪一页'),
        children: [
          for (final entry in journalCategories.entries.where(
            (e) => e.key != 'all',
          ))
            SimpleDialogOption(
              onPressed: () => Navigator.pop(context, entry.key),
              child: Text(entry.value),
            ),
        ],
      ),
    );
    if (chosen != null && mounted) {
      await _run(() async {
        await widget.controller.localConnection!.journalFlags(
          item['id'] as String,
          chosen,
          item['important'] == true,
        );
      });
    }
  }

  Future<void> _eventEditor([Map<String, dynamic>? item]) async {
    await showDialog<bool>(
      context: context,
      builder: (_) =>
          JournalEventEditor(controller: widget.controller, event: item),
    );
    if (mounted) await _load();
    await widget.controller.refreshUpdates();
  }

  Future<void> _addMoment() async {
    await showDialog<bool>(
      context: context,
      builder: (_) => MomentEditor(controller: widget.controller),
    );
    if (mounted) await _load();
    await widget.controller.refreshUpdates();
  }

  Widget _card(Widget child) => Container(
    margin: const EdgeInsets.only(bottom: 12),
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: const Color(0x70ffffff),
      borderRadius: XinYuShapes.cardCorners,
      border: Border.all(color: const Color(0xb0ffffff)),
    ),
    child: child,
  );

  Widget _memory(Map<String, dynamic> item) => _card(
    Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                item['title'] as String? ?? '记住的小事',
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            IconButton(
              tooltip: item['important'] == true ? '取消重要标记' : '标记重要',
              onPressed: loading
                  ? null
                  : () => _run(() async {
                      await widget.controller.localConnection!.journalFlags(
                        item['id'] as String,
                        item['category'] as String,
                        item['important'] != true,
                      );
                    }),
              icon: Icon(
                item['important'] == true
                    ? Icons.star_rounded
                    : Icons.star_border_rounded,
                color: item['important'] == true
                    ? const Color(0xffaf8048)
                    : XinYuColors.muted,
              ),
            ),
          ],
        ),
        Wrap(
          spacing: 8,
          runSpacing: 4,
          children: [
            Text(
              journalCategories[item['category']] ?? '记忆',
              style: const TextStyle(color: XinYuColors.muted, fontSize: 12),
            ),
            if (item['reality_layer'] != 'real_world')
              const Text(
                '剧情记忆',
                style: TextStyle(color: Color(0xff9b7057), fontSize: 12),
              ),
            if (tab == 2)
              Text(
                item['happened_on'] as String,
                style: const TextStyle(color: XinYuColors.muted, fontSize: 12),
              ),
          ],
        ),
        const SizedBox(height: 10),
        SelectableText(
          item['content'] as String,
          style: const TextStyle(height: 1.65),
        ),
        if ((item['image_ids'] as List? ?? []).isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final id in item['image_ids'] as List)
                  SizedBox(
                    width: 130,
                    child: ChatPhoto(
                      controller: widget.controller,
                      id: id as String,
                    ),
                  ),
              ],
            ),
          ),
        const SizedBox(height: 6),
        Wrap(
          spacing: 4,
          children: [
            TextButton.icon(
              onPressed: () => _sources(item),
              icon: const Icon(Icons.history_rounded, size: 17),
              label: const Text('来源'),
            ),
            TextButton(
              onPressed: loading ? null : () => _changeCategory(item),
              child: const Text('分类'),
            ),
            TextButton(
              onPressed: loading ? null : () => _edit(item),
              child: const Text('更正'),
            ),
            TextButton(
              onPressed: loading ? null : () => _forget(item),
              child: const Text('遗忘'),
            ),
          ],
        ),
      ],
    ),
  );

  Widget _event(Map<String, dynamic> item) {
    final status = item['status'] as String;
    final active = !{'cancelled', 'resolved', 'invalidated'}.contains(status);
    final mode = item['mode'];
    final state = switch (status) {
      'cancelled' => '已取消',
      'resolved' => '已完成',
      'waiting' => item['reason'] == 'missed' ? '已过提醒时间' : '已提醒',
      'candidate' => '仅记录',
      _ => mode == 'checkin' ? '等待 TA 问候' : '等待提醒',
    };
    final until = item['days_until'] as int?;
    return _card(
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                item['kind'] == 'anniversary'
                    ? Icons.favorite_border_rounded
                    : Icons.event_outlined,
                color: const Color(0xff9b7057),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  item['title'] as String,
                  style: const TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              if (active && until != null && until >= 0)
                Text(
                  until == 0 ? '今天' : '还有 $until 天',
                  style: const TextStyle(color: XinYuColors.accent),
                ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            item['event_date'] == null
                ? '还没有设置日期'
                : '${item['event_date']} · ${item['at']} ${item['yearly'] == true ? '· 每年' : ''}',
            style: const TextStyle(color: XinYuColors.muted),
          ),
          if (item['yearly'] == true && item['next_local'] != null)
            Text(
              '下次：${item['next_local']}（${item['timezone']}）',
              style: const TextStyle(color: XinYuColors.muted, fontSize: 12),
            ),
          if ((item['note'] as String? ?? '').isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(item['note'] as String),
            ),
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              state,
              style: const TextStyle(color: XinYuColors.muted, fontSize: 12),
            ),
          ),
          Wrap(
            spacing: 4,
            children: [
              TextButton(
                onPressed: () => showMessageContext(
                  context,
                  widget.controller,
                  item['conversation_id'] as String,
                  item['source_turn'] as String,
                ),
                child: const Text('原记录'),
              ),
              if (active)
                TextButton(
                  onPressed: loading ? null : () => _eventEditor(item),
                  child: const Text('编辑'),
                ),
              if (active)
                TextButton(
                  onPressed: loading
                      ? null
                      : () => _run(() async {
                          await widget.controller.localConnection!
                              .closeJournalEvent(
                                item['id'] as String,
                                'resolved',
                              );
                          await widget.controller.refreshUpdates();
                        }),
                  child: const Text('完成'),
                ),
              if (active)
                TextButton(
                  onPressed: loading
                      ? null
                      : () => _run(() async {
                          await widget.controller.localConnection!
                              .closeJournalEvent(
                                item['id'] as String,
                                'cancelled',
                              );
                          await widget.controller.refreshUpdates();
                        }),
                  child: const Text('取消约定'),
                ),
            ],
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final shown = tab == 1 && !closed
        ? items
              .where(
                (e) => !{
                  'cancelled',
                  'resolved',
                  'invalidated',
                }.contains(e['status']),
              )
              .toList()
        : items;
    return Dialog(
      backgroundColor: Colors.transparent,
      insetPadding: const EdgeInsets.all(12),
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: 760,
          maxHeight: MediaQuery.sizeOf(context).height * .9,
        ),
        child: BackdropGroup(
          child: GlassSurface(
            tint: const Color(0xdff5faf5),
            padding: const EdgeInsets.all(16),
            child: Column(
              children: [
                Row(
                  children: [
                    const Expanded(
                      child: Text(
                        '我们的手账',
                        style: TextStyle(
                          fontSize: 23,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: '刷新手账',
                      onPressed: loading ? null : () => _load(),
                      icon: const Icon(Icons.refresh),
                    ),
                    IconButton(
                      tooltip: '关闭手账',
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.close),
                    ),
                  ],
                ),
                const Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    '记得你，也记得一起走过的日子。',
                    style: TextStyle(color: XinYuColors.muted, fontSize: 12),
                  ),
                ),
                const SizedBox(height: 14),
                SizedBox(
                  width: double.infinity,
                  child: Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final entry in const {
                        0: '记忆',
                        1: '纪念与约定',
                        2: '共同回忆',
                      }.entries)
                        ChoiceChip(
                          showCheckmark: false,
                          label: Text(entry.value, softWrap: false),
                          selected: tab == entry.key,
                          onSelected: (_) {
                            setState(() => tab = entry.key);
                            _load();
                          },
                        ),
                    ],
                  ),
                ),
                const SizedBox(height: 10),
                if (tab == 0)
                  SizedBox(
                    height: 44,
                    child: ListView(
                      scrollDirection: Axis.horizontal,
                      children: [
                        for (final entry in journalCategories.entries)
                          Padding(
                            padding: const EdgeInsets.only(right: 6),
                            child: ChoiceChip(
                              label: Text(entry.value),
                              selected: category == entry.key,
                              onSelected: (_) {
                                setState(() => category = entry.key);
                                _load();
                              },
                            ),
                          ),
                      ],
                    ),
                  ),
                if (tab == 1)
                  Row(
                    children: [
                      Expanded(
                        child: TextButton.icon(
                          onPressed: loading ? null : _eventEditor,
                          icon: const Icon(Icons.add),
                          label: const Text('记下日期或约定'),
                        ),
                      ),
                      FilterChip(
                        label: const Text('已结束'),
                        selected: closed,
                        onSelected: (v) => setState(() => closed = v),
                      ),
                    ],
                  ),
                if (tab == 2)
                  Align(
                    alignment: Alignment.centerLeft,
                    child: TextButton.icon(
                      onPressed: loading ? null : _addMoment,
                      icon: const Icon(Icons.add_photo_alternate_outlined),
                      label: const Text('留下一段回忆'),
                    ),
                  ),
                if (loading) const LinearProgressIndicator(),
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.all(8),
                    child: Text(
                      error!,
                      style: const TextStyle(color: Color(0xffa25148)),
                    ),
                  ),
                Expanded(
                  child: shown.isEmpty && !loading
                      ? Center(
                          child: Text(
                            tab == 0
                                ? '聊过的小事，会慢慢收在这里。'
                                : tab == 1
                                ? '把值得记住的日期写下来。'
                                : '一张照片，一句话，留住属于我们的片刻。',
                            textAlign: TextAlign.center,
                            style: const TextStyle(color: XinYuColors.muted),
                          ),
                        )
                      : ListView.builder(
                          padding: const EdgeInsets.only(top: 8, bottom: 12),
                          itemCount: shown.length + (more ? 1 : 0),
                          itemBuilder: (_, index) => index == shown.length
                              ? TextButton(
                                  onPressed: loading
                                      ? null
                                      : () => _load(append: true),
                                  child: const Text('查看更多'),
                                )
                              : tab == 1
                              ? _event(shown[index])
                              : _memory(shown[index]),
                        ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class MomentEditor extends StatefulWidget {
  const MomentEditor({super.key, required this.controller, this.source});
  final CompanionController controller;
  final ChatLine? source;
  @override
  State<MomentEditor> createState() => _MomentEditorState();
}

class _MomentEditorState extends State<MomentEditor> {
  final title = TextEditingController(), content = TextEditingController();
  final form = GlobalKey<FormState>();
  final request = journalRequest();
  late final String conversation = widget.controller.active!;
  late final List<String> images = [...?widget.source?.imageIds];
  final owned = <String>[];
  DateTime day = DateTime.now();
  bool story = false, saving = false, saved = false, importing = false;
  String? error;
  @override
  void initState() {
    super.initState();
    final source = widget.source;
    if (source != null) {
      day = source.createdAt?.toLocal() ?? DateTime.now();
      content.text = '我们聊到：${source.text}'.characters.take(2000).toString();
    }
  }

  @override
  void dispose() {
    title.dispose();
    content.dispose();
    if (!saved) {
      for (final image in owned) {
        widget.controller.discardImage(image);
      }
    }
    super.dispose();
  }

  Future<void> _image() async {
    setState(() {
      importing = true;
      error = null;
    });
    try {
      final image = await widget.controller.importImage('moment');
      if (image != null) {
        if (!mounted) {
          widget.controller.discardImage(image);
          return;
        }
        setState(() {
          images.add(image);
          owned.add(image);
        });
      }
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '回忆图片未能导入'),
        );
      }
    } finally {
      if (mounted) setState(() => importing = false);
    }
  }

  Future<void> _save() async {
    if (!form.currentState!.validate()) return;
    setState(() {
      saving = true;
      error = null;
    });
    try {
      await widget.controller.localConnection!.saveMoment({
        'request_id': request,
        'conversation_id': conversation,
        'title': title.text.trim(),
        'content': content.text.trim(),
        'happened_on': journalDate(day),
        'reality_layer': story ? 'roleplay' : 'real_world',
        'source_ids': [if (widget.source != null) widget.source!.id],
        'image_ids': images,
      });
      saved = true;
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '共同回忆未保存'),
        );
      }
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !saving && !importing,
    child: AlertDialog(
      title: const Text('留下一段共同回忆'),
      content: SizedBox(
        width: 540,
        child: SingleChildScrollView(
          child: Form(
            key: form,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextFormField(
                  key: const Key('moment-title'),
                  controller: title,
                  maxLength: 80,
                  decoration: const InputDecoration(labelText: '给这段回忆起个名字'),
                  validator: (v) =>
                      v == null || v.trim().isEmpty ? '请填写标题' : null,
                ),
                TextFormField(
                  key: const Key('moment-content'),
                  controller: content,
                  maxLength: 2000,
                  minLines: 3,
                  maxLines: 6,
                  decoration: const InputDecoration(labelText: '想记住什么'),
                  validator: (v) =>
                      v == null || v.trim().isEmpty ? '请写下想记住的内容' : null,
                ),
                TextButton.icon(
                  icon: const Icon(Icons.calendar_month),
                  label: Text(journalDate(day)),
                  onPressed: saving
                      ? null
                      : () async {
                          final chosen = await showDatePicker(
                            context: context,
                            initialDate: day,
                            firstDate: DateTime(1900),
                            lastDate: DateTime.now(),
                            helpText: '回忆发生在哪一天',
                            cancelText: '取消',
                            confirmText: '确定',
                          );
                          if (chosen != null && mounted) {
                            setState(() => day = chosen);
                          }
                        },
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('这是故事里的经历'),
                  subtitle: const Text('剧情记忆与日常生活分开保存'),
                  value: story,
                  onChanged: saving ? null : (v) => setState(() => story = v),
                ),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final image in images)
                      SizedBox(
                        width: 88,
                        height: 98,
                        child: Stack(
                          children: [
                            ClipRRect(
                              borderRadius: XinYuShapes.fieldCorners,
                              child: LocalImage(
                                controller: widget.controller,
                                id: image,
                                width: 88,
                                height: 88,
                              ),
                            ),
                            Positioned(
                              right: 0,
                              top: 0,
                              child: IconButton.filledTonal(
                                tooltip: '移除回忆图片',
                                icon: const Icon(Icons.close, size: 16),
                                onPressed: saving
                                    ? null
                                    : () {
                                        setState(() => images.remove(image));
                                        if (owned.remove(image)) {
                                          widget.controller.discardImage(image);
                                        }
                                      },
                              ),
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
                if (images.length < 4)
                  TextButton.icon(
                    onPressed: saving || importing ? null : _image,
                    icon: const Icon(Icons.add_photo_alternate_outlined),
                    label: Text(importing ? '正在处理图片' : '添加照片'),
                  ),
                const Text(
                  '保存的文字会进入记忆；照片留在本机，关联到这段回忆。',
                  style: TextStyle(color: XinYuColors.muted, fontSize: 12),
                ),
                if (error != null)
                  Text(
                    error!,
                    style: const TextStyle(color: Color(0xffa25148)),
                  ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: saving || importing ? null : () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(
          key: const Key('save-moment'),
          onPressed: saving || importing ? null : _save,
          child: Text(saving ? '正在保存' : '保存回忆'),
        ),
      ],
    ),
  );
}

class _CorrectionDialog extends StatefulWidget {
  const _CorrectionDialog(this.content);
  final String content;
  @override
  State<_CorrectionDialog> createState() => _CorrectionDialogState();
}

class _CorrectionDialogState extends State<_CorrectionDialog> {
  late final field = TextEditingController(text: widget.content);
  @override
  void dispose() {
    field.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('更正记忆'),
    content: TextField(
      controller: field,
      autofocus: true,
      maxLength: 2000,
      minLines: 3,
      maxLines: 8,
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('取消'),
      ),
      FilledButton(
        onPressed: () {
          if (field.text.trim().isNotEmpty) {
            Navigator.pop(context, field.text.trim());
          }
        },
        child: const Text('保存'),
      ),
    ],
  );
}

class JournalEventEditor extends StatefulWidget {
  const JournalEventEditor({super.key, required this.controller, this.event});
  final CompanionController controller;
  final Map<String, dynamic>? event;
  @override
  State<JournalEventEditor> createState() => _JournalEventEditorState();
}

class _JournalEventEditorState extends State<JournalEventEditor> {
  final title = TextEditingController(), note = TextEditingController();
  final form = GlobalKey<FormState>();
  final request = journalRequest();
  late final String conversation =
      widget.event?['conversation_id'] as String? ?? widget.controller.active!;
  late final String zone =
      widget.event?['timezone'] as String? ??
      widget.controller.settings['calendar_timezone'] as String? ??
      'Asia/Shanghai';
  DateTime day = DateTime.now().add(const Duration(days: 1));
  TimeOfDay at = const TimeOfDay(hour: 9, minute: 0);
  String kind = 'appointment', mode = 'reminder';
  bool yearly = false, saving = false;
  String? error;
  @override
  void initState() {
    super.initState();
    final e = widget.event;
    if (e != null) {
      title.text = e['title'] as String;
      note.text = e['note'] as String? ?? '';
      day = DateTime.tryParse(e['event_date'] as String? ?? '') ?? day;
      final parts = (e['at'] as String? ?? '09:00').split(':');
      at = TimeOfDay(hour: int.parse(parts[0]), minute: int.parse(parts[1]));
      kind = e['kind'] as String;
      mode = e['mode'] as String;
      yearly = e['yearly'] == true;
    }
  }

  @override
  void dispose() {
    title.dispose();
    note.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!form.currentState!.validate()) return;
    setState(() {
      saving = true;
      error = null;
    });
    try {
      await widget.controller.localConnection!.saveJournalEvent({
        'request_id': request,
        'conversation_id': conversation,
        'title': title.text.trim(),
        'note': note.text.trim(),
        'kind': kind,
        'event_date': journalDate(day),
        'at':
            '${at.hour.toString().padLeft(2, '0')}:${at.minute.toString().padLeft(2, '0')}',
        'yearly': yearly,
        'mode': mode,
        'timezone': zone,
      }, id: widget.event?['id'] as String?);
      if (mode != 'none') {
        await widget.controller.notifications.call('requestPermission');
      }
      await widget.controller.refreshUpdates();
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '日期提醒未保存'),
        );
      }
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !saving,
    child: AlertDialog(
      title: Text(widget.event == null ? '记下一个重要日子' : '编辑日期与约定'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Form(
            key: form,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final entry in const {
                      'appointment': '约定',
                      'anniversary': '纪念日',
                    }.entries)
                      ChoiceChip(
                        label: Text(entry.value),
                        selected: kind == entry.key,
                        onSelected: saving
                            ? null
                            : (_) => setState(() {
                                kind = entry.key;
                                if (kind == 'anniversary') yearly = true;
                              }),
                      ),
                  ],
                ),
                const SizedBox(height: 12),
                TextFormField(
                  key: const Key('event-title'),
                  controller: title,
                  maxLength: 80,
                  decoration: const InputDecoration(labelText: '这是什么日子'),
                  validator: (v) =>
                      v == null || v.trim().isEmpty ? '请填写标题' : null,
                ),
                Wrap(
                  spacing: 12,
                  children: [
                    TextButton.icon(
                      icon: const Icon(Icons.calendar_month),
                      label: Text(journalDate(day)),
                      onPressed: saving
                          ? null
                          : () async {
                              final chosen = await showDatePicker(
                                context: context,
                                initialDate: day,
                                firstDate: DateTime(1900),
                                lastDate: DateTime(2200),
                                helpText: '选择日期',
                                cancelText: '取消',
                                confirmText: '确定',
                              );
                              if (chosen != null && mounted) {
                                setState(() => day = chosen);
                              }
                            },
                    ),
                    TextButton.icon(
                      icon: const Icon(Icons.schedule),
                      label: Text(
                        '${at.hour.toString().padLeft(2, '0')}:${at.minute.toString().padLeft(2, '0')}',
                      ),
                      onPressed: saving
                          ? null
                          : () async {
                              final chosen = await showTimePicker(
                                context: context,
                                initialTime: at,
                                helpText: '提醒时间',
                                cancelText: '取消',
                                confirmText: '确定',
                              );
                              if (chosen != null && mounted) {
                                setState(() => at = chosen);
                              }
                            },
                    ),
                  ],
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('每年记得这一天'),
                  value: yearly,
                  onChanged: saving ? null : (v) => setState(() => yearly = v),
                ),
                TextFormField(
                  controller: note,
                  maxLength: 500,
                  minLines: 1,
                  maxLines: 3,
                  decoration: const InputDecoration(labelText: '备注（可选）'),
                ),
                RoundedChoiceField<String>(
                  initialValue: mode,
                  label: '到时间后',
                  choices: const {
                    'none': '仅记录',
                    'reminder': '日期提醒 · 不调用 AI',
                    'checkin': '让 TA 问候 · 使用模型额度',
                  },
                  onChanged: saving ? null : (v) => setState(() => mode = v!),
                ),
                const SizedBox(height: 12),
                Text(
                  '使用公历，时区 $zone。2 月 29 日在非闰年按 2 月 28 日提醒。',
                  style: const TextStyle(
                    color: XinYuColors.muted,
                    fontSize: 12,
                  ),
                ),
                if (mode != 'none')
                  const Padding(
                    padding: EdgeInsets.only(top: 8),
                    child: Text(
                      '遵守免打扰；安卓省电和后台调度可能推迟提醒。',
                      style: TextStyle(color: XinYuColors.muted, fontSize: 12),
                    ),
                  ),
                if (mode == 'checkin')
                  const Padding(
                    padding: EdgeInsets.only(top: 8),
                    child: Text(
                      '需在设置 → 消息开启主动联系，并配置在线模型。问候也遵守频率和未回复限制。',
                      style: TextStyle(color: XinYuColors.muted, fontSize: 12),
                    ),
                  ),
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      error!,
                      style: const TextStyle(color: Color(0xffa25148)),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: saving ? null : () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(
          key: const Key('save-event'),
          onPressed: saving ? null : _save,
          child: Text(saving ? '正在保存' : '保存约定'),
        ),
      ],
    ),
  );
}

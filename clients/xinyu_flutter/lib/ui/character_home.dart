import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import 'bookmarks.dart';
import 'glass.dart';
import 'local_image.dart';
import 'memory_sheet.dart';
import 'chat_search.dart';

Future<void> showCharacterHome(
  BuildContext context,
  CompanionController controller, {
  bool isUser = false,
}) => showDialog<void>(
  context: context,
  barrierColor: const Color(0x3033403c),
  builder: (_) => _CharacterHome(controller: controller, initialUser: isUser),
);

class _CharacterHome extends StatefulWidget {
  const _CharacterHome({required this.controller, required this.initialUser});
  final CompanionController controller;
  final bool initialUser;
  @override
  State<_CharacterHome> createState() => _CharacterHomeState();
}

class _CharacterHomeState extends State<_CharacterHome> {
  late bool isUser = widget.initialUser;
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller,
    builder: (context, _) {
      final c = widget.controller;
      final name = isUser
          ? (c.userName.isEmpty ? '你' : c.userName)
          : c.companionName;
      final bio =
          c.settings[isUser ? 'user_persona' : 'persona_notes'] as String? ??
          '';
      final style = c.settings['style'] == 'custom'
          ? c.settings['custom_style'] as String? ?? ''
          : bio.trim().isNotEmpty
          ? '以你填写的人物资料为准'
          : {
                  'gentle': '温柔细腻',
                  'playful': '明快俏皮',
                  'steady': '沉稳坦诚',
                }[c.settings['style']] ??
                '';
      return Dialog(
        backgroundColor: Colors.transparent,
        insetPadding: const EdgeInsets.all(14),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 660, maxHeight: 790),
          child: GlassSurface(
            tint: const Color(0xeff4faf5),
            padding: const EdgeInsets.all(20),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  children: [
                    const Expanded(
                      child: Text(
                        '角色主页',
                        style: TextStyle(
                          fontSize: 23,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: '关闭角色主页',
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.close),
                    ),
                  ],
                ),
                Flexible(
                  child: SingleChildScrollView(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Wrap(
                          spacing: 8,
                          children: [
                            ChoiceChip(
                              label: const Text('TA 的主页'),
                              selected: !isUser,
                              onSelected: (_) => setState(() => isUser = false),
                            ),
                            ChoiceChip(
                              label: const Text('我的主页'),
                              selected: isUser,
                              onSelected: (_) => setState(() => isUser = true),
                            ),
                          ],
                        ),
                        const SizedBox(height: 22),
                        Center(
                          child: ProfileAvatar(
                            controller: c,
                            isUser: isUser,
                            size: 90,
                          ),
                        ),
                        const SizedBox(height: 12),
                        Text(
                          name,
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            fontSize: 25,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        const SizedBox(height: 7),
                        Text(
                          isUser ? '我想成为的自己，由我定义。' : '相处的模样，由你的设定决定。',
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            fontSize: 12,
                            color: XinYuColors.muted,
                          ),
                        ),
                        const SizedBox(height: 18),
                        _section(
                          '人物资料',
                          bio.isEmpty ? '还没有填写，点编辑资料来介绍自己。' : bio,
                        ),
                        if (!isUser) ...[
                          const SizedBox(height: 12),
                          _section('性格与说话方式', style.isEmpty ? '尚未填写' : style),
                        ],
                        const SizedBox(height: 16),
                        FilledButton.tonalIcon(
                          key: const Key('edit-character'),
                          onPressed: c.busy
                              ? null
                              : () => showDialog<void>(
                                  context: context,
                                  builder: (_) => _ProfileEditor(
                                    controller: c,
                                    isUser: isUser,
                                  ),
                                ),
                          icon: const Icon(Icons.edit_outlined),
                          label: const Text('编辑资料与头像'),
                        ),
                        const SizedBox(height: 14),
                        Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          alignment: WrapAlignment.center,
                          children: [
                            if (c.hasExperience)
                              OutlinedButton.icon(
                                key: const Key('open-bookmarks'),
                                onPressed: () => showBookmarks(context, c),
                                icon: const Icon(Icons.bookmarks_outlined),
                                label: const Text('收藏夹'),
                              ),
                            OutlinedButton.icon(
                              onPressed: c.busy || !c.connected
                                  ? null
                                  : () => showMemories(context, c),
                              icon: const Icon(Icons.book_outlined),
                              label: const Text('我们的手账'),
                            ),
                            if (c.hasChatFeatures)
                              OutlinedButton.icon(
                                onPressed: () => showChatSearch(context, c),
                                icon: const Icon(Icons.search),
                                label: const Text('聊天记录'),
                              ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    },
  );
  Widget _section(String title, String text) => GlassSurface(
    radius: XinYuShapes.cardRadius,
    padding: const EdgeInsets.all(16),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        SelectableText(text, style: const TextStyle(height: 1.7, fontSize: 13)),
      ],
    ),
  );
}

class _ProfileEditor extends StatefulWidget {
  const _ProfileEditor({required this.controller, required this.isUser});
  final CompanionController controller;
  final bool isUser;
  @override
  State<_ProfileEditor> createState() => _ProfileEditorState();
}

class _ProfileEditorState extends State<_ProfileEditor> {
  final form = GlobalKey<FormState>();
  late final name = TextEditingController(
    text: widget.isUser
        ? widget.controller.userName
        : widget.controller.companionName,
  );
  late final bio = TextEditingController(
    text:
        widget.controller.settings[widget.isUser
                ? 'user_persona'
                : 'persona_notes']
            as String? ??
        '',
  );
  late final style = TextEditingController(
    text: widget.controller.settings['custom_style'] as String? ?? '',
  );
  late String selectedStyle =
      widget.controller.settings['style'] as String? ?? 'gentle';
  String get avatarField => widget.isUser ? 'user_avatar' : 'companion_avatar';
  late String? avatar = widget.controller.settings[avatarField] as String?;
  final imported = <String>[];
  bool working = false;
  String? error;
  Future<void> pick() async {
    setState(() {
      working = true;
      error = null;
    });
    try {
      final id = await widget.controller.importImage(avatarField);
      if (id != null) {
        imported.add(id);
        if (mounted) setState(() => avatar = id);
      }
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '头像未能导入'),
        );
      }
    } finally {
      if (mounted) setState(() => working = false);
    }
  }

  Future<void> save() async {
    if (!form.currentState!.validate()) return;
    setState(() {
      working = true;
      error = null;
    });
    try {
      final values = widget.controller.settingsCopy();
      values[widget.isUser ? 'user_name' : 'companion_name'] = name.text.trim();
      values[widget.isUser ? 'user_persona' : 'persona_notes'] = bio.text
          .trim();
      values[avatarField] = avatar;
      if (!widget.isUser) {
        values['style'] = selectedStyle;
        values['custom_style'] = style.text.trim();
      }
      await widget.controller.save(values);
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '角色资料未保存'),
        );
      }
    } finally {
      if (mounted) setState(() => working = false);
    }
  }

  @override
  void dispose() {
    for (final id in imported) {
      if (id != widget.controller.settings[avatarField]) {
        widget.controller.discardImage(id);
      }
    }
    name.dispose();
    bio.dispose();
    style.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !working,
    child: Dialog(
      backgroundColor: Colors.transparent,
      insetPadding: const EdgeInsets.all(16),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 590, maxHeight: 720),
        child: GlassSurface(
          tint: const Color(0xf5f4faf5),
          padding: const EdgeInsets.all(20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      widget.isUser ? '编辑我的资料' : '编辑 TA 的资料',
                      style: const TextStyle(fontSize: 20),
                    ),
                  ),
                  IconButton(
                    tooltip: '取消编辑资料',
                    onPressed: working ? null : () => Navigator.pop(context),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
              Flexible(
                child: SingleChildScrollView(
                  child: Form(
                    key: form,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        if (avatar != null)
                          Center(
                            child: ClipRRect(
                              borderRadius: BorderRadius.circular(26),
                              child: LocalImage(
                                controller: widget.controller,
                                id: avatar!,
                                width: 90,
                                height: 90,
                              ),
                            ),
                          ),
                        Wrap(
                          alignment: WrapAlignment.center,
                          children: [
                            TextButton.icon(
                              onPressed: working ? null : pick,
                              icon: const Icon(Icons.photo_library_outlined),
                              label: const Text('更换头像'),
                            ),
                            if (avatar != null)
                              TextButton(
                                onPressed: working
                                    ? null
                                    : () => setState(() => avatar = null),
                                child: const Text('恢复默认'),
                              ),
                          ],
                        ),
                        TextFormField(
                          key: const Key('profile-name'),
                          controller: name,
                          maxLength: 24,
                          decoration: const InputDecoration(labelText: '称呼'),
                          validator: (v) =>
                              !widget.isUser && (v?.trim().isEmpty ?? true)
                              ? '请填写称呼'
                              : null,
                        ),
                        const SizedBox(height: 12),
                        TextFormField(
                          key: const Key('profile-bio'),
                          controller: bio,
                          minLines: 3,
                          maxLines: 6,
                          maxLength: widget.isUser ? 6000 : 1000,
                          decoration: const InputDecoration(
                            labelText: '人物资料',
                            hintText: '身份、背景、关系与希望记住的设定',
                          ),
                        ),
                        if (!widget.isUser) ...[
                          const SizedBox(height: 12),
                          RoundedChoiceField<String>(
                            initialValue: selectedStyle,
                            label: '相处风格',
                            choices: const {
                              'gentle': '温柔细腻',
                              'playful': '明快俏皮',
                              'steady': '沉稳坦诚',
                              'custom': '自定义角色',
                            },
                            onChanged: working
                                ? null
                                : (v) => setState(() => selectedStyle = v!),
                          ),
                          if (selectedStyle == 'custom')
                            Padding(
                              padding: const EdgeInsets.only(top: 12),
                              child: TextFormField(
                                key: const Key('profile-style'),
                                controller: style,
                                minLines: 4,
                                maxLines: 9,
                                maxLength: 6000,
                                decoration: const InputDecoration(
                                  labelText: '性格、说话方式与对话示例',
                                  helperText: '自定义角色不混入应用预设性格。',
                                ),
                                validator: (v) => v?.trim().isNotEmpty == true
                                    ? null
                                    : '请填写自定义设定',
                              ),
                            ),
                        ],
                        if (error != null)
                          Text(
                            error!,
                            style: const TextStyle(color: Colors.brown),
                          ),
                      ],
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              FilledButton(
                key: const Key('save-character'),
                onPressed: working ? null : save,
                child: Text(working ? '正在保存…' : '保存资料'),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

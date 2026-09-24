import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import '../data/models.dart';
import 'glass.dart';

Future<void> showCompanionSettings(
  BuildContext context,
  CompanionController controller,
) => showDialog<void>(
  context: context,
  barrierColor: const Color(0x2433403c),
  builder: (_) => SettingsSheet(controller: controller),
);

class SettingsSheet extends StatefulWidget {
  const SettingsSheet({super.key, required this.controller});
  final CompanionController controller;
  @override
  State<SettingsSheet> createState() => _SettingsSheetState();
}

class _SettingsSheetState extends State<SettingsSheet> {
  final _form = GlobalKey<FormState>();
  late Map<String, dynamic> values;
  late final TextEditingController companion, user, notes, address;
  final apiKey = TextEditingController();
  bool working = false;
  String? notice;
  int tab = 0;
  @override
  void initState() {
    super.initState();
    values = widget.controller.settingsCopy();
    companion = TextEditingController(text: widget.controller.companionName);
    user = TextEditingController(text: widget.controller.userName);
    notes = TextEditingController(
      text: values['persona_notes'] as String? ?? '',
    );
    address = TextEditingController(text: widget.controller.endpoint);
  }

  @override
  void dispose() {
    for (final c in [companion, user, notes, address, apiKey]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _action(
    Future<void> Function() action, {
    bool close = false,
  }) async {
    if (working) return;
    setState(() {
      working = true;
      notice = null;
    });
    try {
      await action();
      if (!mounted) return;
      if (close) {
        Navigator.pop(context);
        return;
      }
      setState(() {
        values = widget.controller.settingsCopy();
        companion.text = widget.controller.companionName;
        user.text = widget.controller.userName;
        notes.text = values['persona_notes'] as String? ?? '';
        notice = widget.controller.isDemo
            ? '已切换到演示空间；内容仅保留在本次运行。'
            : '已连接本地服务，请核对保存与模型选项。';
      });
    } catch (e) {
      if (mounted) {
        setState(
          () =>
              notice = e is CompanionException ? e.message : '操作未完成，请检查服务后重试。',
        );
      }
    } finally {
      if (mounted) setState(() => working = false);
    }
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    values['companion_name'] = companion.text.trim();
    values['user_name'] = user.text.trim();
    values['persona_notes'] = notes.text.trim();
    await _action(
      () => widget.controller.save(values, apiKey: apiKey.text),
      close: true,
    );
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    return Dialog(
      backgroundColor: Colors.transparent,
      elevation: 0,
      insetPadding: EdgeInsets.symmetric(
        horizontal: size.width < 600 ? 12 : 36,
        vertical: 20,
      ),
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: 570,
          maxHeight: size.height * .86,
        ),
        child: BackdropGroup(
          child: GlassSurface(
            key: const Key('settings-glass'),
            blur: 28,
            tint: const Color(0xb8faf9f5),
            radius: 30,
            padding: const EdgeInsets.all(22),
            child: Form(
              key: _form,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    children: [
                      const Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '让这里，更像我们',
                              style: TextStyle(
                                fontSize: 22,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            SizedBox(height: 5),
                            Text(
                              '相处的节奏，由你来定。',
                              style: TextStyle(
                                color: XinYuColors.muted,
                                fontSize: 13,
                              ),
                            ),
                          ],
                        ),
                      ),
                      IconButton(
                        tooltip: '关闭设置',
                        onPressed: working
                            ? null
                            : () => Navigator.pop(context),
                        icon: const Icon(Icons.close_rounded),
                      ),
                    ],
                  ),
                  const SizedBox(height: 22),
                  SizedBox(
                    width: double.infinity,
                    child: SegmentedButton<int>(
                      segments: const [
                        ButtonSegment(
                          value: 0,
                          label: Text('相处设定'),
                          icon: Icon(Icons.favorite_border_rounded, size: 17),
                        ),
                        ButtonSegment(
                          value: 1,
                          label: Text('连接与数据'),
                          icon: Icon(Icons.link_rounded, size: 18),
                        ),
                      ],
                      selected: {tab},
                      onSelectionChanged: working
                          ? null
                          : (v) => setState(() => tab = v.first),
                      showSelectedIcon: false,
                    ),
                  ),
                  const SizedBox(height: 20),
                  Flexible(
                    child: SingleChildScrollView(
                      key: const Key('settings-scroll'),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          if (tab == 0) ..._persona(),
                          if (tab == 1) ..._connection(),
                          if (notice != null)
                            Padding(
                              padding: const EdgeInsets.only(top: 16),
                              child: Semantics(
                                liveRegion: true,
                                child: Text(
                                  notice!,
                                  style: const TextStyle(
                                    color: Color(0xff865c43),
                                    height: 1.6,
                                  ),
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 20),
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          widget.controller.isDemo
                              ? '演示设置仅在本次运行生效'
                              : '保存到当前连接的本地服务',
                          style: const TextStyle(
                            fontSize: 11,
                            color: XinYuColors.muted,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      FilledButton(
                        onPressed: working || widget.controller.busy
                            ? null
                            : _save,
                        child: Text(working ? '处理中…' : '保存设置'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  List<Widget> _persona() => [
    TextFormField(
      controller: companion,
      decoration: const InputDecoration(labelText: '怎么称呼 TA'),
      maxLength: 24,
      validator: (v) => v == null || v.trim().isEmpty ? '请填写一个称呼' : null,
    ),
    const SizedBox(height: 12),
    TextFormField(
      controller: user,
      decoration: const InputDecoration(labelText: '希望 TA 怎么称呼你'),
      maxLength: 24,
    ),
    const SizedBox(height: 12),
    DropdownButtonFormField<String>(
      initialValue: values['style'] as String? ?? 'gentle',
      decoration: const InputDecoration(labelText: '相处风格'),
      items: const [
        DropdownMenuItem(value: 'gentle', child: Text('温柔细腻')),
        DropdownMenuItem(value: 'playful', child: Text('明快俏皮')),
        DropdownMenuItem(value: 'steady', child: Text('沉稳坦诚')),
      ],
      onChanged: (v) => values['style'] = v,
    ),
    const SizedBox(height: 18),
    TextFormField(
      controller: notes,
      decoration: const InputDecoration(
        labelText: '想让 TA 了解的相处偏好',
        alignLabelWithHint: true,
      ),
      maxLines: 3,
      maxLength: 1000,
    ),
    SwitchListTile.adaptive(
      contentPadding: EdgeInsets.zero,
      title: const Text('允许浪漫互动', style: TextStyle(fontSize: 14)),
      subtitle: const Text('关闭后以普通陪伴关系相处。', style: TextStyle(fontSize: 12)),
      value: values['romance_consent'] == true,
      onChanged: (v) => setState(() => values['romance_consent'] = v),
    ),
  ];

  List<Widget> _connection() => [
    Text(
      widget.controller.isDemo ? '当前：界面演示' : '当前：本地服务',
      style: const TextStyle(fontWeight: FontWeight.w600),
    ),
    const SizedBox(height: 8),
    const Text(
      '演示不调用模型，也不保存到真实记忆库。连接服务后，可继续使用现有记忆引擎。',
      style: TextStyle(color: XinYuColors.muted, fontSize: 13, height: 1.6),
    ),
    const SizedBox(height: 18),
    TextFormField(
      controller: address,
      autocorrect: false,
      decoration: const InputDecoration(labelText: '本地服务地址'),
      keyboardType: TextInputType.url,
    ),
    const SizedBox(height: 12),
    Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        FilledButton.tonalIcon(
          onPressed: working || widget.controller.busy
              ? null
              : () => _action(() => widget.controller.connect(address.text)),
          icon: const Icon(Icons.link_rounded),
          label: const Text('连接服务'),
        ),
        TextButton(
          onPressed: working || widget.controller.busy
              ? null
              : () => _action(widget.controller.useDemo),
          child: const Text('切回演示'),
        ),
      ],
    ),
    const SizedBox(height: 18),
    if (!widget.controller.isDemo) ...[
      DropdownButtonFormField<String>(
        key: ValueKey('mode-${values['model_mode']}'),
        initialValue: values['model_mode'] as String? ?? 'offline',
        decoration: const InputDecoration(labelText: '回复方式'),
        items: const [
          DropdownMenuItem(value: 'offline', child: Text('离线规则回复（不调用模型）')),
          DropdownMenuItem(value: 'api', child: Text('DeepSeek 模型')),
        ],
        onChanged: (v) => setState(() => values['model_mode'] = v),
      ),
      if (values['model_mode'] == 'api') ...[
        const SizedBox(height: 16),
        TextFormField(
          controller: apiKey,
          obscureText: true,
          autocorrect: false,
          enableSuggestions: false,
          decoration: const InputDecoration(
            labelText: 'API Key',
            helperText: '留空保留已有凭据；客户端不落盘保存。',
          ),
        ),
      ],
      const SizedBox(height: 12),
      CheckboxListTile(
        contentPadding: EdgeInsets.zero,
        controlAffinity: ListTileControlAffinity.leading,
        title: const Text('允许服务保存对话与记忆', style: TextStyle(fontSize: 14)),
        subtitle: const Text('数据存放在运行服务的设备上。', style: TextStyle(fontSize: 12)),
        value: values['storage_consent'] == true,
        onChanged: (v) =>
            setState(() => values['storage_consent'] = v ?? false),
      ),
      CheckboxListTile(
        contentPadding: EdgeInsets.zero,
        controlAffinity: ListTileControlAffinity.leading,
        title: const Text('允许所选回复方式处理消息', style: TextStyle(fontSize: 14)),
        subtitle: const Text(
          '选择模型时会发送必要上下文；离线方式不会联网。',
          style: TextStyle(fontSize: 12),
        ),
        value: values['model_consent'] == true,
        onChanged: (v) => setState(() => values['model_consent'] = v ?? false),
      ),
    ],
    const SizedBox(height: 6),
    const Text(
      'Android 可通过 USB 端口转发连接服务。iPhone 真机当前仅支持界面演示；手机端记忆引擎和跨设备同步尚未移植。',
      style: TextStyle(fontSize: 12, height: 1.6, color: XinYuColors.muted),
    ),
  ];
}

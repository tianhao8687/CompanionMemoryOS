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
  final _scroll = ScrollController();
  late Map<String, dynamic> values;
  late final TextEditingController companion,
      user,
      notes,
      address,
      customStyle,
      model,
      modelUrl;
  final apiKey = TextEditingController();
  bool working = false;
  bool rememberKey = false, clearKey = false;
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
    customStyle = TextEditingController(
      text: values['custom_style'] as String? ?? '',
    );
    model = TextEditingController(
      text: values['deepseek']?['model'] as String? ?? 'deepseek-flash',
    );
    modelUrl = TextEditingController(
      text:
          values['deepseek']?['base_url'] as String? ??
          'https://api.deepseek.com',
    );
    rememberKey = widget.controller.capabilities['key_persisted'] == true;
  }

  @override
  void dispose() {
    _scroll.dispose();
    for (final c in [
      companion,
      user,
      notes,
      address,
      apiKey,
      customStyle,
      model,
      modelUrl,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  void _selectTab(int value) {
    setState(() => tab = value);
    if (_scroll.hasClients) _scroll.jumpTo(0);
  }

  Future<void> _action(
    Future<void> Function() action, {
    bool close = false,
    String? success,
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
        customStyle.text = values['custom_style'] as String? ?? '';
        model.text =
            values['deepseek']?['model'] as String? ?? 'deepseek-flash';
        modelUrl.text =
            values['deepseek']?['base_url'] as String? ??
            'https://api.deepseek.com';
        rememberKey = widget.controller.capabilities['key_persisted'] == true;
        apiKey.clear();
        clearKey = false;
        notice =
            success ??
            (widget.controller.isDemo
                ? '已切换到演示空间；内容仅保留在本次运行。'
                : '本机数据已载入，请核对保存与模型选项。');
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
    values['custom_style'] = customStyle.text.trim();
    if (!widget.controller.isDemo) {
      final config = Map<String, dynamic>.from(
        values['deepseek'] as Map? ?? {},
      );
      config['model'] = model.text.trim();
      config['base_url'] = modelUrl.text.trim();
      values['deepseek'] = config;
    }
    await _action(
      () => widget.controller.save(
        values,
        apiKey: apiKey.text,
        rememberKey: rememberKey,
        clearKey: clearKey,
      ),
      close: true,
    );
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final compact = size.width < 600;
    return Dialog(
      backgroundColor: Colors.transparent,
      elevation: 0,
      insetPadding: EdgeInsets.symmetric(
        horizontal: compact ? 12 : 36,
        vertical: 20,
      ),
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: 620,
          maxHeight: size.height * .88,
        ),
        child: BackdropGroup(
          child: GlassSurface(
            key: const Key('settings-glass'),
            blur: 30,
            tint: const Color(0x88f5fcf8),
            radius: 32,
            padding: EdgeInsets.all(compact ? 16 : 26),
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
                            SizedBox(height: 6),
                            Text(
                              '一点偏爱，刚好合拍。',
                              style: TextStyle(
                                color: XinYuColors.muted,
                                fontSize: 12,
                              ),
                            ),
                          ],
                        ),
                      ),
                      IconButton.filledTonal(
                        tooltip: '关闭设置',
                        style: IconButton.styleFrom(
                          backgroundColor: const Color(0x65ffffff),
                        ),
                        onPressed: working
                            ? null
                            : () => Navigator.pop(context),
                        icon: const Icon(Icons.close_rounded, size: 20),
                      ),
                    ],
                  ),
                  const SizedBox(height: 20),
                  Container(
                    padding: const EdgeInsets.all(4),
                    decoration: BoxDecoration(
                      color: const Color(0x28728c80),
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(color: const Color(0x90ffffff)),
                    ),
                    child: Row(
                      children: [
                        for (final item in [
                          (0, '相处设定', Icons.favorite_border_rounded),
                          (2, '外观', Icons.text_fields_rounded),
                          (1, '连接与数据', Icons.tune_rounded),
                        ])
                          Expanded(
                            child: _SettingsTab(
                              label: item.$2,
                              icon: item.$3,
                              selected: tab == item.$1,
                              showIcon: !compact,
                              onTap: working ? null : () => _selectTab(item.$1),
                            ),
                          ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 18),
                  Flexible(
                    child: SingleChildScrollView(
                      key: const Key('settings-scroll'),
                      controller: _scroll,
                      child: AbsorbPointer(
                        absorbing: working,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (tab == 0) ..._persona(),
                            if (tab == 1) ..._connection(),
                            if (tab == 2) ..._appearance(),
                            if (notice != null)
                              Padding(
                                padding: const EdgeInsets.only(top: 14),
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
                  ),
                  const SizedBox(height: 16),
                  const Divider(height: 1, color: Color(0x90ffffff)),
                  const SizedBox(height: 14),
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          widget.controller.isDemo
                              ? '演示设置仅在本次运行生效'
                              : '只保存在这台设备',
                          style: const TextStyle(
                            fontSize: 11,
                            color: XinYuColors.muted,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      FilledButton.icon(
                        onPressed: working || widget.controller.busy
                            ? null
                            : _save,
                        icon: const Icon(Icons.check_rounded, size: 18),
                        label: Text(working ? '处理中…' : '保存设置'),
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

  List<Widget> _appearance() => [
    _SettingsGroup(
      title: '字号',
      icon: Icons.text_fields_rounded,
      subtitle: '选择舒服的阅读大小，也会保留系统的无障碍字号设置。',
      children: [
        for (final option in [
          ('standard', '标准', '轻盈、留白更多'),
          ('large', '大号', '更舒适的日常阅读'),
          ('extra_large', '特大', '文字更醒目、更好辨认'),
        ]) ...[
          _ChoiceCard(
            title: option.$2,
            description: option.$3,
            icon: Icons.format_size_rounded,
            horizontal: true,
            selected: (values['font_size'] ?? 'standard') == option.$1,
            onTap: () => setState(() => values['font_size'] = option.$1),
          ),
          const SizedBox(height: 10),
        ],
        const SizedBox(height: 6),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            color: const Color(0x65ffffff),
            borderRadius: BorderRadius.circular(17),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                '阅读预览',
                style: TextStyle(fontSize: 11, color: XinYuColors.muted),
              ),
              const SizedBox(height: 10),
              Text(
                '今天，也想听你慢慢说。',
                style: TextStyle(
                  fontSize: switch (values['font_size']) {
                    'large' => 17.92,
                    'extra_large' => 19.84,
                    _ => 16,
                  },
                  height: 1.7,
                ),
              ),
            ],
          ),
        ),
      ],
    ),
  ];

  List<Widget> _persona() => [
    _SettingsGroup(
      title: '彼此的称呼',
      icon: Icons.alternate_email_rounded,
      children: [
        TextFormField(
          controller: companion,
          decoration: const InputDecoration(
            labelText: '怎么称呼 TA',
            counterText: '',
          ),
          maxLength: 24,
          validator: (v) => v == null || v.trim().isEmpty ? '请填写一个称呼' : null,
        ),
        const SizedBox(height: 14),
        TextFormField(
          controller: user,
          decoration: const InputDecoration(
            labelText: '希望 TA 怎么称呼你',
            hintText: '留空也没关系',
            counterText: '',
          ),
          maxLength: 24,
        ),
      ],
    ),
    const SizedBox(height: 14),
    _SettingsGroup(
      title: '相处风格',
      subtitle: '选一种感觉，也可以写下自己的期待。',
      icon: Icons.auto_awesome_outlined,
      children: [
        LayoutBuilder(
          builder: (context, constraints) => Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              for (final style in [
                ('gentle', '温柔细腻', '柔和、细心，有点俏皮', Icons.spa_outlined),
                ('playful', '明快俏皮', '轻松接话，也会逗你', Icons.wb_sunny_outlined),
                ('steady', '沉稳坦诚', '有自己的步调与主见', Icons.coffee_outlined),
                ('custom', '自定义', '由你写下相处的模样', Icons.edit_note_rounded),
              ])
                SizedBox(
                  width: (constraints.maxWidth - 10) / 2,
                  child: _ChoiceCard(
                    title: style.$2,
                    description: style.$3,
                    icon: style.$4,
                    selected: (values['style'] ?? 'gentle') == style.$1,
                    onTap: () => setState(() => values['style'] = style.$1),
                  ),
                ),
            ],
          ),
        ),
        if (values['style'] == 'custom') ...[
          const SizedBox(height: 16),
          TextFormField(
            controller: customStyle,
            maxLines: 5,
            maxLength: 6000,
            decoration: const InputDecoration(
              labelText: '自定义相处风格',
              alignLabelWithHint: true,
              hintText: '比如：坦诚、有主见，开心时可以一起胡闹。',
            ),
            validator: (v) =>
                v == null || v.trim().isEmpty ? '请描述希望的相处风格' : null,
          ),
        ],
      ],
    ),
    const SizedBox(height: 14),
    _SettingsGroup(
      title: '相处偏好',
      icon: Icons.favorite_outline_rounded,
      children: [
        TextFormField(
          controller: notes,
          decoration: const InputDecoration(
            labelText: '想让 TA 了解的相处偏好',
            alignLabelWithHint: true,
            hintText: '喜欢的称呼、聊天习惯，或希望被尊重的边界。',
          ),
          maxLines: 3,
          maxLength: 1000,
        ),
        _SettingsToggle(
          title: '允许浪漫互动',
          subtitle: '关闭后以普通陪伴关系相处。',
          value: values['romance_consent'] == true,
          onChanged: (v) => setState(() => values['romance_consent'] = v),
        ),
      ],
    ),
  ];

  Future<void> _restore() async {
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('从备份恢复'),
        content: const Text('恢复会替换当前设备的聊天、记忆和设置。当前数据会先留一份恢复副本，模型 Key 不在备份中。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('选择备份'),
          ),
        ],
      ),
    );
    if (accepted != true || !mounted) return;
    bool? restored;
    await _action(() async {
      restored = await widget.controller.restoreBackup();
    });
    if (mounted && restored != null) {
      setState(() => notice = restored! ? '备份已恢复。' : '已取消，数据未更改。');
    }
  }

  Future<void> _backup() async {
    bool? saved;
    await _action(() async {
      saved = await widget.controller.backup();
    });
    if (mounted && saved != null) {
      setState(() => notice = saved! ? '备份已保存到你选择的位置。' : '已取消导出。');
    }
  }

  List<Widget> _connection() => [
    _SettingsGroup(
      title: widget.controller.isDemo ? '当前：界面演示' : '当前：本机数据',
      icon: Icons.devices_rounded,
      subtitle: '聊天与记忆留在当前设备。电脑和手机各自独立。',
      children: [
        OutlinedButton.icon(
          onPressed: working || widget.controller.busy
              ? null
              : () => _action(widget.controller.useLocal),
          icon: const Icon(Icons.refresh_rounded, size: 18),
          label: Text(widget.controller.isDemo ? '打开本机数据' : '重新连接'),
        ),
        if (const bool.fromEnvironment('XINYU_DEVELOPMENT')) ...[
          const SizedBox(height: 12),
          TextFormField(
            controller: address,
            decoration: const InputDecoration(labelText: '开发服务地址'),
          ),
          TextButton(
            onPressed: working
                ? null
                : () => _action(() => widget.controller.connect(address.text)),
            child: const Text('连接开发服务'),
          ),
          TextButton(
            onPressed: working
                ? null
                : () => _action(widget.controller.useDemo),
            child: const Text('切换演示'),
          ),
        ],
      ],
    ),
    if (!widget.controller.isDemo) ...[
      const SizedBox(height: 14),
      _SettingsGroup(
        title: '回复方式',
        icon: Icons.chat_bubble_outline_rounded,
        children: [
          _ChoiceCard(
            title: '离线规则回复',
            description: '用于体验聊天流程，不运行大模型。',
            icon: Icons.offline_bolt_outlined,
            horizontal: true,
            selected: (values['model_mode'] ?? 'offline') == 'offline',
            onTap: () => setState(() => values['model_mode'] = 'offline'),
          ),
          const SizedBox(height: 10),
          _ChoiceCard(
            title: '联网调用模型',
            description: '使用自己的 API，消息会发送给模型服务商。',
            icon: Icons.cloud_outlined,
            horizontal: true,
            selected: values['model_mode'] == 'api',
            onTap: () => setState(() => values['model_mode'] = 'api'),
          ),
          if (values['model_mode'] == 'api') ...[
            const SizedBox(height: 20),
            TextFormField(
              controller: model,
              decoration: const InputDecoration(labelText: '模型名称'),
              validator: (v) =>
                  v == null || v.trim().isEmpty ? '请填写模型名称' : null,
            ),
            const SizedBox(height: 14),
            TextFormField(
              controller: modelUrl,
              autocorrect: false,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(labelText: '模型 API 地址'),
              validator: (v) {
                final uri = Uri.tryParse(v?.trim() ?? '');
                return uri != null &&
                        uri.scheme == 'https' &&
                        uri.host.isNotEmpty
                    ? null
                    : '请填写服务商的 HTTPS API 地址';
              },
            ),
            const SizedBox(height: 14),
            TextFormField(
              controller: apiKey,
              obscureText: true,
              autocorrect: false,
              enableSuggestions: false,
              decoration: InputDecoration(
                labelText: 'API Key',
                helperMaxLines: 2,
                helperText:
                    widget.controller.capabilities['key_configured'] == true
                    ? '已配置；留空保留现有 Key。'
                    : '请填写你自己的模型服务 Key。',
              ),
            ),
            const SizedBox(height: 8),
            if (widget
                    .controller
                    .capabilities['credential_persistence_supported'] ==
                true)
              _SettingsToggle(
                title: '在这台设备安全保存 Key',
                subtitle: '由系统安全存储，不写入聊天备份。',
                value: rememberKey,
                onChanged: (v) => setState(() => rememberKey = v),
              ),
            if (widget.controller.capabilities['key_configured'] == true)
              _SettingsToggle(
                title: '清除已保存的 Key',
                subtitle: '保存设置后生效。',
                value: clearKey,
                onChanged: (v) => setState(() => clearKey = v),
              ),
          ],
        ],
      ),
      const SizedBox(height: 14),
      _SettingsGroup(
        title: '消息与记忆',
        icon: Icons.shield_outlined,
        children: [
          _SettingsToggle(
            title: '允许保存对话与记忆',
            subtitle: '数据保存在当前设备。',
            value: values['storage_consent'] == true,
            onChanged: (v) => setState(() => values['storage_consent'] = v),
          ),
          const Divider(height: 18, color: Color(0x70ffffff)),
          _SettingsToggle(
            title: '允许所选回复方式处理消息',
            subtitle: '联网模型会处理必要上下文，并产生服务商 API 用量。',
            value: values['model_consent'] == true,
            onChanged: (v) => setState(() => values['model_consent'] = v),
          ),
        ],
      ),
      if (widget.controller.hasManagedStorage) ...[
        const SizedBox(height: 14),
        _SettingsGroup(
          title: '备份与恢复',
          icon: Icons.inventory_2_outlined,
          subtitle: '导出完整聊天与记忆。恢复支持本应用的备份，最多 64 MB。',
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                OutlinedButton.icon(
                  onPressed: working || widget.controller.busy ? null : _backup,
                  icon: const Icon(Icons.save_alt_rounded, size: 18),
                  label: const Text('导出备份'),
                ),
                OutlinedButton.icon(
                  onPressed: working || widget.controller.busy
                      ? null
                      : _restore,
                  icon: const Icon(Icons.restore_rounded, size: 18),
                  label: const Text('从备份恢复'),
                ),
              ],
            ),
          ],
        ),
      ],
    ],
  ];
}

class _SettingsTab extends StatelessWidget {
  const _SettingsTab({
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
    this.showIcon = true,
  });
  final String label;
  final IconData icon;
  final bool selected, showIcon;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) => Semantics(
    selected: selected,
    button: true,
    child: Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 13),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            gradient: selected
                ? const LinearGradient(
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                    colors: [Color(0xedffffff), Color(0x95e7f5ed)],
                  )
                : null,
            border: Border.all(
              color: selected ? const Color(0xe0ffffff) : Colors.transparent,
            ),
            boxShadow: selected
                ? const [
                    BoxShadow(
                      color: Color(0x14628271),
                      blurRadius: 10,
                      offset: Offset(0, 3),
                    ),
                  ]
                : null,
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              if (showIcon) ...[
                Icon(
                  icon,
                  size: 17,
                  color: selected ? XinYuColors.accent : XinYuColors.muted,
                ),
                const SizedBox(width: 7),
              ],
              Flexible(
                child: Text(
                  label,
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

class _SettingsGroup extends StatelessWidget {
  const _SettingsGroup({
    required this.title,
    required this.icon,
    required this.children,
    this.subtitle,
  });
  final String title;
  final String? subtitle;
  final IconData icon;
  final List<Widget> children;
  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      borderRadius: BorderRadius.circular(23),
      gradient: const LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [Color(0x70ffffff), Color(0x24ffffff)],
      ),
      border: Border.all(color: const Color(0xafffffff)),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 18, color: XinYuColors.accent),
            const SizedBox(width: 9),
            Expanded(
              child: Text(
                title,
                style: const TextStyle(
                  fontWeight: FontWeight.w600,
                  fontSize: 14,
                ),
              ),
            ),
          ],
        ),
        if (subtitle != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              subtitle!,
              style: const TextStyle(
                color: XinYuColors.muted,
                fontSize: 12,
                height: 1.6,
              ),
            ),
          ),
        const SizedBox(height: 16),
        ...children,
      ],
    ),
  );
}

class _ChoiceCard extends StatelessWidget {
  const _ChoiceCard({
    required this.title,
    required this.description,
    required this.icon,
    required this.selected,
    required this.onTap,
    this.horizontal = false,
  });
  final String title, description;
  final IconData icon;
  final bool selected, horizontal;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final mark = Icon(
      selected ? Icons.check_circle_rounded : Icons.circle_outlined,
      size: 17,
      color: selected ? XinYuColors.accent : const Color(0x5561736c),
    );
    final text = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 5),
        Text(
          description,
          style: const TextStyle(
            fontSize: 11,
            height: 1.55,
            color: XinYuColors.muted,
          ),
        ),
      ],
    );
    return Semantics(
      button: true,
      selected: selected,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(17),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 160),
            padding: const EdgeInsets.all(13),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(17),
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: selected
                    ? [const Color(0xedfafff9), const Color(0x9cc6e3d4)]
                    : [const Color(0x90ffffff), const Color(0x30ffffff)],
              ),
              border: Border.all(
                color: selected
                    ? const Color(0x96779e8a)
                    : const Color(0xc0ffffff),
                width: 1,
              ),
              boxShadow: selected
                  ? const [
                      BoxShadow(
                        color: Color(0x12476f5b),
                        blurRadius: 12,
                        offset: Offset(0, 4),
                      ),
                    ]
                  : null,
            ),
            child: horizontal
                ? Row(
                    children: [
                      Icon(icon, size: 23, color: XinYuColors.accent),
                      const SizedBox(width: 12),
                      Expanded(child: text),
                      const SizedBox(width: 8),
                      mark,
                    ],
                  )
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(icon, size: 22, color: XinYuColors.accent),
                          const Spacer(),
                          mark,
                        ],
                      ),
                      const SizedBox(height: 11),
                      text,
                    ],
                  ),
          ),
        ),
      ),
    );
  }
}

class _SettingsToggle extends StatelessWidget {
  const _SettingsToggle({
    required this.title,
    required this.subtitle,
    required this.value,
    required this.onChanged,
  });
  final String title, subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;
  @override
  Widget build(BuildContext context) => SwitchListTile.adaptive(
    contentPadding: EdgeInsets.zero,
    title: Text(title, style: const TextStyle(fontSize: 13, height: 1.5)),
    subtitle: Padding(
      padding: const EdgeInsets.only(top: 5),
      child: Text(
        subtitle,
        style: const TextStyle(
          fontSize: 11,
          height: 1.6,
          color: XinYuColors.muted,
        ),
      ),
    ),
    value: value,
    onChanged: onChanged,
  );
}

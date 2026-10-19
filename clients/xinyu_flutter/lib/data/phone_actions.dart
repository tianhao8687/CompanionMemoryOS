String phoneActionDescription(String name, Map<String, dynamic> args) {
  final target = args['expected_package'] ?? args['package_name'] ?? '目标应用';
  final label =
      args['message'] is String && (args['message'] as String).isNotEmpty
      ? '，名称为“${args['message']}”'
      : '';
  String two(Object? value) => '$value'.padLeft(2, '0');
  switch (name) {
    case 'read_chat_notifications':
      final app = args['package_name'] == 'com.tencent.mm' ? '微信' : 'QQ';
      final filter = args['title_filter'];
      return '读取$app当前通知栏中${filter == null ? '' : '标题含“$filter”的'}'
          '最新 ${args['limit'] ?? 1} 条预览。内容会进入本次对话的工具记录并交给配置的模型；'
          '只帮助理解和起草回复，不发送消息。';
    case 'set_volume':
      return '将媒体音量设为 ${args['level']} 档。';
    case 'set_brightness':
      final level = args['level'];
      return level is num
          ? '将屏幕亮度设为约 ${(level / 255 * 100).round()}%，并切换为手动亮度。'
          : '调整屏幕亮度，并切换为手动亮度。';
    case 'vibrate':
      return '让手机振动 ${args['duration_ms']} 毫秒。';
    case 'vibrate_pattern':
      final timings = args['timings'];
      return timings is List && timings.length == 4
          ? '让手机短拍两下，共约 0.36 秒，不循环。触感强弱由手机决定。'
          : '让手机按间隔短震三次，共约 4.64 秒，不循环。触感强弱由手机决定。';
    case 'cancel_vibration':
      return '停止心隅发起的震动。';
    case 'create_timer':
      final seconds = args['seconds'];
      final duration = seconds is int && seconds % 60 == 0
          ? '${seconds ~/ 60} 分钟'
          : '$seconds 秒';
      return '请系统时钟创建 $duration 的计时器$label。';
    case 'create_alarm':
      const days = {
        'mon': '周一',
        'tue': '周二',
        'wed': '周三',
        'thu': '周四',
        'fri': '周五',
        'sat': '周六',
        'sun': '周日',
      };
      final repeat = '${args['days'] ?? ''}'
          .split(',')
          .map((day) => day.trim().toLowerCase())
          .where((day) => day.isNotEmpty)
          .map((day) => days[day] ?? day)
          .join('、');
      return '请系统时钟设置 ${two(args['hour'])}:${two(args['minute'])} 的闹钟$label。'
          '${repeat.isEmpty ? '不重复。' : '重复：$repeat。'}';
    case 'set_dnd_mode':
      const modes = {
        'off': '关闭勿扰',
        'priority': '仅允许优先通知',
        'alarms': '仅允许闹钟',
        'none': '完全静音（含闹钟）',
      };
      return '将勿扰模式设为：${modes[args['mode']] ?? args['mode']}。';
    case 'launch_app':
      return '打开应用：$target。';
    case 'set_node_text':
      return '在 $target 的目标输入框中填写：“${args['text']}”。';
    case 'click_node':
      final node = args['text'] ?? args['view_id'] ?? '已定位的控件';
      return '在 $target 点击“$node”。';
    case 'tap':
      return '在 $target 点击已定位的位置（${args['x']}, ${args['y']}）。';
    case 'long_click_node':
      final node = args['text'] ?? args['view_id'] ?? '已定位的控件';
      return '在 $target 长按“$node”，随后核对弹出的菜单或界面。';
    case 'gesture':
      final points = args['points'];
      if (points is List && points.length >= 2) {
        return '在 $target 从 ${points.first} 滑动到 ${points.last}，随后核对界面。';
      }
      return '在 $target 沿已定位的路径滑动，随后核对界面。';
    case 'scroll_node':
      return '在 $target ${args['direction'] == 'backward' ? '向前' : '向后'}滚动。';
    case 'global_action':
      const actions = {'back': '返回上一页', 'home': '回到桌面', 'recents': '打开最近任务'};
      return '从 $target ${actions[args['action']] ?? args['action']}。';
    case 'query_screen':
    case 'find_node':
    case 'get_active_window_info':
      return '读取 $target 的当前界面；读取内容会交给当前配置的模型。';
    case 'get_app_info':
      return '查看应用信息：$target。';
    case 'list_installed_apps':
      return '查看这台手机上可见的已安装应用。';
    default:
      return '读取这台手机的相关状态。';
  }
}

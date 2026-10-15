import 'dart:convert';

Map<String, dynamic> automationMap(Object? value) =>
    value is Map ? Map<String, dynamic>.from(value) : {};

List<Map<String, dynamic>> automationList(Object? value) =>
    value is List ? value.whereType<Map>().map(automationMap).toList() : [];

class AutomationState {
  AutomationState(Map<String, dynamic> value)
    : config = automationMap(value['config']),
      capabilities = automationMap(value['capabilities']),
      catalog = automationMap(value['catalog']),
      tools = automationList(value['tools']),
      actions = automationList(value['actions']);

  final Map<String, dynamic> config, capabilities, catalog;
  final List<Map<String, dynamic>> tools, actions;
  Map<String, dynamic>? get netease =>
      automationList(config['servers'])
          .where((server) => server['id'] == 'netease')
          .firstOrNull;
  List<Map<String, dynamic>> get neteaseTools =>
      automationList(catalog['netease']);
  List<Map<String, dynamic>> get pending =>
      actions.where((action) => action['status'] == 'pending').toList();
  bool get supportsNetease {
    final value = capabilities['netease'];
    return value == true ||
        (value is Map &&
            (value['supported'] == true || value['available'] == true));
  }

  Map<String, dynamic> copyConfig() =>
      jsonDecode(jsonEncode(config)) as Map<String, dynamic>;

  String permission(String name) =>
      automationMap(automationMap(netease?['tools'])[name])['mode']
          as String? ??
      'ask';

  String actionTitle(Map<String, dynamic> action) {
    final binding = tools
        .where((tool) => tool['name'] == action['tool_name'])
        .firstOrNull;
    final remoteName = binding?['remote_name'] as String?;
    if (remoteName == 'netease_control') {
      return switch (automationMap(action['arguments'])['action']) {
        'play' => '继续播放网易云音乐',
        'pause' => '暂停网易云音乐',
        'next' => '网易云音乐：下一首',
        'previous' => '网易云音乐：上一首',
        _ => '控制网易云播放',
      };
    }
    return remoteName == null
        ? ((action['tool_name'] as String? ?? '').startsWith('mcp_netease_')
              ? '网易云音乐操作'
              : (action['tool_name'] as String? ?? '应用操作'))
        : musicToolTitle(remoteName);
  }
}

String musicToolTitle(String name) => switch (name) {
  'netease_status' => '检查网易云连接',
  'netease_search_songs' => '找一首歌',
  'netease_open_song' => '在网易云打开歌曲',
  'netease_playback_state' => '看看正在听什么',
  'netease_control' => '暂停、继续与切歌',
  'netease_seek' => '调整播放进度',
  _ => name,
};

String musicToolDescription(Map<String, dynamic> tool) =>
    switch (tool['name']) {
      'netease_status' => '查看这台电脑是否安装网易云，以及播放器是否就绪。',
      'netease_search_songs' => '按歌名、歌手或一句歌词找歌，核对后再播放。',
      'netease_open_song' => '将你选好的歌曲交给网易云客户端打开，播放仍遵循你的账号权限。',
      'netease_playback_state' => '读取网易云当前歌曲、歌手与播放状态。',
      'netease_control' => '控制网易云暂停、继续播放、上一首和下一首。',
      'netease_seek' => '在播放器支持时跳转到当前歌曲的指定位置。',
      _ => tool['description'] as String? ?? '',
    };

String automationStatus(String? value) => switch (value) {
  'pending' => '等待你确认 · 尚未执行',
  'running' => '正在执行',
  'succeeded' => '已完成',
  'failed' => '未完成',
  'uncertain' => '结果待核对，请先查看网易云',
  'denied' => '已拒绝',
  _ => value ?? '等待更新',
};

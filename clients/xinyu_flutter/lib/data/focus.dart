class FocusSession {
  FocusSession(Map<String, dynamic> value)
    : id = value['id'] as String,
      revision = value['revision'] as int,
      phase = value['phase'] as String,
      intention = value['intention'] as String? ?? '',
      minutes = value['focus_minutes'] as int,
      remaining = (value['remaining_seconds'] as num).toDouble(),
      deadline = (value['deadline'] as num?)?.toDouble(),
      endedAt = (value['ended_at'] as num?)?.toDouble(),
      noticeRevision = value['notice_revision'] as int?;
  final String id, phase, intention;
  final int revision, minutes;
  final double remaining;
  final double? deadline, endedAt;
  final int? noticeRevision;
  bool get settled => const {'done', 'ended'}.contains(phase);
  bool get closed => settled || phase == 'focus_done';
  bool get paused => phase.endsWith('_paused');
  String get action => paused
      ? 'resume'
      : phase == 'focus_done'
      ? 'rest'
      : 'pause';
  String get actionLabel => paused
      ? '继续'
      : phase == 'focus_done'
      ? '休息一下'
      : '暂停';
  String get label =>
      const {
        'focus': '专注中',
        'focus_paused': '已暂停',
        'focus_done': '时间到了',
        'rest': '休息中',
        'rest_paused': '休息已暂停',
        'done': '休息结束',
        'ended': '已结束',
      }[phase] ??
      '';
  String get line => switch (phase) {
    'focus' => '好，先 $minutes 分钟。',
    'focus_paused' => '好，暂停了。',
    'focus_done' => '$minutes 分钟到了。',
    'rest' => '好，歇一会儿。',
    'rest_paused' => '休息计时暂停了。',
    'done' => '休息时间到了。',
    _ => '好，先到这里。',
  };
}

String focusTime(int seconds) =>
    '${(seconds ~/ 60).toString().padLeft(2, '0')}:${(seconds % 60).toString().padLeft(2, '0')}';

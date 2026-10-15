import 'dart:convert';

import 'focus.dart';

enum FocusInteraction { touch, chooseStep, completeStep, breathe }

/// A visible record of an explicit UI action, sent through ordinary chat.
/// It makes no claims about mood, attention, or unreported task progress.
String focusInteractionMessage(
  FocusInteraction action, {
  FocusSession? session,
  String? step,
}) => [
  '【专注页互动 · 用户点击】',
  switch (action) {
    FocusInteraction.touch => '动作：我轻碰了你的头像，叫你一声。',
    FocusInteraction.chooseStep => '动作：我选定了下面这个小步骤。',
    FocusInteraction.completeStep => '动作：我点击“做好了”，确认下面这个小步骤已经完成。整体任务进度尚未确认。',
    FocusInteraction.breathe => '动作：我点击“一起缓缓”，暂停计时，进入可跳过的呼吸引导。',
  },
  if (session != null) '计时状态：${session.label}。',
  if (session != null && session.intention.isNotEmpty)
    '当前任务：${jsonEncode(session.intention)}',
  if (step != null) '小步骤：${jsonEncode(step)}',
  '以上是界面动作记录，不是对我的情绪或行为的观察。沿用你的性格和我们的谈话，简短回应这个动作即可，不必复述记录或主动安排下一步。',
].join('\n');

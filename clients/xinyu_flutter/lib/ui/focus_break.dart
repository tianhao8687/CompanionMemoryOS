import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../state/companion_controller.dart';
import 'focus_style.dart';
import 'focus_header.dart';
import 'focus_reply.dart';
import 'local_image.dart';

/// An optional, bounded pause. The shared server clock stays paused on exit.
class FocusBreak extends StatefulWidget {
  const FocusBreak({super.key, required this.controller});
  final CompanionController controller;
  @override
  State<FocusBreak> createState() => _FocusBreakState();
}

class _FocusBreakState extends State<FocusBreak>
    with SingleTickerProviderStateMixin {
  late final breath = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 20),
    animationBehavior: AnimationBehavior.preserve,
  )..forward();

  @override
  void dispose() {
    breath.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Theme(
    data: FocusStyle.theme(context),
    child: Builder(
      builder: (context) => CallbackShortcuts(
        bindings: {
          const SingleActivator(LogicalKeyboardKey.escape): () =>
              Navigator.pop(context),
        },
        child: Focus(
          autofocus: true,
          child: Scaffold(
            key: const Key('focus-break-screen'),
            body: Stack(
              fit: StackFit.expand,
              children: [
                ExcludeSemantics(
                  child: Image.asset(
                    FocusStyle.background,
                    fit: BoxFit.cover,
                    alignment: const Alignment(.1, 0),
                  ),
                ),
                SafeArea(
                  child: Column(
                    children: [
                      const FocusPageHeader(title: '一起缓缓', backLabel: '回到专注'),
                      Expanded(
                        child: LayoutBuilder(
                          builder: (context, bounds) => SingleChildScrollView(
                            padding: const EdgeInsets.fromLTRB(24, 24, 24, 40),
                            child: ConstrainedBox(
                              constraints: BoxConstraints(
                                minHeight: math.max(0, bounds.maxHeight - 64),
                              ),
                              child: Center(
                                child: ConstrainedBox(
                                  constraints: const BoxConstraints(
                                    maxWidth: 440,
                                  ),
                                  child: AnimatedBuilder(
                                    animation: breath,
                                    builder: (context, _) {
                                      final seconds = breath.value * 20;
                                      final done = breath.isCompleted;
                                      final cycle = seconds % 10;
                                      final inhale = cycle < 4;
                                      final expansion = inhale
                                          ? cycle / 4
                                          : 1 - (cycle - 4) / 6;
                                      final reduced =
                                          MediaQuery.disableAnimationsOf(
                                            context,
                                          );
                                      final label = done
                                          ? '慢慢来，准备好再继续。'
                                          : inhale
                                          ? '慢慢吸气'
                                          : '慢慢呼气';
                                      return Column(
                                        mainAxisSize: MainAxisSize.min,
                                        children: [
                                          Row(
                                            mainAxisAlignment:
                                                MainAxisAlignment.center,
                                            children: [
                                              _avatar(false),
                                              const Padding(
                                                padding: EdgeInsets.symmetric(
                                                  horizontal: 24,
                                                ),
                                                child: Icon(
                                                  Icons.more_horiz_rounded,
                                                  color: FocusStyle.muted,
                                                ),
                                              ),
                                              _avatar(true),
                                            ],
                                          ),
                                          const SizedBox(height: 24),
                                          FocusReply(
                                            controller: widget.controller,
                                          ),
                                          const SizedBox(height: 16),
                                          ExcludeSemantics(
                                            child: SizedBox(
                                              width: 232,
                                              height: 232,
                                              child: Center(
                                                child: Transform.scale(
                                                  scale: reduced || done
                                                      ? .9
                                                      : .78 + expansion * .22,
                                                  child: Container(
                                                    width: 224,
                                                    height: 224,
                                                    decoration: BoxDecoration(
                                                      shape: BoxShape.circle,
                                                      border: Border.all(
                                                        color: const Color(
                                                          0xccffffff,
                                                        ),
                                                        width: 1.5,
                                                      ),
                                                      gradient:
                                                          const RadialGradient(
                                                            colors: [
                                                              Color(0x25ffffff),
                                                              Color(0x55ffe4ed),
                                                              Color(0xb3f5f7fc),
                                                            ],
                                                          ),
                                                    ),
                                                    child: const Icon(
                                                      Icons.air_rounded,
                                                      size: 48,
                                                      color: FocusStyle.accent,
                                                    ),
                                                  ),
                                                ),
                                              ),
                                            ),
                                          ),
                                          const SizedBox(height: 24),
                                          Semantics(
                                            liveRegion: true,
                                            child: Text(
                                              label,
                                              key: const Key(
                                                'focus-breath-instruction',
                                              ),
                                              textAlign: TextAlign.center,
                                              style: FocusStyle.heading
                                                  .copyWith(
                                                    fontSize:
                                                        MediaQuery.sizeOf(
                                                              context,
                                                            ).width <
                                                            600
                                                        ? 22
                                                        : 26,
                                                  ),
                                            ),
                                          ),
                                          const SizedBox(height: 12),
                                          const Text(
                                            '按自己的节奏，也可以只是坐一会儿。',
                                            textAlign: TextAlign.center,
                                            style: FocusStyle.caption,
                                          ),
                                          const SizedBox(height: 12),
                                          Text(
                                            done
                                                ? '呼吸引导已结束'
                                                : '${seconds < 10 ? 1 : 2} / 2',
                                            style: FocusStyle.caption,
                                          ),
                                          const SizedBox(height: 32),
                                          OutlinedButton(
                                            key: const Key(
                                              'focus-break-return',
                                            ),
                                            onPressed: () =>
                                                Navigator.pop(context),
                                            child: const Text('回到专注'),
                                          ),
                                          const SizedBox(height: 12),
                                          ListenableBuilder(
                                            listenable: widget.controller.focus,
                                            builder: (context, _) => Text(
                                              widget
                                                          .controller
                                                          .focus
                                                          .session
                                                          ?.paused ==
                                                      true
                                                  ? '计时已暂停，回来后点「继续」。'
                                                  : '当前计时状态：${widget.controller.focus.session?.label ?? '未开始'}',
                                              textAlign: TextAlign.center,
                                              style: FocusStyle.caption,
                                            ),
                                          ),
                                        ],
                                      );
                                    },
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );

  Widget _avatar(bool user) => Semantics(
    image: true,
    label: user ? '你' : widget.controller.companionDisplayName,
    child: ProfileAvatar(
      controller: widget.controller,
      isUser: user,
      size: 56,
      shape: BoxShape.circle,
      fallbackColor: user ? FocusStyle.surface : FocusStyle.avatar,
      foregroundColor: user ? FocusStyle.accent : Colors.white,
    ),
  );
}

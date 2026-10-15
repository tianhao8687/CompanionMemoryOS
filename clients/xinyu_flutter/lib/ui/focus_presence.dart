import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import '../data/focus_interaction.dart';
import 'focus_style.dart';
import 'focus_field.dart';
import 'local_image.dart';

class FocusCompanionAvatar extends StatefulWidget {
  const FocusCompanionAvatar({
    super.key,
    required this.controller,
    required this.size,
  });
  final CompanionController controller;
  final double size;
  @override
  State<FocusCompanionAvatar> createState() => _FocusCompanionAvatarState();
}

class _FocusCompanionAvatarState extends State<FocusCompanionAvatar>
    with SingleTickerProviderStateMixin {
  late final animation = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 900),
  );
  int seen = 0;
  bool reduceMotion = false;

  @override
  void initState() {
    super.initState();
    seen = widget.controller.focus.presence.cue;
    widget.controller.focus.presence.addListener(_respond);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    reduceMotion = MediaQuery.disableAnimationsOf(context);
    if (reduceMotion) animation.stop();
  }

  void _respond() {
    final cue = widget.controller.focus.presence.cue;
    if (seen == cue) return;
    seen = cue;
    if (!reduceMotion) animation.forward(from: 0);
  }

  @override
  void didUpdateWidget(FocusCompanionAvatar oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller == widget.controller) return;
    oldWidget.controller.focus.presence.removeListener(_respond);
    seen = widget.controller.focus.presence.cue;
    widget.controller.focus.presence.addListener(_respond);
  }

  @override
  void dispose() {
    widget.controller.focus.presence.removeListener(_respond);
    animation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: animation,
    builder: (context, child) {
      final t = reduceMotion ? 0.0 : animation.value;
      final response = math.sin(t * math.pi);
      return Transform.translate(
        offset: Offset(0, -4 * response),
        child: Transform.rotate(
          angle: math.sin(t * math.pi * 2) * .035,
          child: Stack(
            clipBehavior: Clip.none,
            alignment: Alignment.center,
            children: [
              Positioned(
                top: -48,
                left: -48,
                right: -48,
                bottom: -48,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: RadialGradient(
                      colors: [
                        const Color(0xb3ffe0e6),
                        const Color(0x60ffe0e6),
                        const Color(0x00ffe0e6),
                      ],
                      stops: [0, .4 + response * .15, 1],
                    ),
                  ),
                ),
              ),
              if (response > 0)
                Positioned(
                  width: widget.size + t * 72,
                  height: widget.size + t * 72,
                  child: IgnorePointer(
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        border: Border.all(
                          color: Colors.white.withValues(alpha: (1 - t) * .65),
                        ),
                      ),
                    ),
                  ),
                ),
              child!,
            ],
          ),
        ),
      );
    },
    child: Tooltip(
      message: '轻碰头像，叫我一声',
      child: Semantics(
        button: true,
        label: '轻碰${widget.controller.companionDisplayName}，叫我一声',
        child: Material(
          color: Colors.transparent,
          shape: const CircleBorder(),
          child: InkWell(
            key: const Key('focus-touch'),
            customBorder: const CircleBorder(),
            onTap: widget.controller.canInteractWithFocus
                ? () => widget.controller.interactWithFocus(
                    FocusInteraction.touch,
                  )
                : null,
            child: Padding(
              padding: const EdgeInsets.all(4),
              child: ProfileAvatar(
                controller: widget.controller,
                size: widget.size,
                shape: BoxShape.circle,
                fallbackColor: FocusStyle.avatar,
                foregroundColor: Colors.white,
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

Future<void> showFocusStep(
  BuildContext context,
  CompanionController controller,
) async {
  final sessionId = controller.focus.session?.id;
  final result = await showDialog<String>(
    context: context,
    builder: (_) => _StepEditor(initial: controller.focus.presence.step ?? ''),
  );
  if (result != null && controller.focus.session?.id == sessionId) {
    await controller.interactWithFocus(
      FocusInteraction.chooseStep,
      step: result,
    );
  }
}

class _StepEditor extends StatefulWidget {
  const _StepEditor({required this.initial});
  final String initial;
  @override
  State<_StepEditor> createState() => _StepEditorState();
}

class _StepEditorState extends State<_StepEditor> {
  late final text = TextEditingController(text: widget.initial);
  final form = GlobalKey<FormState>();
  @override
  void dispose() {
    text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    scrollable: true,
    title: const Text('先做哪一小步？'),
    content: SizedBox(
      width: 400,
      child: Form(
        key: form,
        child: FocusField(
          inputKey: const Key('focus-step-input'),
          controller: text,
          autofocus: true,
          maxLength: 160,
          minLines: 1,
          maxLines: 3,
          label: '一件现在能动手的小事',
          validator: (value) =>
              value == null || value.trim().isEmpty ? '写下这一步，或者先不选。' : null,
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('先不选'),
      ),
      FilledButton(
        key: const Key('focus-step-save'),
        onPressed: () {
          if (form.currentState!.validate()) {
            Navigator.pop(context, text.text.trim());
          }
        },
        child: const Text('就做这一步'),
      ),
    ],
  );
}

class FocusStepCard extends StatelessWidget {
  const FocusStepCard({super.key, required this.controller});
  final CompanionController controller;
  @override
  Widget build(BuildContext context) {
    final presence = controller.focus.presence;
    final step = presence.step ?? presence.lastCompletedStep;
    if (step == null) {
      return TextButton.icon(
        key: const Key('focus-choose-step'),
        onPressed: controller.canInteractWithFocus
            ? () => showFocusStep(context, controller)
            : null,
        icon: const Icon(Icons.add_rounded, size: 20),
        label: const Text('选一个小步骤'),
      );
    }
    final done = presence.step == null;
    return Container(
      key: const Key('focus-step-card'),
      constraints: const BoxConstraints(maxWidth: 440),
      padding: const EdgeInsets.fromLTRB(20, 16, 12, 16),
      decoration: BoxDecoration(
        color: const Color(0x94f5f7fc),
        border: Border.all(color: const Color(0xb3ffffff)),
        borderRadius: BorderRadius.circular(22),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final description = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(done ? '你刚刚做到了' : '先做这一小步', style: FocusStyle.caption),
              const SizedBox(height: 4),
              Text(step, style: FocusStyle.body),
            ],
          );
          final actions = Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              TextButton.icon(
                key: Key(done ? 'focus-next-step' : 'focus-step-done'),
                onPressed: !controller.canInteractWithFocus
                    ? null
                    : done
                    ? () => showFocusStep(context, controller)
                    : () => controller.interactWithFocus(
                        FocusInteraction.completeStep,
                      ),
                icon: Icon(
                  done ? Icons.add_rounded : Icons.check_rounded,
                  size: 20,
                ),
                label: Text(done ? '再选一步' : '做好了'),
              ),
              if (!done)
                IconButton(
                  tooltip: '修改小步骤',
                  onPressed: controller.canInteractWithFocus
                      ? () => showFocusStep(context, controller)
                      : null,
                  icon: const Icon(Icons.edit_outlined, size: 20),
                ),
            ],
          );
          if (constraints.maxWidth < 340 ||
              MediaQuery.textScalerOf(context).scale(14) > 18) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [description, const SizedBox(height: 8), actions],
            );
          }
          return Row(
            children: [
              Expanded(child: description),
              const SizedBox(width: 12),
              actions,
            ],
          );
        },
      ),
    );
  }
}

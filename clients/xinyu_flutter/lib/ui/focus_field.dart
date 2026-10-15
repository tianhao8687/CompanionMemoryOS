import 'package:flutter/material.dart';

import 'focus_style.dart';

/// A stationary label never shrinks into a field's border while typing.
class FocusField extends StatelessWidget {
  const FocusField({
    super.key,
    required this.inputKey,
    required this.controller,
    required this.label,
    this.hint,
    this.unit,
    this.maxLength,
    this.minLines = 1,
    this.maxLines = 1,
    this.numeric = false,
    this.autofocus = false,
    this.enabled = true,
    this.validator,
    this.onChanged,
  });
  final Key inputKey;
  final TextEditingController controller;
  final String label;
  final String? hint, unit;
  final int? maxLength;
  final int minLines, maxLines;
  final bool numeric, autofocus, enabled;
  final FormFieldValidator<String>? validator;
  final ValueChanged<String>? onChanged;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    mainAxisSize: MainAxisSize.min,
    children: [
      Padding(
        padding: const EdgeInsets.only(left: 4, bottom: 8),
        child: Text(label, style: FocusStyle.caption),
      ),
      Semantics(
        label: unit == null ? label : '$label，$unit',
        child: TextFormField(
          key: inputKey,
          controller: controller,
          enabled: enabled,
          autofocus: autofocus,
          maxLength: maxLength,
          minLines: minLines,
          maxLines: maxLines,
          keyboardType: numeric ? TextInputType.number : null,
          style: FocusStyle.body.copyWith(fontSize: 16, height: 1.5),
          decoration: InputDecoration(
            hintText: hint,
            suffixText: unit,
            counterText: '',
          ),
          validator: validator,
          onChanged: onChanged,
        ),
      ),
    ],
  );
}

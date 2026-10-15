import 'package:flutter/material.dart';

import 'typography.dart';

/// The room and its controls share one quiet surface, with no nested cards.
abstract final class NookStyle {
  static const surface = Color(0xfffaf8f3);
  static const ink = Color(0xff303a36);
  static const muted = Color(0xff69736c);
  static const accent = Color(0xff536851);
  static const line = Color(0xffe1e4dc);
  static const avatar = Color(0xffe5e8de);

  static ThemeData theme(BuildContext context) {
    final base = Theme.of(context);
    const shape = RoundedRectangleBorder(
      borderRadius: BorderRadius.all(Radius.circular(14)),
    );
    return base.copyWith(
      colorScheme: base.colorScheme.copyWith(
        primary: accent,
        onPrimary: Colors.white,
        surface: surface,
        onSurface: ink,
        outline: line,
      ),
      textTheme: base.textTheme.apply(bodyColor: ink, displayColor: ink),
      iconTheme: const IconThemeData(color: muted, size: 22),
      dividerTheme: const DividerThemeData(color: line, thickness: 1, space: 1),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: accent,
          foregroundColor: Colors.white,
          minimumSize: const Size(104, 46),
          shape: shape,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 12),
          textStyle: const TextStyle(
            fontFamily: XinYuTypography.family,
            fontSize: 14,
            fontWeight: FontWeight.w500,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: accent,
          side: const BorderSide(color: line),
          shape: shape,
          minimumSize: const Size(72, 44),
          textStyle: const TextStyle(
            fontFamily: XinYuTypography.family,
            fontSize: 14,
            fontWeight: FontWeight.w500,
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: accent,
          minimumSize: const Size(48, 44),
          shape: shape,
          textStyle: const TextStyle(
            fontFamily: XinYuTypography.family,
            fontSize: 14,
            fontWeight: FontWeight.w500,
          ),
        ),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(
          foregroundColor: muted,
          minimumSize: const Size(44, 44),
          shape: shape,
        ),
      ),
      popupMenuTheme: const PopupMenuThemeData(color: surface),
    );
  }
}

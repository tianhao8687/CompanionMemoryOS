import 'package:flutter/material.dart';

abstract final class MusicStyle {
  static const ink = Color(0xfff6f2e9);
  static const muted = Color(0xffc8cfc8);
  static const background = Color(0xff20282a);
  static const line = Color(0x26ffffff);
  static const accent = Color(0xffeadcc3);
  static const note = TextStyle(fontSize: 14, height: 1.5, color: muted);
  static const gradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xff4a5750), Color(0xff354241), background],
    stops: [0, .45, 1],
  );

  static ThemeData theme(BuildContext context) {
    final base = Theme.of(context);
    return base.copyWith(
      brightness: Brightness.dark,
      colorScheme: const ColorScheme.dark(
        primary: accent,
        onPrimary: background,
        surface: background,
        onSurface: ink,
        onSurfaceVariant: muted,
        outline: line,
      ),
      iconTheme: const IconThemeData(color: ink, size: 24),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(
          foregroundColor: ink,
          minimumSize: const Size.square(48),
          maximumSize: const Size.square(48),
          fixedSize: const Size.square(48),
          padding: const EdgeInsets.all(12),
          iconSize: 24,
          shape: const CircleBorder(),
        ),
      ),
      textTheme: base.textTheme.apply(bodyColor: ink, displayColor: ink),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: ink,
          minimumSize: const Size(48, 48),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0x12ffffff),
        hintStyle: note,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 18,
          vertical: 12,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(28),
          borderSide: const BorderSide(color: line),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(28),
          borderSide: const BorderSide(color: line),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(28),
          borderSide: const BorderSide(color: accent),
        ),
      ),
    );
  }
}

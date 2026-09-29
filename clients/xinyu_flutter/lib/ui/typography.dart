import 'package:flutter/material.dart';

/// Bundled on every platform so Chinese and Latin text share the same metrics.
abstract final class XinYuTypography {
  static const family = 'Noto Sans SC';
  static const fontAsset = 'assets/fonts/NotoSansSC-Variable.ttf';

  // Preserve Material's localized sizes and colors, using the font's own spacing.
  static const textTheme = TextTheme(
    displayLarge: TextStyle(letterSpacing: 0),
    displayMedium: TextStyle(letterSpacing: 0),
    displaySmall: TextStyle(letterSpacing: 0),
    headlineLarge: TextStyle(letterSpacing: 0),
    headlineMedium: TextStyle(letterSpacing: 0),
    headlineSmall: TextStyle(letterSpacing: 0),
    titleLarge: TextStyle(letterSpacing: 0, fontWeight: FontWeight.w500),
    titleMedium: TextStyle(letterSpacing: 0, fontWeight: FontWeight.w500),
    titleSmall: TextStyle(letterSpacing: 0, fontWeight: FontWeight.w500),
    bodyLarge: TextStyle(letterSpacing: 0, fontWeight: FontWeight.w400),
    bodyMedium: TextStyle(letterSpacing: 0, fontWeight: FontWeight.w400),
    bodySmall: TextStyle(letterSpacing: 0, fontWeight: FontWeight.w400),
    labelLarge: TextStyle(letterSpacing: 0, fontWeight: FontWeight.w500),
    labelMedium: TextStyle(letterSpacing: 0, fontWeight: FontWeight.w500),
    labelSmall: TextStyle(letterSpacing: 0, fontWeight: FontWeight.w500),
  );

  /// Compose and read at the same size; the app's accessibility scaler still applies.
  static TextStyle message({required bool compact}) => TextStyle(
    fontSize: compact ? 16 : 18,
    fontWeight: FontWeight.w400,
    letterSpacing: 0,
    height: 1.5,
  );
}

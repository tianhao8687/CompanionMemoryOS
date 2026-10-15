import 'package:flutter/material.dart';

/// Bundled on every platform so Chinese and Latin text share the same metrics.
abstract final class XinYuTypography {
  static const family = 'Noto Sans SC';
  static const fontAsset = 'assets/fonts/NotoSansSC-Variable.ttf';

  // Explicit roles prevent Material defaults and per-page guesses from drifting.
  static const textTheme = TextTheme(
    displayLarge: TextStyle(letterSpacing: 0),
    displayMedium: TextStyle(letterSpacing: 0),
    displaySmall: TextStyle(letterSpacing: 0),
    headlineLarge: TextStyle(letterSpacing: 0),
    headlineMedium: TextStyle(letterSpacing: 0),
    headlineSmall: TextStyle(letterSpacing: 0),
    titleLarge: TextStyle(
      fontSize: 22,
      height: 1.5,
      letterSpacing: 0,
      fontWeight: FontWeight.w500,
    ),
    titleMedium: TextStyle(
      fontSize: 18,
      height: 1.5,
      letterSpacing: 0,
      fontWeight: FontWeight.w500,
    ),
    titleSmall: TextStyle(
      fontSize: 16,
      height: 1.5,
      letterSpacing: 0,
      fontWeight: FontWeight.w500,
    ),
    bodyLarge: TextStyle(
      fontSize: 16,
      height: 1.5,
      letterSpacing: 0,
      fontWeight: FontWeight.w400,
    ),
    bodyMedium: TextStyle(
      fontSize: 16,
      height: 1.5,
      letterSpacing: 0,
      fontWeight: FontWeight.w400,
    ),
    bodySmall: TextStyle(
      fontSize: 14,
      height: 1.5,
      letterSpacing: 0,
      fontWeight: FontWeight.w400,
    ),
    labelLarge: TextStyle(
      fontSize: 16,
      height: 1.5,
      letterSpacing: 0,
      fontWeight: FontWeight.w500,
    ),
    labelMedium: TextStyle(
      fontSize: 14,
      height: 1.5,
      letterSpacing: 0,
      fontWeight: FontWeight.w500,
    ),
    labelSmall: TextStyle(
      fontSize: 14,
      height: 1.5,
      letterSpacing: 0,
      fontWeight: FontWeight.w400,
    ),
  );

  static TextTheme forPlatform(TargetPlatform platform) =>
      {TargetPlatform.android, TargetPlatform.iOS}.contains(platform)
      ? textTheme.copyWith(
          titleLarge: textTheme.titleLarge!.copyWith(fontSize: 18),
          bodyLarge: textTheme.bodyLarge!.copyWith(fontSize: 17),
          bodyMedium: textTheme.bodyMedium!.copyWith(fontSize: 17),
        )
      : textTheme;

  /// Compose and read at the same size; the app's accessibility scaler still applies.
  static TextStyle message({required bool compact}) => TextStyle(
    fontSize: compact ? 17 : 18,
    fontWeight: FontWeight.w400,
    letterSpacing: 0,
    height: 1.5,
  );
}

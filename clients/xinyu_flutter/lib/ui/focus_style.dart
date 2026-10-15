import 'package:flutter/material.dart';

import 'typography.dart';

/// The lake supplies the atmosphere; controls share the app's glass language.
abstract final class FocusStyle {
  static const ink = Color(0xff293e59);
  static const muted = Color(0xff405571);
  static const accent = Color(0xff486384);
  static const avatar = Color(0xff718db2);
  static const surface = Color(0xfff3f6fb);
  static const line = Color(0x66ffffff);
  static const background = 'assets/focus/blue-hour.png';
  // Every focus surface uses the same family and two deliberate weights.
  // Medium keeps small Chinese text legible over the lake; semibold marks actions.
  static const control = TextStyle(
    fontFamily: XinYuTypography.family,
    fontSize: 15,
    fontWeight: FontWeight.w600,
    letterSpacing: 0,
    height: 1.4,
  );
  static const body = TextStyle(
    fontFamily: XinYuTypography.family,
    fontSize: 16,
    fontWeight: FontWeight.w500,
    letterSpacing: 0,
    height: 1.6,
    color: ink,
  );
  static const caption = TextStyle(
    fontFamily: XinYuTypography.family,
    fontSize: 14,
    fontWeight: FontWeight.w500,
    height: 1.5,
    letterSpacing: 0,
    color: muted,
  );
  static const heading = TextStyle(
    fontFamily: XinYuTypography.family,
    fontSize: 22,
    fontWeight: FontWeight.w600,
    height: 1.5,
    letterSpacing: 0,
    color: ink,
  );
  static const navigation = TextStyle(
    fontFamily: XinYuTypography.family,
    fontSize: 15,
    fontWeight: FontWeight.w600,
    height: 1.4,
    letterSpacing: 0,
    color: ink,
  );
  static const timer = TextStyle(
    fontFamily: XinYuTypography.family,
    fontSize: 56,
    fontWeight: FontWeight.w500,
    height: 1.25,
    letterSpacing: 0,
    fontFeatures: [FontFeature.tabularFigures()],
    color: ink,
  );

  static ThemeData theme(BuildContext context) {
    final base = Theme.of(context);
    final compact = MediaQuery.sizeOf(context).width < 360;
    const fieldBorder = OutlineInputBorder(
      borderRadius: BorderRadius.all(Radius.circular(18)),
      borderSide: BorderSide(color: Color(0xb3ffffff)),
    );
    return base.copyWith(
      colorScheme: base.colorScheme.copyWith(
        primary: accent,
        onPrimary: Colors.white,
        surface: surface,
        onSurface: ink,
        onSurfaceVariant: muted,
        outline: line,
      ),
      textTheme: base.textTheme
          .apply(
            fontFamily: XinYuTypography.family,
            bodyColor: ink,
            displayColor: ink,
          )
          .copyWith(
            bodyLarge: body,
            bodyMedium: body,
            bodySmall: caption,
            labelLarge: control,
            labelMedium: caption,
            labelSmall: caption,
            titleLarge: heading,
            titleMedium: control.copyWith(fontSize: 16, color: ink),
            titleSmall: control.copyWith(fontSize: 14, color: ink),
            headlineSmall: heading.copyWith(fontSize: 24),
            headlineMedium: heading.copyWith(fontSize: 26),
            headlineLarge: heading.copyWith(fontSize: 28),
          ),
      iconTheme: const IconThemeData(color: muted, size: 20),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: accent,
          foregroundColor: Colors.white,
          minimumSize: Size(compact ? 120 : 144, 52),
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
          shape: const StadiumBorder(),
          elevation: 0,
          textStyle: control,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: ink,
          backgroundColor: const Color(0x66ffffff),
          side: const BorderSide(color: Color(0xb3ffffff)),
          minimumSize: Size(compact ? 120 : 144, 52),
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
          shape: const StadiumBorder(),
          textStyle: control,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: ink,
          minimumSize: const Size(48, 48),
          shape: const StadiumBorder(),
          textStyle: control,
        ),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(
          foregroundColor: ink,
          minimumSize: const Size(48, 48),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0x8cffffff),
        labelStyle: caption,
        hintStyle: body.copyWith(color: muted, height: 1.5),
        suffixStyle: caption,
        errorStyle: caption.copyWith(color: base.colorScheme.error),
        errorMaxLines: 3,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 18,
          vertical: 16,
        ),
        border: fieldBorder,
        enabledBorder: fieldBorder,
        focusedBorder: fieldBorder.copyWith(
          borderSide: const BorderSide(color: accent, width: 1.5),
        ),
      ),
      menuTheme: const MenuThemeData(
        style: MenuStyle(
          backgroundColor: WidgetStatePropertyAll(Color(0xf5f5f7fc)),
          surfaceTintColor: WidgetStatePropertyAll(Colors.transparent),
          elevation: WidgetStatePropertyAll(2),
          shadowColor: WidgetStatePropertyAll(Color(0x26293e59)),
          shape: WidgetStatePropertyAll(
            RoundedRectangleBorder(
              borderRadius: BorderRadius.all(Radius.circular(22)),
              side: BorderSide(color: Color(0xddffffff)),
            ),
          ),
          padding: WidgetStatePropertyAll(EdgeInsets.all(8)),
        ),
      ),
      menuButtonTheme: MenuButtonThemeData(
        style: ButtonStyle(
          textStyle: WidgetStatePropertyAll(body.copyWith(fontSize: 15)),
          foregroundColor: const WidgetStatePropertyAll(ink),
          iconColor: const WidgetStatePropertyAll(muted),
          iconSize: const WidgetStatePropertyAll(20),
          minimumSize: const WidgetStatePropertyAll(Size(0, 48)),
          padding: const WidgetStatePropertyAll(
            EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          ),
          shape: const WidgetStatePropertyAll(
            RoundedRectangleBorder(
              borderRadius: BorderRadius.all(Radius.circular(14)),
            ),
          ),
        ),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: surface,
        surfaceTintColor: Colors.transparent,
        insetPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
        clipBehavior: Clip.antiAlias,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(28)),
        ),
        titleTextStyle: heading,
        contentTextStyle: body,
      ),
      listTileTheme: base.listTileTheme.copyWith(
        titleTextStyle: body,
        subtitleTextStyle: caption,
        minVerticalPadding: 12,
        horizontalTitleGap: 12,
        iconColor: muted,
      ),
      tooltipTheme: TooltipThemeData(
        textStyle: caption.copyWith(color: ink),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: surface,
          border: Border.all(color: Colors.white),
          borderRadius: BorderRadius.circular(12),
        ),
      ),
    );
  }
}

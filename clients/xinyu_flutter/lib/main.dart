import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'state/companion_controller.dart';
import 'data/managed_repository.dart';
import 'state/frame_probe.dart';
import 'ui/glass.dart';
import 'ui/home.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const XinYuApp(local: true));
}

class XinYuApp extends StatefulWidget {
  const XinYuApp({super.key, this.controller, this.probe, this.local = false});
  final bool local;
  final CompanionController? controller;
  final FrameProbe? probe;
  @override
  State<XinYuApp> createState() => _XinYuAppState();
}

class _XinYuAppState extends State<XinYuApp> {
  late final CompanionController controller =
      widget.controller ??
      CompanionController(
        repository: widget.local ? ManagedRepository() : null,
      );
  late final FrameProbe probe = widget.probe ?? FrameProbe();
  @override
  void initState() {
    super.initState();
    // Failures remain visible in the controller's error region.
    unawaited(controller.initialize().catchError((Object _) {}));
  }

  @override
  void dispose() {
    if (widget.controller == null) controller.dispose();
    if (widget.probe == null) probe.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: '心隅',
    debugShowCheckedModeBanner: false,
    builder: (context, child) => ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final scale = readingScale(controller.settings['font_size']);
        return MediaQuery(
          data: MediaQuery.of(context).copyWith(
            textScaler: _XinYuTextScaler(
              MediaQuery.textScalerOf(context),
              scale,
            ),
          ),
          child: child!,
        );
      },
    ),
    locale: const Locale('zh', 'CN'),
    supportedLocales: const [Locale('zh', 'CN'), Locale('en')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    theme: ThemeData(
      useMaterial3: true,
      fontFamily: Platform.isWindows ? 'Microsoft YaHei UI' : null,
      fontFamilyFallback: const [
        'Microsoft YaHei',
        'PingFang SC',
        'Noto Sans CJK SC',
      ],
      colorScheme:
          ColorScheme.fromSeed(
            seedColor: XinYuColors.accent,
            brightness: Brightness.light,
          ).copyWith(
            surface: const Color(0xfff1eee7),
            onSurface: XinYuColors.ink,
            primary: XinYuColors.accent,
          ),
      scaffoldBackgroundColor: Colors.transparent,
      dialogTheme: const DialogThemeData(
        shape: XinYuShapes.panel,
        clipBehavior: Clip.antiAlias,
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        shape: XinYuShapes.panel,
        clipBehavior: Clip.antiAlias,
      ),
      chipTheme: const ChipThemeData(shape: XinYuShapes.pill),
      checkboxTheme: const CheckboxThemeData(shape: CircleBorder()),
      listTileTheme: const ListTileThemeData(shape: XinYuShapes.field),
      popupMenuTheme: const PopupMenuThemeData(shape: XinYuShapes.card),
      menuTheme: const MenuThemeData(
        style: MenuStyle(shape: WidgetStatePropertyAll(XinYuShapes.card)),
      ),
      menuButtonTheme: const MenuButtonThemeData(
        style: ButtonStyle(shape: WidgetStatePropertyAll(XinYuShapes.pill)),
      ),
      datePickerTheme: const DatePickerThemeData(shape: XinYuShapes.panel),
      timePickerTheme: const TimePickerThemeData(
        shape: XinYuShapes.panel,
        hourMinuteShape: XinYuShapes.field,
        dayPeriodShape: XinYuShapes.pill,
      ),
      snackBarTheme: const SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        shape: XinYuShapes.card,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0x60ffffff),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 15,
        ),
        border: OutlineInputBorder(
          borderRadius: XinYuShapes.fieldCorners,
          borderSide: const BorderSide(color: Color(0xcaffffff)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: XinYuShapes.fieldCorners,
          borderSide: const BorderSide(color: Color(0xcaffffff)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: XinYuShapes.fieldCorners,
          borderSide: const BorderSide(color: Color(0xff719887), width: 1.4),
        ),
        labelStyle: const TextStyle(color: XinYuColors.muted, fontSize: 13),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(48, 46),
          shape: XinYuShapes.pill,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(44, 44),
          shape: XinYuShapes.pill,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          minimumSize: const Size(44, 44),
          shape: XinYuShapes.pill,
        ),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(
          minimumSize: const Size(44, 44),
          shape: const CircleBorder(),
        ),
      ),
      scrollbarTheme: ScrollbarThemeData(
        thumbColor: WidgetStateProperty.all(const Color(0x65748a7c)),
        thickness: WidgetStateProperty.all(4),
      ),
    ),
    home: XinYuHome(controller: controller, probe: probe),
  );
}

/// Keep the OS accessibility curve and apply the user's app preference to it.
class _XinYuTextScaler extends TextScaler {
  const _XinYuTextScaler(this.system, this.factor);
  final TextScaler system;
  final double factor;
  @override
  double scale(double fontSize) => system.scale(fontSize) * factor;
  @override
  double get textScaleFactor => system.scale(14) / 14 * factor;
  @override
  bool operator ==(Object other) =>
      other is _XinYuTextScaler &&
      other.system == system &&
      other.factor == factor;
  @override
  int get hashCode => Object.hash(system, factor);
}

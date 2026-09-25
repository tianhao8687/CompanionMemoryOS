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
        final scale = switch (controller.settings['font_size']) {
          'large' => 1.12,
          'extra_large' => 1.24,
          _ => 1.0,
        };
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
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0x60ffffff),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 15,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: Color(0xcaffffff)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: Color(0xcaffffff)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: Color(0xff719887), width: 1.4),
        ),
        labelStyle: const TextStyle(color: XinYuColors.muted, fontSize: 13),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(48, 46),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(15),
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(minimumSize: const Size(44, 44)),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(minimumSize: const Size(44, 44)),
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

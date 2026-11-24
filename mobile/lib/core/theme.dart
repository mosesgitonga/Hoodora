import 'package:flutter/material.dart';

/// One set of the app's colours, for light or dark.
class PaletteColors {
  const PaletteColors({
    required this.primary,
    required this.primaryDark,
    required this.glow,
    required this.glowTint,
    required this.ink,
    required this.inkSoft,
    required this.muted,
    required this.cream,
    required this.sand,
    required this.line,
    required this.lineStrong,
    required this.trust,
    required this.trustInk,
    required this.trustTint,
    required this.danger,
    required this.surface,
    required this.alertTint,
    required this.alertInk,
    required this.foundTint,
    required this.foundInk,
    required this.recommendTint,
    required this.recommendInk,
  });

  final Color primary;
  final Color primaryDark;
  final Color glow;
  final Color glowTint;
  final Color ink;
  final Color inkSoft;
  final Color muted;
  final Color cream;
  final Color sand;
  final Color line;
  final Color lineStrong;
  final Color trust;
  final Color trustInk;
  final Color trustTint;
  final Color danger;
  final Color surface;

  /// Post category chips (Alert, Lost & found, Recommendation), so the urgent
  /// ones stand out; Question uses the trust colours (decision U.4).
  final Color alertTint;
  final Color alertInk;
  final Color foundTint;
  final Color foundInk;
  final Color recommendTint;
  final Color recommendInk;

  /// Hoodora's palette, from the app icon: its orange, navy and cream. Buttons
  /// and links use a deeper orange than the icon's #E8480C, so white text on
  /// them, and they on cream, stay above 4.5:1 contrast.
  static const light = PaletteColors(
    primary: Color(0xFFCC3D0A),
    primaryDark: Color(0xFFA3310A),
    glow: Color(0xFFFF7A1A),
    glowTint: Color(0xFFFFE7D6),
    ink: Color(0xFF1E1B3A),
    inkSoft: Color(0xFF3A3756),
    muted: Color(0xFF5B5872),
    cream: Color(0xFFFFF8F2),
    sand: Color(0xFFF6EADF),
    line: Color(0xFFF1E5DA),
    lineStrong: Color(0xFFE1CFC0),
    trust: Color(0xFF0E7C70),
    trustInk: Color(0xFF0B6158),
    trustTint: Color(0xFFE3F4F1),
    danger: Color(0xFFB42318),
    surface: Color(0xFFFFFFFF),
    alertTint: Color(0xFFFDE2D5),
    alertInk: Color(0xFF8A2A06),
    foundTint: Color(0xFFDCE8F7),
    foundInk: Color(0xFF163E6C),
    recommendTint: Color(0xFFFBE7B5),
    recommendInk: Color(0xFF5C3D00),
  );

  /// At night: the icon's navy, deepened, instead of cream; the orange a shade
  /// brighter so it still reads; text a soft off-white.
  static const dark = PaletteColors(
    primary: Color(0xFFF0642A),
    primaryDark: Color(0xFFFF9A66),
    glow: Color(0xFFFF7A1A),
    glowTint: Color(0xFF3A2418),
    ink: Color(0xFFF3EFF7),
    inkSoft: Color(0xFFD8D3E2),
    muted: Color(0xFFA6A2B8),
    cream: Color(0xFF13111F),
    sand: Color(0xFF26223A),
    line: Color(0xFF2C2842),
    lineStrong: Color(0xFF443E5E),
    trust: Color(0xFF43B9A9),
    trustInk: Color(0xFF8DDCD0),
    trustTint: Color(0xFF142F33),
    danger: Color(0xFFF0705F),
    surface: Color(0xFF1D1A2E),
    alertTint: Color(0xFF3D1F14),
    alertInk: Color(0xFFFFB59A),
    foundTint: Color(0xFF172A42),
    foundInk: Color(0xFFA9C8F0),
    recommendTint: Color(0xFF3A2E10),
    recommendInk: Color(0xFFF2D58A),
  );

  static PaletteColors of(Brightness brightness) => brightness == Brightness.dark ? dark : light;
}

/// The colours in use now, light or dark. Set by the app from the theme's
/// brightness before anything below it builds (see `MyRadiusApp`).
class Palette {
  const Palette._();

  static PaletteColors _current = PaletteColors.light;

  static void use(Brightness brightness) => _current = PaletteColors.of(brightness);

  static bool get isDark => identical(_current, PaletteColors.dark);

  static Color get primary => _current.primary;
  static Color get primaryDark => _current.primaryDark;
  static Color get glow => _current.glow;
  static Color get glowTint => _current.glowTint;
  static Color get ink => _current.ink;
  static Color get inkSoft => _current.inkSoft;
  static Color get muted => _current.muted;
  static Color get cream => _current.cream;
  static Color get sand => _current.sand;
  static Color get line => _current.line;
  static Color get lineStrong => _current.lineStrong;
  static Color get trust => _current.trust;
  static Color get trustInk => _current.trustInk;
  static Color get trustTint => _current.trustTint;
  static Color get danger => _current.danger;
  static Color get alertTint => _current.alertTint;
  static Color get alertInk => _current.alertInk;
  static Color get foundTint => _current.foundTint;
  static Color get foundInk => _current.foundInk;
  static Color get recommendTint => _current.recommendTint;
  static Color get recommendInk => _current.recommendInk;

  /// Cards, sheets and fields: white by day, a raised navy at night.
  static Color get surface => _current.surface;

  /// Text and icons on the brand colour or over a photo: white in both modes.
  static const onPrimary = Color(0xFFFFFFFF);

  /// The fill of a selected chip or segment: the daytime orange in both modes,
  /// with white text on it at 5.1:1. The night orange is brighter so it reads on
  /// navy, which leaves white text on it near 3:1 (decision U.4).
  static const selectedFill = Color(0xFFCC3D0A);
}

/// Both typefaces are variable fonts. Flutter does not map `fontWeight` onto a
/// variable font's weight axis by itself, so every style sets the axis too.
TextStyle _figtree(double size, FontWeight weight, {double? height, Color? color}) {
  return TextStyle(
    fontFamily: 'Figtree',
    fontSize: size,
    fontWeight: weight,
    fontVariations: [FontVariation.weight(weight.value.toDouble())],
    height: height,
    color: color,
  );
}

TextStyle _display(double size, Color color, {double letterSpacing = -0.4}) {
  return TextStyle(
    fontFamily: 'Bricolage Grotesque',
    fontSize: size,
    fontWeight: FontWeight.w700,
    fontVariations: const [FontVariation.weight(700)],
    letterSpacing: letterSpacing,
    height: 1.12,
    color: color,
  );
}

ThemeData buildTheme([Brightness brightness = Brightness.light]) {
  final p = PaletteColors.of(brightness);
  final scheme = ColorScheme(
    brightness: brightness,
    primary: p.primary,
    onPrimary: Palette.onPrimary,
    primaryContainer: p.glowTint,
    onPrimaryContainer: p.primaryDark,
    secondary: p.trust,
    onSecondary: Palette.onPrimary,
    secondaryContainer: p.trustTint,
    onSecondaryContainer: p.trustInk,
    error: p.danger,
    onError: Palette.onPrimary,
    surface: p.cream,
    onSurface: p.ink,
    onSurfaceVariant: p.muted,
    surfaceContainerLowest: p.surface,
    surfaceContainerHighest: p.sand,
    outline: p.lineStrong,
    outlineVariant: p.line,
  );

  final textTheme = TextTheme(
    displaySmall: _display(34, p.ink),
    headlineMedium: _display(30, p.ink),
    headlineSmall: _display(26, p.ink),
    titleLarge: _display(22, p.ink, letterSpacing: -0.2),
    titleMedium: _figtree(17, FontWeight.w600, color: p.ink),
    titleSmall: _figtree(15, FontWeight.w600, color: p.ink),
    bodyLarge: _figtree(16, FontWeight.w400, height: 1.5, color: p.ink),
    bodyMedium: _figtree(15, FontWeight.w400, height: 1.45, color: p.ink),
    bodySmall: _figtree(13, FontWeight.w400, height: 1.45, color: p.muted),
    labelLarge: _figtree(16, FontWeight.w600),
    labelMedium: _figtree(14, FontWeight.w500),
    labelSmall: _figtree(12, FontWeight.w500, color: p.muted),
  );

  final rounded = RoundedRectangleBorder(borderRadius: BorderRadius.circular(14));

  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: p.cream,
    fontFamily: 'Figtree',
    textTheme: textTheme,
    // Selected chips and segments: orange with white text, the rest outlined, in
    // both modes. Without these, Material's default teal and the market's own
    // ink fill (near-white at night, under white text) took over (decision U.4).
    chipTheme: ChipThemeData(
      selectedColor: Palette.selectedFill,
      backgroundColor: p.surface,
      checkmarkColor: Palette.onPrimary,
      showCheckmark: false,
      labelStyle: WidgetStateTextStyle.resolveWith(
        (states) => _figtree(
          14,
          FontWeight.w500,
          color: states.contains(WidgetState.selected) ? Palette.onPrimary : p.ink,
        ),
      ),
      side: WidgetStateBorderSide.resolveWith(
        (states) => BorderSide(color: states.contains(WidgetState.selected) ? Palette.selectedFill : p.lineStrong),
      ),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: ButtonStyle(
        backgroundColor: WidgetStateProperty.resolveWith(
          (states) => states.contains(WidgetState.selected) ? Palette.selectedFill : p.surface,
        ),
        foregroundColor: WidgetStateProperty.resolveWith(
          (states) => states.contains(WidgetState.selected) ? Palette.onPrimary : p.ink,
        ),
        side: WidgetStatePropertyAll(BorderSide(color: p.lineStrong)),
      ),
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: p.cream,
      foregroundColor: p.ink,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: _figtree(17, FontWeight.w600, color: p.ink),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size.fromHeight(56),
        backgroundColor: p.primary,
        foregroundColor: Palette.onPrimary,
        disabledBackgroundColor: p.lineStrong,
        disabledForegroundColor: Palette.onPrimary,
        textStyle: _figtree(17, FontWeight.w600),
        shape: rounded,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size.fromHeight(52),
        foregroundColor: p.ink,
        side: BorderSide(color: p.lineStrong, width: 1.5),
        textStyle: _figtree(16, FontWeight.w600),
        shape: rounded,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: p.primary,
        textStyle: _figtree(15, FontWeight.w600),
        minimumSize: const Size(44, 44),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: p.surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      hintStyle: _figtree(16, FontWeight.w400, color: p.muted),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: BorderSide(color: p.lineStrong, width: 1.5),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: BorderSide(color: p.lineStrong, width: 1.5),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: BorderSide(color: p.primary, width: 2),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: BorderSide(color: p.danger, width: 1.5),
      ),
    ),
    checkboxTheme: CheckboxThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(5)),
      side: BorderSide(color: p.lineStrong, width: 1.5),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: p.surface,
      indicatorColor: p.glowTint,
      height: 72,
      labelTextStyle: WidgetStateProperty.resolveWith((states) {
        final selected = states.contains(WidgetState.selected);
        return _figtree(12, selected ? FontWeight.w600 : FontWeight.w500,
            color: selected ? p.primary : p.muted);
      }),
      iconTheme: WidgetStateProperty.resolveWith((states) {
        final selected = states.contains(WidgetState.selected);
        return IconThemeData(color: selected ? p.primary : p.muted);
      }),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: p.ink,
      contentTextStyle: _figtree(14, FontWeight.w500, color: p.cream),
      behavior: SnackBarBehavior.floating,
    ),
  );
}

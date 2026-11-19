import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'theme.dart';

/// Hoodora's mark: a centre dot in a ring of eight neighbours, one of them
/// larger and darker: you, among them. Drawn from the same geometry as the app
/// icon (scripts/make_brand_assets.py), in the brand orange with an ink accent,
/// so it reads on the light and the dark background.
class HoodoraMark extends StatelessWidget {
  const HoodoraMark({super.key, this.size = 36});

  final double size;

  @override
  Widget build(BuildContext context) {
    return SizedBox.square(
      dimension: size,
      child: CustomPaint(painter: _HoodoraMarkPainter(dots: Palette.primary, accent: Palette.ink)),
    );
  }
}

class _HoodoraMarkPainter extends CustomPainter {
  _HoodoraMarkPainter({required this.dots, required this.accent});

  final Color dots;
  final Color accent;

  // In units of the mark's width, as in the icon, enlarged to fill the square.
  static const _ring = 0.372;
  static const _centre = 0.145;
  static const _outer = 0.0717;
  static const _accent = 0.104;

  @override
  void paint(Canvas canvas, Size size) {
    final side = size.shortestSide;
    final centre = size.center(Offset.zero);
    final dot = Paint()..color = dots;
    canvas.drawCircle(centre, _centre * side, dot);
    for (var step = 0; step < 8; step++) {
      final angle = (-90 + step * 45) * math.pi / 180;
      final at = centre + Offset(math.cos(angle), math.sin(angle)) * (_ring * side);
      final isAccent = step == 1;
      canvas.drawCircle(at, (isAccent ? _accent : _outer) * side, isAccent ? (Paint()..color = accent) : dot);
    }
  }

  @override
  bool shouldRepaint(_HoodoraMarkPainter old) => old.dots != dots || old.accent != accent;
}

/// The mark and the name, as in the logo: lower case, heavy, in ink.
class Wordmark extends StatelessWidget {
  const Wordmark({super.key});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const HoodoraMark(),
        const SizedBox(width: 10),
        Text(
          'hoodora',
          style: Theme.of(context).textTheme.titleLarge?.copyWith(
                color: Palette.ink,
                fontWeight: FontWeight.w800,
                fontVariations: const [FontVariation('wght', 800)],
                letterSpacing: -0.5,
              ),
        ),
      ],
    );
  }
}

/// A full-width button that shows progress while [busy] and ignores taps then.
class BusyButton extends StatelessWidget {
  const BusyButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.busy = false,
  });

  final String label;
  final VoidCallback? onPressed;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    return FilledButton(
      onPressed: busy ? null : onPressed,
      child: busy
          ? const SizedBox.square(
              dimension: 22,
              child: CircularProgressIndicator(strokeWidth: 2.5, color: Palette.onPrimary),
            )
          : Text(label),
    );
  }
}

/// An inline error under a form, in words a person can act on.
class FormError extends StatelessWidget {
  const FormError(this.message, {super.key});

  final String? message;

  @override
  Widget build(BuildContext context) {
    if (message == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.error_outline, size: 18, color: Palette.danger),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message!,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Palette.danger),
            ),
          ),
        ],
      ),
    );
  }
}

/// The verified-neighbour badge.
class NeighbourBadge extends StatelessWidget {
  const NeighbourBadge({super.key, this.long = false});

  final bool long;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
      decoration: BoxDecoration(
        color: Palette.trustTint,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.shield_outlined, size: 13, color: Palette.trustInk),
          const SizedBox(width: 4),
          Flexible(
            child: Text(
              long ? 'Verified neighbour' : 'Neighbour',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context)
                  .textTheme
                  .labelSmall
                  ?.copyWith(color: Palette.trustInk, fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );
  }
}

/// A calm panel with an icon, used for privacy notes and empty states.
class NotePanel extends StatelessWidget {
  const NotePanel({super.key, required this.icon, required this.text, this.tint});

  final IconData icon;
  final String text;

  /// The panel's background; the surface colour when not given.
  final Color? tint;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: tint ?? Palette.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Palette.line),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 22, color: Palette.primary),
          const SizedBox(width: 12),
          Expanded(child: Text(text, style: Theme.of(context).textTheme.bodyMedium)),
        ],
      ),
    );
  }
}

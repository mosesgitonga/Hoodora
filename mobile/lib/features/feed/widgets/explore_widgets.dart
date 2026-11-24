import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/hints.dart';
import '../../../core/location.dart';
import '../../../core/theme.dart';
import '../explore.dart';

/// "Within 15 km of here": everything shown is around where the phone is
/// (decision L.1), which is home only when the phone is at home (decision U.4).
String reachLabel(double km) => 'Within ${kmLabel(km)} km of here';

/// "15", or "2.5": a radius as people read it.
String kmLabel(double km) => km == km.roundToDouble() ? km.toStringAsFixed(0) : km.toStringAsFixed(1);

/// "near Gatitu", beside the Home title: roughly where the phone is (decision
/// L.4). Tapping it says how rough, and that only this person sees it.
class NearChip extends StatelessWidget {
  const NearChip({super.key, required this.place});

  final NearPlace place;

  void _explain(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final ward = place.ward;
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: Palette.cream,
      builder: (sheet) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 20, 20, 12),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Near ${place.name}', style: text.titleLarge),
              if (ward != null && ward != place.name) ...[
                const SizedBox(height: 2),
                Text('$ward ward', style: text.bodyMedium?.copyWith(color: Palette.muted)),
              ],
              const SizedBox(height: 12),
              Text(
                "Roughly where your phone is, from the hexagon it's in, a few hundred "
                'metres across. Near a boundary it may name the place next door.',
                style: text.bodyMedium,
              ),
              const SizedBox(height: 8),
              Text("Only you see this, and it isn't saved.", style: text.bodyMedium),
              const SizedBox(height: 12),
              Text(
                'Place names: © OpenStreetMap contributors, GeoNames, OCHA and geoBoundaries.',
                style: text.bodySmall?.copyWith(color: Palette.muted),
              ),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(onPressed: () => Navigator.of(sheet).pop(), child: const Text('OK')),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final style = Theme.of(context).textTheme.labelMedium?.copyWith(color: Palette.inkSoft);
    return Semantics(
      button: true,
      label: 'Roughly where you are: near ${place.name}',
      excludeSemantics: true,
      child: Material(
        color: Palette.sand,
        shape: const StadiumBorder(),
        child: InkWell(
          customBorder: const StadiumBorder(),
          onTap: () => _explain(context),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(8, 4, 10, 4),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.place_outlined, size: 14, color: Palette.primary),
                const SizedBox(width: 3),
                Flexible(
                  child: Text('near ${place.name}', maxLines: 1, overflow: TextOverflow.ellipsis, style: style),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// The radius line: what's shown, and the Update location button beside it
/// (decision U.4). A Wrap, so with large text or a narrow phone the button
/// moves under the text rather than overflowing.
class ReachLine extends StatelessWidget {
  const ReachLine({super.key, required this.info});

  /// The reach, and anything that goes with it, such as the market's order.
  final Widget info;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      alignment: WrapAlignment.spaceBetween,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [info, const LocateButton()],
    );
  }
}

/// Reads GPS now and shows the feed, the market, and services and jobs from
/// where the phone is. The app does this by itself when it opens; this is for
/// someone who has just moved, or turned location on.
class LocateButton extends ConsumerStatefulWidget {
  const LocateButton({super.key});

  @override
  ConsumerState<LocateButton> createState() => _LocateButtonState();
}

class _LocateButtonState extends ConsumerState<LocateButton> {
  bool _busy = false;

  /// The first tap says what the button does (decision U.4), then carries on.
  Future<void> _tap() async {
    if (!ref.read(hintsProvider).contains(Hint.updateLocation)) {
      ref.read(hintsProvider.notifier).mark(Hint.updateLocation);
      final go = await showModalBottomSheet<bool>(
        context: context,
        backgroundColor: Palette.cream,
        builder: (sheet) => SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 12),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Update location', style: Theme.of(sheet).textTheme.titleLarge),
                const SizedBox(height: 10),
                const Text(
                  'Home, the market, and services and jobs show what is around where your phone is. '
                  'The app checks when you open it. Tap this after you move to see what is around you now.',
                ),
                const SizedBox(height: 12),
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    TextButton(onPressed: () => Navigator.of(sheet).pop(false), child: const Text('Not now')),
                    const SizedBox(width: 8),
                    FilledButton(
                      onPressed: () => Navigator.of(sheet).pop(true),
                      style: FilledButton.styleFrom(minimumSize: const Size(0, 40)),
                      child: const Text('Update now'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      );
      if (go != true || !mounted) return;
    }
    await _locate();
  }

  Future<void> _locate() async {
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(exploreProvider.notifier).fromHere();
      messenger.showSnackBar(const SnackBar(content: Text("Showing what's around you now.")));
    } on LocationProblem catch (problem) {
      messenger.showSnackBar(SnackBar(content: Text(problem.message)));
    } on ApiException catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(error.message)));
    } catch (_) {
      messenger.showSnackBar(const SnackBar(content: Text("Couldn't read your location. Try again.")));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    // Labelled, because the crosshair alone read as "recentre the map"
    // (decision U.4). Compact, to sit on the radius line.
    return TextButton.icon(
      onPressed: _busy ? null : _tap,
      style: TextButton.styleFrom(
        foregroundColor: Palette.primary,
        minimumSize: const Size(0, 32),
        padding: const EdgeInsets.symmetric(horizontal: 8),
        visualDensity: VisualDensity.compact,
        textStyle: Theme.of(context).textTheme.labelMedium?.copyWith(fontWeight: FontWeight.w600),
      ),
      icon: _busy
          ? SizedBox.square(dimension: 14, child: CircularProgressIndicator(strokeWidth: 2, color: Palette.primary))
          : const Icon(Icons.my_location_rounded, size: 16),
      label: const Text('Update location', maxLines: 1, overflow: TextOverflow.ellipsis),
    );
  }
}

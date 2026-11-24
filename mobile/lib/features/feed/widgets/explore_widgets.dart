import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/location.dart';
import '../../../core/theme.dart';
import '../explore.dart';

/// "Within 15 km of you": everything shown is around where the phone is
/// (decision L.1).
String reachLabel(double km) {
  final value = km == km.roundToDouble() ? km.toStringAsFixed(0) : km.toStringAsFixed(1);
  return 'Within $value km of you';
}

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
    return IconButton(
      onPressed: _busy ? null : _locate,
      tooltip: 'Update my location',
      color: Palette.ink,
      visualDensity: VisualDensity.compact,
      icon: _busy
          ? SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Palette.primary))
          : const Icon(Icons.my_location_rounded),
    );
  }
}

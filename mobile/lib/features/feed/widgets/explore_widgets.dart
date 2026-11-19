import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/location.dart';
import '../../../core/router.dart';
import '../../../core/theme.dart';
import '../../auth/auth_controller.dart';
import '../explore.dart';

/// Home as words that fit mid-sentence: its name, or "your home area" while it
/// is too quiet to be named.
String homeAreaName(WidgetRef ref) {
  final auth = ref.watch(authControllerProvider);
  final label = auth is AuthSignedIn ? auth.me.areaLabel : null;
  return label == null || label.precision == 'generic' ? 'your home area' : label.label;
}

/// "Within 15 km of home", or "of you" while showing what's around the phone.
String reachLabel(double km, {required bool aroundNow}) {
  final value = km == km.roundToDouble() ? km.toStringAsFixed(0) : km.toStringAsFixed(1);
  return 'Within $value km of ${aroundNow ? 'you' : 'home'}';
}

/// "Use my location now": reads GPS and shows the feed, the market, and
/// services and jobs from where the phone is, whether that's a trip, a visit or
/// home itself.
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
      final outcome = await ref.read(exploreProvider.notifier).fromHere();
      if (outcome == ExploreOutcome.atHome) {
        messenger.showSnackBar(
          const SnackBar(content: Text("You're in your home area, so this is already what's around you.")),
        );
      }
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
      tooltip: 'Use my location now',
      color: Palette.ink,
      visualDensity: VisualDensity.compact,
      icon: _busy
          ? SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Palette.primary))
          : const Icon(Icons.my_location_rounded),
    );
  }
}

/// While the app shows what's around the phone: until when, the way back to the
/// home area, and the way to make this home for good.
class ExploringStrip extends ConsumerWidget {
  const ExploringStrip({super.key, required this.exploring, this.offerMove = true});

  final Exploring exploring;

  /// "Living here now? Move your home": on Home, not on every screen.
  final bool offerMove;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final text = Theme.of(context).textTheme;
    final until = TimeOfDay.fromDateTime(exploring.until).format(context);
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 4, 8),
      decoration: BoxDecoration(color: Palette.glowTint, borderRadius: BorderRadius.circular(12)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.near_me_outlined, size: 18, color: Palette.primaryDark),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  "Showing what's around you now, until $until. What you post still goes to "
                  '${homeAreaName(ref)}.',
                  style: text.bodySmall?.copyWith(color: Palette.ink),
                ),
              ),
              TextButton(
                onPressed: () => ref.read(exploreProvider.notifier).backHome(),
                child: const Text('Show home area'),
              ),
            ],
          ),
          if (offerMove)
            Padding(
              padding: const EdgeInsets.only(left: 26),
              child: InkWell(
                onTap: () => context.go(Routes.moveHome),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Text(
                    'Living here now? Move your home',
                    style: text.bodySmall?.copyWith(color: Palette.primary, fontWeight: FontWeight.w600),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

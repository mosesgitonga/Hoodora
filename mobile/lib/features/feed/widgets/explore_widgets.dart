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

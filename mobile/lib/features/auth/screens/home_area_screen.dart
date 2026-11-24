import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/location.dart';
import '../../../core/providers.dart';
import '../../../core/theme.dart';
import '../../../core/widgets.dart';
import '../auth_controller.dart';

/// The last step of signing up: is the area the phone is in now the person's
/// home area? The app reads the location once and the server keeps only the
/// zone it falls in, never the coordinates (decision L.2).
///
/// - **Yes:** it's their home area. With a verified phone they can post around
///   it straight away.
/// - **No:** they can look around and comment from day one, and post in an area
///   once they've been there on four days of a week. They set their home area
///   later, from Me › Home area.
class HomeAreaScreen extends ConsumerStatefulWidget {
  const HomeAreaScreen({super.key});

  @override
  ConsumerState<HomeAreaScreen> createState() => _HomeAreaScreenState();
}

class _HomeAreaScreenState extends ConsumerState<HomeAreaScreen> {
  bool? _choice;
  String? _error;

  Future<void> _answer({required bool homeArea}) async {
    setState(() {
      _choice = homeArea;
      _error = null;
    });
    try {
      final reading = await ref.read(locationReaderProvider).readHere();
      await ref.read(authRepositoryProvider).setHome(reading, atHome: homeArea);
      await ref.read(authControllerProvider.notifier).refreshMe();
    } on LocationProblem catch (problem) {
      if (mounted) setState(() => _error = problem.message);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _choice = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final busy = _choice != null;
    return Scaffold(
      body: SafeArea(
        // Scrolls when there isn't room (a small phone, or large text), and
        // otherwise keeps the buttons at the bottom.
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(24, 32, 24, 24),
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: constraints.maxHeight - 56),
              child: IntrinsicHeight(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Align(alignment: Alignment.centerLeft, child: HoodoraMark(size: 48)),
                    const SizedBox(height: 20),
                    Text('Is this your home area?', style: text.headlineMedium),
                    const SizedBox(height: 12),
                    Text(
                      'Hoodora shows what is happening around wherever you are. Your home area is '
                      'the one shown on your profile.',
                      style: text.bodyLarge?.copyWith(color: Palette.muted),
                    ),
                    const SizedBox(height: 20),
                    const NotePanel(
                      icon: Icons.shield_outlined,
                      text:
                          "We don't save your exact location. We only keep the zone you're in, "
                          'about 2.5 km across, and neighbours see its name and a rough distance '
                          'like "1–3 km".',
                    ),
                    FormError(_error),
                    const Spacer(),
                    const SizedBox(height: 20),
                    BusyButton(
                      label: 'Yes, this is my home area',
                      busy: _choice == true,
                      onPressed: busy ? null : () => _answer(homeArea: true),
                    ),
                    const SizedBox(height: 10),
                    OutlinedButton(
                      onPressed: busy ? null : () => _answer(homeArea: false),
                      child: _choice == false
                          ? const SizedBox.square(dimension: 22, child: CircularProgressIndicator(strokeWidth: 2.5))
                          : const Text("No, I'm just visiting"),
                    ),
                    const SizedBox(height: 10),
                    Text(
                      "You can make 3 posts straight away, without links. After that, you can post "
                      "in an area once you've been there on 4 days in a week.",
                      textAlign: TextAlign.center,
                      style: text.bodySmall?.copyWith(fontSize: 12),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

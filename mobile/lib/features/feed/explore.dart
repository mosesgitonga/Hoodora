import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../auth/auth_models.dart';

/// Reading the feed from where the phone is now, rather than from home
/// (decision 1.1's explore mode). Only what the person sees moves: home, what
/// others see, and anything they post stay at home. The server holds it for a
/// couple of hours, and so does this.
class Exploring {
  const Exploring({required this.area, required this.until});

  final AreaLabel area;
  final DateTime until;

  bool get active => until.isAfter(DateTime.now());
}

/// What a tap on "Use my location now" found.
enum ExploreOutcome { exploring, atHome }

/// Discarded with the signed-in shell, like the feed, so it never outlives the account.
final exploreProvider = NotifierProvider.autoDispose<ExploreController, Exploring?>(ExploreController.new);

class ExploreController extends Notifier<Exploring?> {
  Timer? _ends;

  @override
  Exploring? build() {
    ref.onDispose(() => _ends?.cancel());
    return null;
  }

  /// Reads GPS, asking for permission if needed, and moves the feed to the
  /// hexagon the phone is in, unless that is still home's. Throws
  /// `LocationProblem` or `ApiException` for the caller to show.
  Future<ExploreOutcome> fromHere() async {
    final reading = await ref.read(locationReaderProvider).readHere();
    final data = Map<String, dynamic>.from(await ref.read(apiClientProvider).post('/me/explore', body: {
      // Coordinates go up once, become a hexagon, and are not kept.
      'latitude': reading.latitude,
      'longitude': reading.longitude,
      'accuracy_metres': reading.accuracyMetres,
    }) as Map);
    if (data['same_area_as_home'] == true) {
      _set(null);
      return ExploreOutcome.atHome;
    }
    _set(Exploring(
      area: AreaLabel.fromJson(Map<String, dynamic>.from(data['area_label'] as Map)),
      until: DateTime.parse(data['expires_at'] as String).toLocal(),
    ));
    return ExploreOutcome.exploring;
  }

  /// Back to the feed around home.
  Future<void> backHome() async {
    _set(null);
    try {
      await ref.read(apiClientProvider).delete('/me/explore');
    } catch (_) {
      // The server's session ends on its own; the app already shows home.
    }
  }

  void _set(Exploring? next) {
    _ends?.cancel();
    state = next;
    if (next != null) {
      // When the server's session lapses, its feed falls back to home: so does this.
      _ends = Timer(next.until.difference(DateTime.now()), () => state = null);
    }
  }
}

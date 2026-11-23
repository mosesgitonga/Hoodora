import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../auth/auth_models.dart';

/// Where the phone is, when that isn't home (decision L.1). The app sends it by
/// itself when it opens and comes back to the foreground, and the feed, the
/// market, services and jobs, and everything posted then follow it. Home stays
/// in the background, for the profile, the badge and People nearby. The server
/// holds the location for a couple of hours, and so does this.
class Exploring {
  const Exploring({required this.area, required this.until});

  final AreaLabel area;
  final DateTime until;

  bool get active => until.isAfter(DateTime.now());
}

/// What reading the location found.
enum ExploreOutcome { exploring, atHome }

/// Discarded with the signed-in shell, like the feed, so it never outlives the account.
final exploreProvider = NotifierProvider.autoDispose<ExploreController, Exploring?>(ExploreController.new);

class ExploreController extends Notifier<Exploring?> {
  /// Opening and leaving the app often doesn't send a location each time.
  static const minInterval = Duration(minutes: 2);

  Timer? _ends;
  DateTime? _lastSent;
  bool _sending = false;

  @override
  Exploring? build() {
    ref.onDispose(() => _ends?.cancel());
    return null;
  }

  /// Sends where the phone is, by itself: at launch and on coming back to the
  /// app. At most once every [minInterval], never asks for permission, and silent
  /// on any failure: the server then reads from home until the next try.
  Future<void> refreshQuietly() async {
    final last = _lastSent;
    if (_sending || (last != null && DateTime.now().difference(last) < minInterval)) return;
    _sending = true;
    try {
      await fromHere(mayAsk: false);
    } catch (_) {
      // No location allowed, no fix, or no connection.
    } finally {
      _sending = false;
    }
  }

  /// Reads GPS and sends it. [mayAsk] asks for permission if needed, as the
  /// location button does. Throws `LocationProblem` or `ApiException` for the
  /// caller to show.
  Future<ExploreOutcome> fromHere({bool mayAsk = true}) async {
    final reading = await ref.read(locationReaderProvider).readHere(mayAsk: mayAsk);
    final data = Map<String, dynamic>.from(await ref.read(apiClientProvider).post('/me/explore', body: {
      // Coordinates go up once, become a hexagon, and are not kept.
      'latitude': reading.latitude,
      'longitude': reading.longitude,
      'accuracy_metres': reading.accuracyMetres,
    }) as Map);
    _lastSent = DateTime.now();
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

  void _set(Exploring? next) {
    _ends?.cancel();
    state = next;
    if (next != null) {
      // When the server's hold lapses, its lists fall back to home: so does
      // this, and it asks again where the phone is.
      _ends = Timer(next.until.difference(DateTime.now()), () {
        state = null;
        _lastSent = null;
        refreshQuietly();
      });
    }
  }
}

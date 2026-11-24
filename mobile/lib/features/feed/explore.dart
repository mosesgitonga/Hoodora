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

/// Roughly where the phone is, "near Gatitu": the named place its hexagon falls
/// in (decision L.4). Shown to the person only, and never saved, by the server
/// or here.
class NearPlace {
  const NearPlace({required this.name, required this.level, this.ward});

  factory NearPlace.fromJson(Map<String, dynamic> json) => NearPlace(
        name: json['name'] as String,
        level: json['level'] as String,
        ward: json['ward'] as String?,
      );

  final String name;

  /// `town`, `village`, `sublocation` or `ward`: how specific [name] is.
  final String level;
  final String? ward;
}

/// The latest [NearPlace], replaced by each reading. Discarded with the signed-in
/// shell, like [exploreProvider].
final nearProvider = NotifierProvider.autoDispose<NearController, NearPlace?>(NearController.new);

class NearController extends Notifier<NearPlace?> {
  Timer? _ends;

  @override
  NearPlace? build() {
    ref.onDispose(() => _ends?.cancel());
    return null;
  }

  /// Shows [place] until [until]: after that it is no longer known where the
  /// phone is, so no name is better than an old one.
  void show(NearPlace? place, {required DateTime until}) {
    _ends?.cancel();
    state = place;
    if (place != null) _ends = Timer(until.difference(DateTime.now()), () => state = null);
  }
}

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
    final until = DateTime.parse(data['expires_at'] as String).toLocal();
    final near = data['near'];
    // At home too: the name is about where the phone is, not about home.
    ref.read(nearProvider.notifier).show(
          near is Map ? NearPlace.fromJson(Map<String, dynamic>.from(near)) : null,
          until: until,
        );
    if (data['same_area_as_home'] == true) {
      _set(null);
      return ExploreOutcome.atHome;
    }
    _set(Exploring(
      area: AreaLabel.fromJson(Map<String, dynamic>.from(data['area_label'] as Map)),
      until: until,
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

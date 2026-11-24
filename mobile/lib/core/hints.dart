import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

/// Hint keys: one-time notes, and small facts about this phone's use of the app.
abstract final class Hint {
  /// The note on what "Update location" does, shown on its first tap.
  static const updateLocation = 'update_location_explained';

  /// This account has posted, this session: the Post button drops its label.
  /// Kept in memory only, never in the file: it names an account, and
  /// per-account state doesn't outlive signing out (decision M.4).
  static String posted(String userId) => 'posted:$userId';

  /// Whether a hint is written to the file, or kept for this session only.
  static bool remembered(String key) => !key.startsWith('posted:');
}

/// Which one-time notes this phone has shown, kept like the theme choice: a tiny
/// file in the app's private folder. No personal data: only the keys of notes
/// shown (see [Hint.remembered]).
abstract class HintsStore {
  Future<Set<String>> load();
  Future<void> save(Set<String> seen);
}

class FileHintsStore implements HintsStore {
  const FileHintsStore();

  Future<File> _file() async => File('${(await getApplicationSupportDirectory()).path}/hints.json');

  @override
  Future<Set<String>> load() async {
    try {
      final file = await _file();
      if (!await file.exists()) return {};
      return {for (final key in (jsonDecode(await file.readAsString()) as List)) key as String};
    } catch (_) {
      return {};
    }
  }

  @override
  Future<void> save(Set<String> seen) async {
    try {
      await (await _file()).writeAsString(jsonEncode(seen.toList()));
    } catch (_) {
      // Not saved: the note may show once more after a restart.
    }
  }
}

class MemoryHintsStore implements HintsStore {
  MemoryHintsStore([Set<String>? seen]) : seen = {...?seen};

  Set<String> seen;

  @override
  Future<Set<String>> load() async => {...seen};

  @override
  Future<void> save(Set<String> next) async => seen = {...next};
}

final hintsStoreProvider = Provider<HintsStore>((ref) => const FileHintsStore());

/// The hints seen so far. Starts empty and fills from the store a moment later.
final hintsProvider = NotifierProvider<HintsController, Set<String>>(HintsController.new);

class HintsController extends Notifier<Set<String>> {
  @override
  Set<String> build() {
    Future.microtask(() async {
      final saved = await ref.read(hintsStoreProvider).load();
      if (saved.isNotEmpty) state = {...state, ...saved};
    });
    return const {};
  }

  /// Takes effect at once; the file is written in the background, since nothing
  /// should wait on a hint being saved.
  void mark(String key) {
    if (state.contains(key)) return;
    state = {...state, key};
    if (Hint.remembered(key)) {
      unawaited(ref.read(hintsStoreProvider).save({for (final k in state) if (Hint.remembered(k)) k}));
    }
  }
}

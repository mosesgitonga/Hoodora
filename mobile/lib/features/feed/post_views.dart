import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../auth/auth_controller.dart';

/// Tells the server which posts appeared on screen, so their view counts
/// include this person (decision F.1). At most once per post per account per
/// run of the app: the server counts each person once per post anyway, so
/// repeats would only cost data.
///
/// Batched: a post seen starts a short wait, and everything seen meanwhile goes
/// with it. Ten waiting go at once. Whatever is left goes when the app is put in
/// the background.
///
/// Best effort: a failed report is dropped. A view count is a nudge, not a
/// record, and retrying would cost data on an expensive connection. The server
/// also counts a vote, reaction or comment as a view, so a post never shows
/// more people acting on it than seeing it.
class PostViewReporter {
  PostViewReporter(this._send, {this.wait = const Duration(seconds: 3)}) {
    _lifecycle = AppLifecycleListener(onHide: () => unawaited(_flush()));
  }

  /// Sends a batch of post IDs to the server.
  final Future<void> Function(List<String> postIds) _send;
  final Duration wait;
  late final AppLifecycleListener _lifecycle;
  final _reported = <String>{};
  final _pending = <String>{};
  Timer? _timer;
  bool _flushQueued = false;
  bool _disposed = false;

  static const _enough = 10;
  static const _batch = 50;

  void seen(String postId) {
    if (_disposed || !_reported.add(postId)) return;
    _pending.add(postId);
    if (_pending.length >= _enough) {
      if (_flushQueued) return;
      _flushQueued = true;
      // Cards report themselves after the frame that built them, one after the
      // other; a microtask runs once they all have, so they go in one report.
      scheduleMicrotask(() {
        _flushQueued = false;
        unawaited(_flush());
      });
    } else {
      _timer ??= Timer(wait, () => unawaited(_flush()));
    }
  }

  Future<void> _flush() async {
    _timer?.cancel();
    _timer = null;
    if (_disposed || _pending.isEmpty) return;
    final batch = _pending.take(_batch).toList();
    _pending.removeAll(batch);
    if (_pending.isNotEmpty) _timer = Timer(wait, () => unawaited(_flush()));
    try {
      await _send(batch);
    } catch (error) {
      debugPrint('post_views_not_reported: $error');
    }
  }

  void dispose() {
    _disposed = true;
    _timer?.cancel();
    _timer = null;
    _lifecycle.dispose();
  }
}

/// The signed-in account, or null. The reporter starts afresh for each account:
/// a post one account has seen is still unseen by the next one on this phone.
String? _accountId(AuthState auth) => switch (auth) {
      AuthSignedIn(:final me) => me.id,
      AuthNeedsHome(:final me) => me.id,
      _ => null,
    };

final postViewReporterProvider = Provider<PostViewReporter>((ref) {
  ref.watch(authControllerProvider.select(_accountId));
  final reporter = PostViewReporter(ref.watch(feedRepositoryProvider).reportViews);
  ref.onDispose(reporter.dispose);
  return reporter;
});

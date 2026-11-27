import 'dart:async';

import 'package:flutter/scheduler.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import 'feed_repository.dart';

/// Tells the server which posts appeared on screen, so their view counts
/// include this person (decision F.1). At most once per post per run of the
/// app: the server counts each person once per post anyway, so repeats would
/// only cost data.
///
/// Batched without timers: the cards seen in one frame wait together, and go
/// once ten are waiting or five seconds have passed since the last report.
/// Whatever is left goes when the app is put in the background.
///
/// Best effort: a failed report is dropped. A view count is a nudge, not a
/// record, and retrying would cost data on an expensive connection.
class PostViewReporter {
  PostViewReporter(this._repository) {
    _lifecycle = AppLifecycleListener(onHide: () => unawaited(_flush()));
  }

  final FeedRepository _repository;
  late final AppLifecycleListener _lifecycle;
  final _reported = <String>{};
  final _pending = <String>{};
  bool _scheduled = false;
  /// Counted from the start, so opening the app sends nothing at once.
  DateTime _lastReport = DateTime.now();

  static const _wait = Duration(seconds: 5);
  static const _enough = 10;
  static const _batch = 50;

  void seen(String postId) {
    if (!_reported.add(postId)) return;
    _pending.add(postId);
    if (_scheduled) return;
    _scheduled = true;
    // After this frame, so every card built in it goes in one report.
    SchedulerBinding.instance.addPostFrameCallback((_) {
      _scheduled = false;
      if (_pending.length >= _enough || DateTime.now().difference(_lastReport) >= _wait) {
        unawaited(_flush());
      }
    });
  }

  Future<void> _flush() async {
    if (_pending.isEmpty) return;
    final batch = _pending.take(_batch).toList();
    _pending.removeAll(batch);
    _lastReport = DateTime.now();
    try {
      await _repository.reportViews(batch);
    } catch (error) {
      debugPrint('post_views_not_reported: $error');
    }
  }

  void dispose() => _lifecycle.dispose();
}

final postViewReporterProvider = Provider<PostViewReporter>((ref) {
  final reporter = PostViewReporter(ref.watch(feedRepositoryProvider));
  ref.onDispose(reporter.dispose);
  return reporter;
});

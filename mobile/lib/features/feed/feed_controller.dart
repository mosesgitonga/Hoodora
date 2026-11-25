import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/providers.dart';
import 'explore.dart';
import 'feed_models.dart';

class FeedState {
  const FeedState({
    this.posts = const [],
    this.nextCursor,
    this.radiusKm,
    this.recentPostDays,
    this.loading = true,
    this.loadingMore = false,
    this.error,
  });

  final List<Post> posts;
  final String? nextCursor;
  final double? radiusKm;

  /// Days that count as recent, from the first page (see [FeedPage]).
  final int? recentPostDays;
  final bool loading;
  final bool loadingMore;
  final ApiException? error;

  bool get hasMore => nextCursor != null;

  FeedState copyWith({
    List<Post>? posts,
    String? nextCursor,
    bool clearCursor = false,
    double? radiusKm,
    bool? loading,
    bool? loadingMore,
    ApiException? error,
    bool clearError = false,
  }) {
    return FeedState(
      posts: posts ?? this.posts,
      nextCursor: clearCursor ? null : (nextCursor ?? this.nextCursor),
      radiusKm: radiusKm ?? this.radiusKm,
      // Kept: set by a first page, which builds a new state.
      recentPostDays: recentPostDays,
      loading: loading ?? this.loading,
      loadingMore: loadingMore ?? this.loadingMore,
      error: clearError ? null : (error ?? this.error),
    );
  }
}

/// Discarded with the signed-in shell, so the next account starts afresh.
final feedControllerProvider = NotifierProvider.autoDispose<FeedController, FeedState>(FeedController.new);

/// The neighbourhood feed: first page, more on scroll, pull to refresh, and
/// local updates when the person reacts, comments or posts.
class FeedController extends Notifier<FeedState> {
  @override
  FeedState build() {
    // Moving the feed to where the phone is, or back home, reloads it.
    ref.listen(exploreProvider, (was, now) {
      if ((was == null) != (now == null) || was?.area.label != now?.area.label) refresh();
    });
    Future.microtask(refresh);
    return const FeedState();
  }

  bool get _exploring => ref.read(exploreProvider)?.active ?? false;

  /// Each load gets a number; an answer to an older one is dropped, so switching
  /// between around-you-now and home never shows the other place's posts.
  int _generation = 0;

  Future<void> refresh() async {
    // Nothing is watching any more (the screen that read it has gone).
    if (!ref.mounted) return;
    final generation = ++_generation;
    state = state.copyWith(loading: true, clearError: true);
    try {
      final page = await ref.read(feedRepositoryProvider).feed(exploring: _exploring);
      if (!ref.mounted || generation != _generation) return;
      state = FeedState(
        posts: page.items,
        nextCursor: page.nextCursor,
        radiusKm: page.radiusKm,
        recentPostDays: page.recentPostDays,
        loading: false,
      );
    } on ApiException catch (error) {
      if (ref.mounted && generation == _generation) state = state.copyWith(loading: false, error: error);
    }
  }

  Future<void> loadMore() async {
    if (!state.hasMore || state.loadingMore || state.loading) return;
    final generation = _generation;
    state = state.copyWith(loadingMore: true);
    try {
      final page = await ref.read(feedRepositoryProvider).feed(cursor: state.nextCursor, exploring: _exploring);
      // A reload started meanwhile: this page belongs to the list it replaced.
      if (!ref.mounted || generation != _generation) return;
      final seen = {for (final post in state.posts) post.id};
      state = state.copyWith(
        posts: [...state.posts, ...page.items.where((post) => !seen.contains(post.id))],
        nextCursor: page.nextCursor,
        clearCursor: page.nextCursor == null,
        loadingMore: false,
      );
    } on ApiException catch (error) {
      state = state.copyWith(loadingMore: false, error: error);
    }
  }

  /// Reacts to a post with the one reaction its category offers, or takes it
  /// back. Shown at once and put back if the server refuses (decision U.3).
  Future<void> toggleReaction(String postId) async {
    final post = state.posts.where((p) => p.id == postId).firstOrNull;
    if (post == null) return;
    final on = post.myReaction != null;
    _replace(on
        ? post.copyWith(clearReaction: true, reactionCount: post.reactionCount - 1)
        : post.copyWith(myReaction: reactionKindFor(post.category), reactionCount: post.reactionCount + 1));
    try {
      final repo = ref.read(feedRepositoryProvider);
      if (on) {
        await repo.unreact(postId);
      } else {
        final count = await repo.react(postId, reactionKindFor(post.category));
        final current = state.posts.where((p) => p.id == postId).firstOrNull;
        if (current != null) _replace(current.copyWith(reactionCount: count));
      }
    } on ApiException {
      _replace(post);
      rethrow;
    }
  }

  void replace(Post post) => _replace(post);

  void prepend(Post post) =>
      state = state.copyWith(posts: [post, ...state.posts.where((p) => p.id != post.id)]);

  void commentAdded(String postId) {
    final post = state.posts.where((p) => p.id == postId).firstOrNull;
    if (post != null) _replace(post.copyWith(commentCount: post.commentCount + 1));
  }

  void commentRemoved(String postId) {
    final post = state.posts.where((p) => p.id == postId).firstOrNull;
    if (post != null && post.commentCount > 0) _replace(post.copyWith(commentCount: post.commentCount - 1));
  }

  /// After the author edits a post: shown as the server now has it.
  void edited(Post post) => _replace(post);

  /// After the author deletes a post.
  void removed(String postId) => state = state.copyWith(posts: [...state.posts.where((p) => p.id != postId)]);

  void _replace(Post post) {
    state = state.copyWith(posts: [for (final p in state.posts) p.id == post.id ? post : p]);
  }
}

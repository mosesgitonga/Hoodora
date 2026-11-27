import 'package:myradius/features/feed/post_views.dart';

/// A view reporter that reports nothing, for tests that aren't about views.
///
/// The real one waits a few seconds before sending, and a test whose provider
/// container is disposed in tear-down would end with that wait still pending.
class NoViews extends PostViewReporter {
  NoViews() : super((_) async {});

  @override
  void seen(String postId) {}
}

final noViews = postViewReporterProvider.overrideWith((ref) {
  final reporter = NoViews();
  ref.onDispose(reporter.dispose);
  return reporter;
});

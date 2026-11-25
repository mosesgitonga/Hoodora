import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:myradius/core/api/api_client.dart';
import 'package:myradius/core/api/token_store.dart';
import 'package:myradius/core/hints.dart';
import 'package:myradius/core/offline_store.dart';
import 'package:myradius/core/providers.dart';
import 'package:myradius/core/realtime.dart';
import 'package:myradius/core/theme.dart';
import 'package:myradius/features/feed/feed_models.dart';
import 'package:myradius/features/feed/widgets/post_card.dart';
import 'package:myradius/main.dart';

import 'feed_test.dart' show feedJson, postJson;
import 'me_test.dart' show meJson;
import 'support/fake_adapter.dart';
import 'support/fake_location.dart';
import 'support/fake_socket.dart';

/// Decision T.2 in the app: where the older posts begin, what a stale alert
/// looks like, and the prompt when nothing near is recent.
void main() {
  String daysAgo(num days) =>
      DateTime.now().toUtc().subtract(Duration(minutes: (days * 1440).round())).toIso8601String();

  Map<String, dynamic> at(Map<String, dynamic> json, num days, {bool? fresh}) =>
      {...json, 'created_at': daysAgo(days), 'fresh_alert': ?fresh};

  group('the words', () {
    test('a time in full', () {
      final now = DateTime(2026, 11, 25, 12);
      expect(timeAgoInFull(now.subtract(const Duration(minutes: 5)), now: now), '5 minutes ago');
      expect(timeAgoInFull(now.subtract(const Duration(hours: 3)), now: now), '3 hours ago');
      expect(timeAgoInFull(now.subtract(const Duration(days: 1, hours: 2)), now: now), '1 day ago');
      expect(timeAgoInFull(now.subtract(const Duration(days: 5)), now: now), '5 days ago');
      expect(timeAgoInFull(now.subtract(const Duration(days: 23)), now: now), '3 weeks ago');
      expect(timeAgoInFull(now.subtract(const Duration(days: 70)), now: now), '2 months ago');
      expect(timeAgoInFull(now.subtract(const Duration(days: 400)), now: now), '1 year ago');
    });

    test('where the older posts begin', () {
      final now = DateTime.now();
      Post post(String id, int days) => Post.fromJson(at(postJson(id), days));
      final posts = [post('a', 1), post('b', 29), post('c', 31), post('d', 60)];
      expect(firstOlderPost(posts, 30, now: now), 2);
      expect(firstOlderPost(posts.take(2).toList(), 30, now: now), isNull);
      expect(firstOlderPost(posts.skip(2).toList(), 30, now: now), 0);
      // An older server sends no window: no divider at all.
      expect(firstOlderPost(posts, null, now: now), isNull);
    });
  });

  // --------------------------------------------------------------------------
  // A stale alert
  // --------------------------------------------------------------------------
  Future<void> card(WidgetTester tester, Map<String, dynamic> json) async {
    Palette.use(Brightness.light);
    await tester.pumpWidget(MaterialApp(
      theme: buildTheme(),
      home: Scaffold(body: SingleChildScrollView(child: PostCard(post: Post.fromJson(json), onReact: () {}))),
    ));
  }

  Color? chipColour(WidgetTester tester, String label) {
    final box = tester.widget<Container>(find.ancestor(of: find.text(label), matching: find.byType(Container)).first);
    return (box.decoration as BoxDecoration?)?.color;
  }

  group('an alert', () {
    testWidgets('while fresh, keeps its colour and its brief time', (tester) async {
      await card(tester, at(postJson('p1', category: 'alert'), 0.5, fresh: true));
      expect(chipColour(tester, 'Alert'), Palette.alertTint);
      expect(find.textContaining('ago'), findsNothing);
    });

    testWidgets('past its days, goes neutral and says how old it is', (tester) async {
      await card(tester, at(postJson('p1', category: 'alert'), 23, fresh: false));
      expect(find.text('Alert'), findsOneWidget);
      expect(chipColour(tester, 'Alert'), Palette.sand);
      expect(find.textContaining('3 weeks ago'), findsOneWidget);
    });

    testWidgets('from a server that predates the flag, stays as it was', (tester) async {
      await card(tester, at(postJson('p1', category: 'alert'), 23));
      expect(chipColour(tester, 'Alert'), Palette.alertTint);
      expect(find.textContaining('ago'), findsNothing);
    });

    testWidgets('only alerts go quiet: an old question keeps its chip', (tester) async {
      await card(tester, at(postJson('p1', category: 'question'), 23, fresh: false));
      expect(chipColour(tester, 'Question'), Palette.trustTint);
    });
  });

  // --------------------------------------------------------------------------
  // The feed
  // --------------------------------------------------------------------------
  late List<Map<String, dynamic>> feed;
  int? recentDays;

  Future<void> open(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    final store = MemoryTokenStore()..refreshToken = 'r1';
    final me = {...meJson(), 'starter_posts_left': 3};
    final adapter = FakeAdapter((request) {
      return switch ((request.method, request.path)) {
        ('POST', '/auth/refresh') => FakeReply(200, tokens('a1', 'r2')),
        ('GET', '/me') => FakeReply(200, me),
        ('GET', '/feed') => FakeReply(200, {...feedJson(feed), 'recent_post_days': ?recentDays}),
        ('GET', '/conversations') => const FakeReply(200, {'items': <Object>[], 'next_cursor': null}),
        _ => FakeReply(404, errorBody('not_found', 'Resource not found')),
      };
    });
    final api = ApiClient(store: store, dio: fakeDio(adapter));
    await tester.pumpWidget(ProviderScope(
      overrides: [
        tokenStoreProvider.overrideWithValue(store),
        apiClientProvider.overrideWithValue(api),
        offlineStoreProvider.overrideWithValue(MemoryOfflineStore()),
        locationReaderProvider.overrideWithValue(const FakeReader.none()),
        hintsStoreProvider.overrideWithValue(MemoryHintsStore()),
        realtimeProvider.overrideWith((ref) {
          final client = RealtimeClient(api, connect: FakeSockets().connect, uri: Uri.parse('ws://api.test/v1/ws'));
          ref.onDispose(client.dispose);
          return client;
        }),
      ],
      child: const MyRadiusApp(),
    ));
    await tester.pumpAndSettle();
  }

  setUp(() => recentDays = 30);

  group('the feed', () {
    testWidgets('marks where the older posts begin, once', (tester) async {
      feed = [
        at(postJson('p1', body: 'Water back on today', category: 'general'), 2),
        at(postJson('p2', body: 'Matatu stage moved', category: 'general'), 40),
        at(postJson('p3', body: 'Lost a black umbrella', category: 'general'), 50),
      ];
      await open(tester);

      expect(find.text('Older posts'), findsOneWidget);
      final divider = tester.getTopLeft(find.text('Older posts')).dy;
      expect(tester.getTopLeft(find.text('Water back on today')).dy, lessThan(divider));
      expect(tester.getTopLeft(find.text('Matatu stage moved')).dy, greaterThan(divider));
      // Something recent is there, so the prompt waits at the end as before.
      expect(find.text('Nothing new around here lately'), findsNothing);
    });

    testWidgets('has no divider when every post is recent', (tester) async {
      feed = [at(postJson('p1', category: 'general'), 2), at(postJson('p2', category: 'general'), 10)];
      await open(tester);
      expect(find.text('Older posts'), findsNothing);
    });

    testWidgets('has no divider from a server that does not say the window', (tester) async {
      recentDays = null;
      feed = [at(postJson('p1', category: 'general'), 2), at(postJson('p2', category: 'general'), 40)];
      await open(tester);
      expect(find.text('Older posts'), findsNothing);
    });

    testWidgets('with nothing recent, asks a question at the top, not the bottom', (tester) async {
      feed = [
        at(postJson('p1', body: 'Matatu stage moved', category: 'general'), 40),
        at(postJson('p2', body: 'Lost a black umbrella', category: 'general'), 50),
      ];
      await open(tester);

      expect(find.text('Nothing new around here lately'), findsOneWidget);
      final ask = find.text('Ask your neighbours something');
      expect(ask, findsOneWidget);
      expect(tester.getTopLeft(ask).dy, lessThan(tester.getTopLeft(find.text('Older posts')).dy));
      expect(tester.getTopLeft(find.text('Older posts')).dy, lessThan(tester.getTopLeft(find.text('Matatu stage moved')).dy));

      await tester.tap(ask);
      await tester.pumpAndSettle();
      expect(tester.widget<ChoiceChip>(find.widgetWithText(ChoiceChip, 'Question')).selected, isTrue);
    });
  });
}

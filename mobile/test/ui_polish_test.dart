import 'package:dio/dio.dart' show RequestOptions;
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
import 'me_test.dart' show meJson, profileJson;
import 'support/fake_adapter.dart';
import 'support/fake_location.dart';
import 'support/fake_socket.dart';

/// The UI polish brief (decisions U.3 and U.4): the meta line, counts, reactions by
/// category, chips, the shortcut row, the Post button, empty states and trust signals.
void main() {
  // --------------------------------------------------------------------------
  // A post card on its own
  // --------------------------------------------------------------------------
  Future<void> card(WidgetTester tester, Map<String, dynamic> json) async {
    Palette.use(Brightness.light);
    await tester.pumpWidget(MaterialApp(
      theme: buildTheme(),
      home: Scaffold(body: SingleChildScrollView(child: PostCard(post: Post.fromJson(json), onReact: () {}))),
    ));
  }

  Map<String, dynamic> withArea(Map<String, dynamic> json, String label, String precision, String bucket) =>
      {...json, 'area_label': {'label': label, 'precision': precision}, 'distance_bucket': bucket};

  group('the meta line', () {
    testWidgets('leaves out the fallback label, since the band says as much', (tester) async {
      await card(tester, withArea(postJson('p1'), 'nearby', 'generic', '3_10km'));
      expect(find.textContaining('nearby'), findsNothing);
      expect(find.textContaining(RegExp(r'^3–10 km · ')), findsOneWidget);
    });

    testWidgets('keeps a real place name', (tester) async {
      await card(tester, withArea(postJson('p1'), "King'ong'o", 'area', '1_3km'));
      expect(find.textContaining(RegExp(r"^King'ong'o · 1–3 km · ")), findsOneWidget);
    });

    test('reads the time briefly', () {
      final now = DateTime(2026, 11, 24, 15);
      expect(timeAgo(DateTime(2026, 11, 24, 14, 48), now: now), '12m');
      expect(timeAgo(DateTime(2026, 11, 24, 12), now: now), '3h');
      expect(timeAgo(DateTime(2026, 11, 23, 20), now: now), 'Yesterday');
      expect(timeAgo(DateTime(2026, 11, 7, 9), now: now), '7 Nov');
      expect(timeAgo(DateTime(2025, 11, 7, 9), now: now), '7 Nov 2025');
    });
  });

  group('counts and reactions', () {
    testWidgets('no zero counts: the labels alone', (tester) async {
      await card(tester, postJson('p1', category: 'question'));
      expect(find.text('Helpful'), findsOneWidget);
      expect(find.text('Comment'), findsOneWidget);
      expect(find.textContaining('0 '), findsNothing);
    });

    testWidgets('counts once there are some', (tester) async {
      await card(tester, postJson('p1', category: 'general', reactions: 3, comments: 1));
      expect(find.text('3 likes'), findsOneWidget);
      expect(find.text('1 comment'), findsOneWidget);
    });

    testWidgets('an Update offers a heart and has no chip', (tester) async {
      await card(tester, postJson('p1', category: 'general'));
      expect(find.text('Like'), findsOneWidget);
      expect(find.byIcon(Icons.favorite_border_rounded), findsOneWidget);
      expect(find.byIcon(Icons.thumb_up_alt_outlined), findsNothing);
      expect(find.text('Update'), findsNothing);
    });

    testWidgets('the other categories offer helpful, and keep their chip', (tester) async {
      for (final (category, label) in [
        ('question', 'Question'),
        ('recommendation', 'Recommendation'),
        ('alert', 'Alert'),
        ('lost_and_found', 'Lost & found'),
      ]) {
        await card(tester, postJson('p1', category: category));
        expect(find.byIcon(Icons.thumb_up_alt_outlined), findsOneWidget, reason: category);
        expect(find.text(label), findsOneWidget, reason: category);
      }
    });

    testWidgets('a reaction of mine shows as on, whatever its kind', (tester) async {
      await card(tester, postJson('p1', category: 'general', reactions: 1, myReaction: 'helpful'));
      expect(find.byIcon(Icons.favorite_rounded), findsOneWidget);
      expect(find.text('1 like'), findsOneWidget);
    });
  });

  // --------------------------------------------------------------------------
  // Chips
  // --------------------------------------------------------------------------
  group('selected chips and segments', () {
    double contrast(Color a, Color b) {
      final (la, lb) = (a.computeLuminance(), b.computeLuminance());
      return (la > lb ? la + 0.05 : lb + 0.05) / (la > lb ? lb + 0.05 : la + 0.05);
    }

    for (final brightness in Brightness.values) {
      test('are orange with readable white text, in ${brightness.name} mode', () {
        Palette.use(brightness);
        final theme = buildTheme(brightness);
        expect(theme.chipTheme.selectedColor, Palette.selectedFill);
        final label = WidgetStateProperty.resolveAs(theme.chipTheme.labelStyle, {WidgetState.selected});
        expect(label?.color, Palette.onPrimary);
        final segment = theme.segmentedButtonTheme.style!;
        expect(segment.backgroundColor!.resolve({WidgetState.selected}), Palette.selectedFill);
        expect(segment.foregroundColor!.resolve({WidgetState.selected}), Palette.onPrimary);
        expect(contrast(Palette.onPrimary, Palette.selectedFill), greaterThanOrEqualTo(4.5));
        // Unselected keep the outline, and dark text.
        expect(WidgetStateProperty.resolveAs(theme.chipTheme.labelStyle, <WidgetState>{})?.color, Palette.ink);
      });
    }
  });

  // --------------------------------------------------------------------------
  // The whole app, signed in
  // --------------------------------------------------------------------------
  late Map<String, dynamic> me;
  late List<Map<String, dynamic>> feed;
  late List<RequestOptions> sent;

  Future<void> open(WidgetTester tester, {Set<String> hints = const {}}) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    final store = MemoryTokenStore()..refreshToken = 'r1';
    final adapter = FakeAdapter((request) {
      final path = request.path;
      return switch ((request.method, path)) {
        ('POST', '/auth/refresh') => FakeReply(200, tokens('a1', 'r2')),
        ('GET', '/me') => FakeReply(200, me),
        ('GET', '/feed') => FakeReply(200, feedJson(feed)),
        ('GET', '/users/u1') => FakeReply(200, profileJson(me)),
        ('GET', '/users/u1/posts' || '/users/u1/listings' || '/users/u1/services') =>
          const FakeReply(200, {'items': <Object>[], 'next_cursor': null}),
        ('GET', '/conversations') => const FakeReply(200, {'items': <Object>[], 'next_cursor': null}),
        _ => FakeReply(404, errorBody('not_found', 'Resource not found')),
      };
    });
    sent = adapter.requests;
    final api = ApiClient(store: store, dio: fakeDio(adapter));
    await tester.pumpWidget(ProviderScope(
      overrides: [
        tokenStoreProvider.overrideWithValue(store),
        apiClientProvider.overrideWithValue(api),
        offlineStoreProvider.overrideWithValue(MemoryOfflineStore()),
        locationReaderProvider.overrideWithValue(const FakeReader.none()),
        hintsStoreProvider.overrideWithValue(MemoryHintsStore(hints)),
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

  setUp(() {
    me = {...meJson(), 'starter_posts_left': 3};
    feed = [postJson('p1', body: 'Matatu stage moved')];
  });

  group('home', () {
    testWidgets('Services and Groups are one tap away; Events waits for its screen', (tester) async {
      await open(tester);
      expect(find.widgetWithText(ActionChip, 'Services'), findsOneWidget);
      expect(find.widgetWithText(ActionChip, 'Groups'), findsOneWidget);
      expect(find.widgetWithText(ActionChip, 'Events'), findsNothing);

      await tester.tap(find.widgetWithText(ActionChip, 'Groups'));
      await tester.pumpAndSettle();
      expect(sent.any((r) => r.path == '/groups' || r.path.startsWith('/groups')), isTrue);
    });

    testWidgets('the Post button says Post until the first post', (tester) async {
      await open(tester);
      expect(find.widgetWithText(FloatingActionButton, 'Post'), findsOneWidget);
    });

    testWidgets('and is just a plus once I have posted', (tester) async {
      me = {...me, 'starter_posts_left': 2};
      await open(tester);
      expect(find.widgetWithText(FloatingActionButton, 'Post'), findsNothing);
      expect(find.byTooltip('New post'), findsOneWidget);
    });

    testWidgets('the end of the feed asks a question, in the composer on Question', (tester) async {
      await open(tester);
      final ask = find.text('Ask your neighbours something');
      await tester.scrollUntilVisible(ask, 300, scrollable: find.byType(Scrollable).first);
      await tester.tap(ask);
      await tester.pumpAndSettle();

      final question = tester.widget<ChoiceChip>(find.widgetWithText(ChoiceChip, 'Question'));
      expect(question.selected, isTrue);
    });

    testWidgets('Update location explains itself once', (tester) async {
      await open(tester);
      await tester.tap(find.text('Update location'));
      await tester.pumpAndSettle();
      expect(find.textContaining('show what is around where your phone is'), findsOneWidget);
      await tester.tap(find.text('Not now'));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Update location'));
      await tester.pumpAndSettle();
      expect(find.textContaining('show what is around where your phone is'), findsNothing);
    });

    testWidgets('the header says Around here, and the reach is from here', (tester) async {
      me = {...me, 'area_label': {'label': 'nearby', 'precision': 'generic'}};
      await open(tester);
      expect(find.text('Around here'), findsWidgets);
      expect(find.text('Within 15 km of here'), findsOneWidget);
      expect(find.text('Around you'), findsNothing);
    });
  });

  test('only one-time notes reach the hints file, never which account posted', () async {
    final store = MemoryHintsStore();
    final container = ProviderContainer(overrides: [hintsStoreProvider.overrideWithValue(store)]);
    addTearDown(container.dispose);
    final hints = container.read(hintsProvider.notifier);

    hints.mark(Hint.posted('u1'));
    hints.mark(Hint.updateLocation);
    await Future<void>.delayed(Duration.zero);

    expect(container.read(hintsProvider), containsAll([Hint.posted('u1'), Hint.updateLocation]));
    expect(store.seen, {Hint.updateLocation});
  });

  group('my profile', () {
    Future<void> openMe(WidgetTester tester) async {
      await open(tester);
      await tester.tap(find.text('Me'));
      await tester.pumpAndSettle();
    }

    testWidgets('shows what neighbours see, and how I stand', (tester) async {
      me = {
        ...me,
        'badge_presence_days': 6,
        'badge_presence_days_needed': 10,
        'badge_presence_window_days': 14,
        'badge_account_age_reached_at': '2026-10-30T09:00:00Z',
        'vouches_received': 1,
        'circle_count': 3,
      };
      await openMe(tester);

      expect(find.textContaining('Neighbours see: Nyeri Town'), findsOneWidget);
      expect(find.text('Phone verified'), findsOneWidget);
      expect(find.text('Neighbour badge: at home 6 of the 10 days needed (last 14)'), findsOneWidget);
      expect(find.text('1 neighbour vouched for you'), findsOneWidget);
      expect(find.text('3 people in your Circle'), findsOneWidget);
    });

    testWidgets('a verified neighbour sees the badge, not progress', (tester) async {
      me = {...meJson(verified: true), 'circle_count': 1};
      await openMe(tester);
      expect(find.text('Verified neighbour'), findsOneWidget);
      expect(find.textContaining('Neighbour badge: at home'), findsNothing);
      expect(find.text('1 person in your Circle'), findsOneWidget);
    });

    testWidgets('reviews and empty tabs say what to do next', (tester) async {
      me = {...me, 'rating_count': 0, 'rating_average': null};
      await openMe(tester);
      expect(find.textContaining('Reviews appear after your first sale or job'), findsOneWidget);
      expect(find.text("You haven't posted yet. Say hello to your neighbours."), findsOneWidget);
      expect(find.widgetWithText(FilledButton, 'Write a post'), findsOneWidget);

      await tester.tap(find.text('Services').last);
      await tester.pumpAndSettle();
      expect(find.widgetWithText(FilledButton, 'Offer a service'), findsOneWidget);
    });
  });
}

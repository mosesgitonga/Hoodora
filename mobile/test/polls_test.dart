import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:myradius/core/api/token_store.dart';
import 'package:myradius/core/offline_store.dart';
import 'package:myradius/core/providers.dart';
import 'package:myradius/core/theme.dart';
import 'package:myradius/features/auth/auth_controller.dart';
import 'package:myradius/features/auth/auth_models.dart';
import 'package:myradius/features/feed/feed_models.dart';
import 'package:myradius/features/feed/post_views.dart';
import 'package:myradius/features/feed/widgets/post_card.dart';

import 'chats_test.dart' show meJson;
import 'feed_test.dart' show postJson;

/// The signed-in account, set by the test.
class _Auth extends AuthController {
  _Auth(this._initial);
  final AuthState _initial;

  @override
  AuthState build() => _initial;

  void become(AuthState next) => state = next;
}

AuthState _signedIn(String id) => AuthSignedIn(Me.fromJson({...meJson, 'id': id}));

/// Polls on posts, and how many saw a post (decision F.1).
void main() {
  Map<String, dynamic> pollJson({bool voted = false, bool closed = false, bool visible = false, int total = 3}) => {
        'options': [
          {'id': 'o1', 'text': 'Saturday morning', 'votes': visible ? 2 : null},
          {'id': 'o2', 'text': 'Sunday afternoon', 'votes': visible ? 1 : null},
        ],
        'total_votes': total,
        'closes_at': DateTime.now().add(const Duration(days: 2, hours: 1)).toUtc().toIso8601String(),
        'closed': closed,
        'voted': voted,
        'results_visible': visible,
      };

  Map<String, dynamic> pollPost({Map<String, dynamic>? poll, int views = 0}) => {
        ...postJson('p1', body: 'When should we do the clean-up?', category: 'question'),
        'poll': poll ?? pollJson(),
        'view_count': views,
      };

  Future<void> card(
    WidgetTester tester,
    Map<String, dynamic> json, {
    Future<Poll> Function(String optionId)? onVote,
    VoidCallback? onSeen,
  }) async {
    Palette.use(Brightness.light);
    await tester.pumpWidget(MaterialApp(
      theme: buildTheme(),
      home: Scaffold(
        body: SingleChildScrollView(
          child: PostCard(post: Post.fromJson(json), onReact: () {}, onVote: onVote, onSeen: onSeen),
        ),
      ),
    ));
    await tester.pumpAndSettle();
  }

  group('models', () {
    test('a post reads its poll and view count, and an older server has neither', () {
      final post = Post.fromJson(pollPost(views: 12));
      expect(post.viewCount, 12);
      expect(post.poll!.options.map((o) => o.text), ['Saturday morning', 'Sunday afternoon']);
      expect(post.poll!.options.first.votes, isNull);

      final plain = Post.fromJson(postJson('p2'));
      expect(plain.poll, isNull);
      expect(plain.viewCount, 0);
    });

    test('how long a poll has left reads naturally', () {
      final now = DateTime(2026, 11, 27, 12);
      expect(pollClosesIn(now.add(const Duration(days: 2, hours: 3)), now: now), 'Closes in 2 days');
      expect(pollClosesIn(now.add(const Duration(hours: 1, minutes: 5)), now: now), 'Closes in 1 hour');
      expect(pollClosesIn(now.add(const Duration(seconds: 20)), now: now), 'Closes in 1 minute');
    });
  });

  group('a poll on a card', () {
    testWidgets('before voting: the answers to tap, and only the total', (tester) async {
      await card(tester, pollPost(), onVote: (_) async => throw StateError('not tapped'));

      expect(find.widgetWithText(OutlinedButton, 'Saturday morning'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Sunday afternoon'), findsOneWidget);
      expect(find.textContaining('%'), findsNothing);
      expect(find.textContaining('3 votes'), findsOneWidget);
      expect(find.textContaining('Closes in 2 days'), findsOneWidget);
    });

    testWidgets('voting shows each answer\'s share, and never which was chosen', (tester) async {
      String? chosen;
      await card(tester, pollPost(), onVote: (optionId) async {
        chosen = optionId;
        return Poll.fromJson(pollJson(voted: true, visible: true));
      });

      await tester.tap(find.text('Sunday afternoon'));
      await tester.pumpAndSettle();

      expect(chosen, 'o2');
      expect(find.byType(OutlinedButton), findsNothing);
      expect(find.text('67%'), findsOneWidget);
      expect(find.text('33%'), findsOneWidget);
      expect(find.textContaining('You voted'), findsOneWidget);
    });

    testWidgets('a closed poll shows its final results to everyone', (tester) async {
      await card(tester, pollPost(poll: pollJson(closed: true, visible: true)));

      expect(find.byType(OutlinedButton), findsNothing);
      expect(find.textContaining('Final results'), findsOneWidget);
    });

    testWidgets('where voting is not possible, the answers are not tappable', (tester) async {
      await card(tester, pollPost());

      final button = tester.widget<OutlinedButton>(find.widgetWithText(OutlinedButton, 'Saturday morning'));
      expect(button.onPressed, isNull);
    });
  });

  group('views', () {
    testWidgets('a card says how many saw it, and nothing until someone has', (tester) async {
      await card(tester, pollPost(views: 1234));
      expect(find.text('1.2K views'), findsOneWidget);

      await card(tester, pollPost(views: 1));
      expect(find.text('1 view'), findsOneWidget);

      await card(tester, pollPost());
      expect(find.textContaining('view'), findsNothing);
    });

    testWidgets('a card reports itself seen once', (tester) async {
      var seen = 0;
      await card(tester, pollPost(), onSeen: () => seen++);
      await tester.pump();

      expect(seen, 1);
    });
  });

  group('reporting views', () {
    testWidgets('a post seen is sent after a short wait, even when nothing else appears', (tester) async {
      final sent = <List<String>>[];
      final reporter = PostViewReporter((ids) async => sent.add(ids));
      addTearDown(reporter.dispose);

      reporter
        ..seen('p1')
        ..seen('p2')
        ..seen('p1');
      await tester.pump(const Duration(seconds: 2));
      expect(sent, isEmpty);
      await tester.pump(const Duration(seconds: 2));
      expect(sent, [
        ['p1', 'p2'],
      ]);

      reporter.seen('p1');
      await tester.pump(const Duration(seconds: 5));
      expect(sent, hasLength(1), reason: 'each post once');
    });

    testWidgets('ten waiting go at once', (tester) async {
      final sent = <List<String>>[];
      final reporter = PostViewReporter((ids) async => sent.add(ids));
      addTearDown(reporter.dispose);

      for (var i = 0; i < 10; i++) {
        reporter.seen('p$i');
      }
      await tester.pump();
      expect(sent.single, hasLength(10));
    });

    testWidgets('a failed report is dropped quietly', (tester) async {
      final reporter = PostViewReporter((ids) async => throw StateError('offline'));
      addTearDown(reporter.dispose);

      reporter.seen('p1');
      await tester.pump(const Duration(seconds: 4));
      expect(tester.takeException(), isNull);
    });

    testWidgets('each account on the phone starts afresh', (tester) async {
      final auth = _Auth(_signedIn('u1'));
      final container = ProviderContainer(overrides: [
        tokenStoreProvider.overrideWithValue(MemoryTokenStore()),
        offlineStoreProvider.overrideWithValue(MemoryOfflineStore()),
        authControllerProvider.overrideWith(() => auth),
      ]);
      addTearDown(container.dispose);

      final first = container.read(postViewReporterProvider);
      auth.become(_signedIn('u1'));
      expect(container.read(postViewReporterProvider), same(first), reason: 'same account, profile refreshed');

      auth.become(_signedIn('u2'));
      expect(container.read(postViewReporterProvider), isNot(same(first)));
    });
  });
}

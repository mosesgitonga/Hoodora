import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:myradius/core/api/api_client.dart';
import 'package:myradius/core/api/token_store.dart';
import 'package:myradius/core/google_auth.dart';
import 'package:myradius/core/offline_store.dart';
import 'package:myradius/core/providers.dart';
import 'package:myradius/main.dart';

import 'support/fake_adapter.dart';
import 'support/fake_google.dart';
import 'support/fake_location.dart';

/// A mid-range Android phone: 1080 × 2400 pixels at 2.75×, about 393 × 873.
void usePhoneScreen(WidgetTester tester) {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.75;
  addTearDown(tester.view.reset);
}

/// The whole sign-in flow against a scripted API: Google (the only way in,
/// decision A.2), sign-up with consents, home area, and into the app.
void main() {
  late FakeAdapter adapter;
  late MemoryTokenStore store;
  late FakeGoogleAuth google;

  Widget app() {
    final api = ApiClient(store: store, dio: fakeDio(adapter));
    return ProviderScope(
      overrides: [
        tokenStoreProvider.overrideWithValue(store),
        apiClientProvider.overrideWithValue(api),
        googleAuthProvider.overrideWithValue(google),
        locationReaderProvider.overrideWithValue(const FakeReader.none()),
        offlineStoreProvider.overrideWithValue(MemoryOfflineStore()),
      ],
      child: const MyRadiusApp(),
    );
  }

  setUp(() {
    store = MemoryTokenStore();
    google = FakeGoogleAuth();
    adapter = FakeAdapter((request) {
      switch (request.path) {
        case '/auth/signup':
          return FakeReply(201, {'tokens': tokens('a1', 'r1'), 'user_id': 'u1'});
        case '/me':
          return const FakeReply(200, {
            'id': 'u1',
            'display_name': 'Amina K.',
            'phone_number': '+254712345678',
            'status': 'active',
            'member_since': '2026-10-16T09:00:00Z',
            'has_home_location': false,
            'is_verified_neighbour': false,
            'rating_count': 0,
          });
        default:
          return FakeReply(404, errorBody('not_found', 'Resource not found'));
      }
    });
  });

  testWidgets("without the server, sign-in says so and offers to try again", (tester) async {
    usePhoneScreen(tester);
    await tester.pumpWidget(app());
    await tester.pumpAndSettle();

    // No stored session: the guest Home first (decision M.9). There is no GPS in a
    // test, so it offers to sign up instead.
    await tester.tap(find.text('Sign up instead'));
    await tester.pumpAndSettle();
    expect(find.text("What's happening around you"), findsOneWidget);

    // This server can't say how to sign in (it answers 404), and Google is the
    // only way: no button to a dead end, and no phone number to type.
    expect(find.text('Continue with Google'), findsNothing);
    expect(find.byType(TextField), findsNothing);
    expect(find.textContaining("Signing in isn't available right now"), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
  });

  testWidgets('a stored session that is no longer valid lands on the guest Home', (tester) async {
    store.refreshToken = 'revoked';
    adapter = FakeAdapter((request) =>
        FakeReply(401, errorBody('unauthenticated', 'That session is no longer valid')));
    await tester.pumpWidget(app());
    await tester.pumpAndSettle();
    expect(find.text('Sign up instead'), findsOneWidget);
    expect(store.refreshToken, isNull);
  });

  testWidgets('a stored session with no connection offers to try again', (tester) async {
    store.refreshToken = 'r1';
    adapter = FakeAdapter((request) => throw StateError('offline'));
    await tester.pumpWidget(app());
    await tester.pumpAndSettle();
    expect(find.text("You're offline"), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
  });

  group('Google sign-in (decisions A.1, A.2)', () {
    /// A server with Google sign-in on. [googleStatus] is what `/auth/google`
    /// answers.
    FakeAdapter googleServer({String googleStatus = 'signup_required'}) => FakeAdapter((request) {
          switch (request.path) {
            case '/auth/methods':
              return const FakeReply(200, {
                'phone': false,
                'google': true,
                'google_client_id': 'web-client.apps.googleusercontent.com',
              });
            case '/auth/google':
              return googleStatus == 'signed_in'
                  ? FakeReply(200, {'status': 'signed_in', 'tokens': tokens('a2', 'r2')})
                  : const FakeReply(200, {'status': 'signup_required', 'signup_token': 'st-g'});
            case '/auth/signup':
              return FakeReply(201, {'tokens': tokens('a1', 'r1'), 'user_id': 'u1'});
            case '/me':
              return const FakeReply(200, {
                'id': 'u1',
                'display_name': 'Amina Kamau',
                'phone_number': null,
                'has_google_account': true,
                'status': 'active',
                'member_since': '2026-11-23T09:00:00Z',
                'has_home_location': false,
                'is_verified_neighbour': false,
                'rating_count': 0,
              });
            default:
              return FakeReply(404, errorBody('not_found', 'Resource not found'));
          }
        });

    Future<void> openSignIn(WidgetTester tester) async {
      usePhoneScreen(tester);
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      await tester.tap(find.text('Sign up instead'));
      await tester.pumpAndSettle();
    }

    testWidgets('a new Google account signs up with its name suggested', (tester) async {
      adapter = googleServer();
      google.credential = const GoogleCredential(idToken: 'google-id-token', displayName: 'Amina Kamau');
      await openSignIn(tester);

      await tester.tap(find.text('Continue with Google'));
      await tester.pumpAndSettle();

      // Google was handed the server's client ID, and the server the token.
      expect(google.serverClientIds, ['web-client.apps.googleusercontent.com']);
      final sent = adapter.requests.firstWhere((r) => r.path == '/auth/google').data as Map;
      expect(sent['id_token'], 'google-id-token');
      expect(sent['device_id'], store.id);

      // The sign-up screen, starting from the Google name.
      expect(find.text('Create your account'), findsOneWidget);
      expect(find.text('Amina Kamau'), findsOneWidget);
      for (final label in [
        'I am 18 or older',
        'I agree to the terms of use',
        'I agree to the privacy policy',
        'Use my location to show what is nearby',
      ]) {
        await tester.ensureVisible(find.text(label));
        await tester.tap(find.text(label));
        await tester.pump();
      }
      final create = find.widgetWithText(FilledButton, 'Create account');
      await tester.ensureVisible(create);
      await tester.tap(create);
      await tester.pumpAndSettle();

      final signup = adapter.requests.firstWhere((r) => r.path == '/auth/signup').data as Map;
      expect(signup['signup_token'], 'st-g');
      expect(signup['display_name'], 'Amina Kamau');
      expect(find.text('Is this your home area?'), findsOneWidget);
    });

    testWidgets('Google is the only way in', (tester) async {
      adapter = googleServer();
      await openSignIn(tester);

      expect(find.text('Continue with Google'), findsOneWidget);
      expect(find.byType(TextField), findsNothing);
      expect(find.text('Send code'), findsNothing);
    });

    testWidgets('backing out of the Google picker changes nothing', (tester) async {
      adapter = googleServer();
      google.credential = null;
      await openSignIn(tester);

      await tester.tap(find.text('Continue with Google'));
      await tester.pumpAndSettle();

      expect(adapter.requests.map((r) => r.path), isNot(contains('/auth/google')));
      expect(find.text("What's happening around you"), findsOneWidget);
      expect(find.textContaining("didn't work"), findsNothing);
    });

    testWidgets('a returning Google account goes straight in', (tester) async {
      adapter = googleServer(googleStatus: 'signed_in');
      google.credential = const GoogleCredential(idToken: 'google-id-token');
      await openSignIn(tester);

      await tester.tap(find.text('Continue with Google'));
      await tester.pumpAndSettle();

      expect(store.refreshToken, 'r2');
      expect(adapter.requests.map((r) => r.path), isNot(contains('/auth/signup')));
      expect(find.text('Is this your home area?'), findsOneWidget);
    });
  });
}

import 'package:dio/dio.dart' show RequestOptions;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:myradius/core/api/api_client.dart';
import 'package:myradius/core/api/token_store.dart';
import 'package:myradius/core/offline_store.dart';
import 'package:myradius/core/providers.dart';
import 'package:myradius/core/realtime.dart';
import 'package:myradius/main.dart';

import 'feed_test.dart' show feedJson, postJson;
import 'support/fake_adapter.dart';
import 'support/fake_location.dart';
import 'support/fake_socket.dart';

void main() {
  late List<RequestOptions> sent;

  /// Signed in, with home in Nyeri Town. [explore] is the server's answer when the
  /// app sends where the phone is; the feed differs by where it is read from.
  Future<void> open(WidgetTester tester, {required Map<String, dynamic> explore, FakeReader? reader}) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    final store = MemoryTokenStore()..refreshToken = 'r1';
    final adapter = FakeAdapter((request) => switch ((request.method, request.path)) {
          ('POST', '/auth/refresh') => FakeReply(200, tokens('a1', 'r2')),
          ('GET', '/me') => const FakeReply(200, {
              'id': 'u1',
              'display_name': 'Amina K.',
              'status': 'active',
              'has_home_location': true,
              'is_verified_neighbour': false,
              'area_label': {'label': 'Nyeri Town', 'precision': 'town'},
            }),
          ('GET', '/feed') => request.queryParameters['anchor'] == 'explore'
              ? FakeReply(200, feedJson([postJson('p2', body: 'Matatu stage moved')]))
              : FakeReply(200, feedJson([postJson('p1', body: 'Water off on Saturday')])),
          ('POST', '/me/explore') => FakeReply(200, explore),
          ('GET', '/listings') => FakeReply(200, {'items': <Object>[], 'next_cursor': null, 'radius_km': 10}),
          ('GET', '/services') => FakeReply(200, {'items': <Object>[], 'next_cursor': null, 'radius_km': 10}),
          ('DELETE', '/me/explore') => const FakeReply(204),
          _ => FakeReply(404, errorBody('not_found', 'Resource not found')),
        });
    sent = adapter.requests;
    final api = ApiClient(store: store, dio: fakeDio(adapter));
    await tester.pumpWidget(ProviderScope(
      overrides: [
        tokenStoreProvider.overrideWithValue(store),
        apiClientProvider.overrideWithValue(api),
        offlineStoreProvider.overrideWithValue(MemoryOfflineStore()),
        locationReaderProvider.overrideWithValue(reader ?? const FakeReader()),
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

  String later() => DateTime.now().toUtc().add(const Duration(hours: 2)).toIso8601String();

  testWidgets('away from home, the app says where it is by itself, and the feed follows', (tester) async {
    await open(tester, explore: {
      'area_label': {'label': 'Kingongo', 'precision': 'area'},
      'expires_at': later(),
      'same_area_as_home': false,
    });

    // Sent at launch, with no tap (decision L.1).
    final asked = sent.singleWhere((r) => r.method == 'POST' && r.path == '/me/explore');
    expect((asked.data as Map).keys, containsAll(['latitude', 'longitude']));
    expect(find.text('Kingongo'), findsOneWidget);
    expect(find.text('Matatu stage moved'), findsOneWidget);
    expect(find.text('Water off on Saturday'), findsNothing);
    // No strip, and no way "back home": what's around the phone is the app.
    expect(find.text('Show home area'), findsNothing);
    expect(find.textContaining('still goes to'), findsNothing);
  });

  testWidgets('the market and services and jobs follow too', (tester) async {
    await open(tester, explore: {
      'area_label': {'label': 'Kingongo', 'precision': 'area'},
      'expires_at': later(),
      'same_area_as_home': false,
    });

    await tester.tap(find.text('Market'));
    await tester.pumpAndSettle();
    final listings = sent.where((r) => r.path == '/listings').toList();
    expect(listings.last.queryParameters['anchor'], 'explore');
  });

  testWidgets('in the home hexagon, the feed is home, and the button confirms', (tester) async {
    await open(tester, explore: {
      'area_label': {'label': 'Nyeri Town', 'precision': 'town'},
      'expires_at': later(),
      'same_area_as_home': true,
    });
    expect(find.text('Nyeri Town'), findsOneWidget);
    expect(find.text('Water off on Saturday'), findsOneWidget);

    await tester.tap(find.byTooltip('Update my location'));
    await tester.pumpAndSettle();

    expect(find.text("Showing what's around you now."), findsOneWidget);
    expect(find.text('Water off on Saturday'), findsOneWidget);
  });

  testWidgets('with no location, the feed stays on home and the button says why', (tester) async {
    await open(tester, explore: const {}, reader: const FakeReader(problem: 'Location is off. Turn it on to use this.'));
    expect(find.text('Water off on Saturday'), findsOneWidget);
    expect(sent.where((r) => r.path == '/me/explore'), isEmpty);

    await tester.tap(find.byTooltip('Update my location'));
    await tester.pumpAndSettle();

    expect(find.text('Location is off. Turn it on to use this.'), findsOneWidget);
    expect(sent.where((r) => r.path == '/me/explore'), isEmpty);
  });

  testWidgets('coming back to the app soon after sends nothing more', (tester) async {
    await open(tester, explore: {
      'area_label': {'label': 'Kingongo', 'precision': 'area'},
      'expires_at': later(),
      'same_area_as_home': false,
    });

    // Away for a moment and back (resumed → inactive → resumed is a legal path).
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();

    // Within two minutes of the last: still one.
    expect(sent.where((r) => r.method == 'POST' && r.path == '/me/explore'), hasLength(1));
  });
}


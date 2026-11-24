import 'package:dio/dio.dart' show RequestOptions;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:myradius/core/api/api_client.dart';
import 'package:myradius/core/api/token_store.dart';
import 'package:myradius/core/providers.dart';
import 'package:myradius/core/realtime.dart';
import 'package:myradius/core/router.dart';
import 'package:myradius/main.dart';

import 'feed_test.dart' show postJson;
import 'support/fake_adapter.dart';
import 'support/fake_location.dart';
import 'support/fake_socket.dart';

/// Circle in the app (decisions C.1–C.6): from a profile, on the Circle screen,
/// when posting, and in Privacy. The server holds the rules; these check the app
/// asks for the right thing and shows what it's told.
void main() {
  late FakeAdapter adapter;
  late Map<String, dynamic> me;
  late Map<String, dynamic> kamau;
  late List<Map<String, dynamic>> incoming;
  late List<Map<String, dynamic>> outgoing;

  Map<String, dynamic> person(String id, String name) => {'id': id, 'display_name': name, 'is_verified_neighbour': false};

  Map<String, dynamic> request(String id, Map<String, dynamic> user, String direction) => {
        'id': id,
        'user': user,
        'direction': direction,
        'status': 'pending',
        'created_at': '2026-11-20T09:00:00Z',
        'expires_at': '2026-12-20T09:00:00Z',
      };

  FakeReply handle(RequestOptions r) {
    final path = r.path;
    if (path == '/auth/refresh') return FakeReply(200, tokens('a1', 'r2'));
    if (path == '/me' && r.method == 'GET') return FakeReply(200, me);
    if (path == '/me' && r.method == 'PATCH') {
      me = {...me, ...Map<String, dynamic>.from(r.data as Map)};
      return FakeReply(200, me);
    }
    if (path == '/feed') return const FakeReply(200, {'items': [], 'next_cursor': null, 'radius_km': 15});
    if (path == '/me/consents') return const FakeReply(200, <Object>[]);
    if (path == '/conversations') return const FakeReply(200, {'items': [], 'next_cursor': null});
    if (path == '/users/u2') return FakeReply(200, kamau);
    if (path.startsWith('/users/u2/')) return const FakeReply(200, {'items': [], 'next_cursor': null});
    if (path == '/circle/requests' && r.method == 'POST') {
      kamau = {...kamau, 'relationship': 'request_sent', 'circle_request_id': 'r9'};
      return FakeReply(201, {'relationship': 'request_sent', 'request': request('r9', person('u2', 'Kamau N.'), 'outgoing')});
    }
    if (path == '/circle/requests') {
      final items = r.queryParameters['direction'] == 'outgoing' ? outgoing : incoming;
      return FakeReply(200, {'items': items, 'next_cursor': null});
    }
    if (path.endsWith('/accept')) {
      final id = path.split('/')[3];
      incoming = incoming.where((x) => x['id'] != id).toList();
      kamau = {...kamau, 'relationship': 'in_circle', 'circle_request_id': null};
      return const FakeReply(204);
    }
    if (path.startsWith('/circle/requests/') && r.method == 'DELETE') {
      final id = path.split('/').last;
      outgoing = outgoing.where((x) => x['id'] != id).toList();
      return const FakeReply(204);
    }
    if (path == '/circle') {
      return FakeReply(200, {
        'items': [
          {
            'user': person('u7', 'Njeri W.'),
            'area_label': {'label': 'Nairobi', 'precision': 'town'},
            'distance_bucket': null,
            'within_feed_radius': false,
            'since': '2026-11-01T09:00:00Z',
          },
        ],
        'next_cursor': null,
      });
    }
    if (path == '/feed/circle') {
      return FakeReply(200, {
        'items': [postJson('p7', body: 'Settled in Nairobi, miss Nyeri mandazi')],
        'next_cursor': null,
      });
    }
    if (path == '/stories/circle' || path == '/stories') return const FakeReply(200, {'items': [], 'next_cursor': null});
    if (path == '/posts' && r.method == 'POST') {
      return FakeReply(201, {'post': postJson('p8', body: (r.data as Map)['body'] as String), 'reach_estimate': 40});
    }
    return FakeReply(404, errorBody('not_found', 'Resource not found'));
  }

  Future<ProviderContainer> open(WidgetTester tester, String location) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    adapter = FakeAdapter(handle);
    final store = MemoryTokenStore()..refreshToken = 'r1';
    final api = ApiClient(store: store, dio: fakeDio(adapter));
    final container = ProviderContainer(overrides: [
      tokenStoreProvider.overrideWithValue(store),
      apiClientProvider.overrideWithValue(api),
      locationReaderProvider.overrideWithValue(const FakeReader.none()),
      realtimeProvider.overrideWith((ref) {
        final client = RealtimeClient(api, connect: FakeSockets().connect, uri: Uri.parse('ws://api.test/v1/ws'));
        ref.onDispose(client.dispose);
        return client;
      }),
    ]);
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const MyRadiusApp()));
    await tester.pumpAndSettle();
    container.read(routerProvider).push(location);
    await tester.pumpAndSettle();
    return container;
  }

  setUp(() {
    me = {
      'id': 'u1',
      'display_name': 'Amina K.',
      'status': 'active',
      'has_home_location': true,
      'is_verified_neighbour': false,
      'area_label': {'label': 'Nyeri Town', 'precision': 'town'},
      'circle_request_policy': 'everyone',
    };
    kamau = {
      ...person('u2', 'Kamau N.'),
      'area_label': {'label': 'Nyeri Town', 'precision': 'town'},
      'posts_visible': true,
      'relationship': 'none',
      'circle_request_id': null,
    };
    incoming = [];
    outgoing = [];
  });

  testWidgets('Add to Circle sends a request, and the profile then says so', (tester) async {
    await open(tester, Routes.person('u2'));

    await tester.tap(find.text('Add to Circle'));
    await tester.pumpAndSettle();

    final sent = adapter.requests.singleWhere((r) => r.path == '/circle/requests' && r.method == 'POST');
    expect(sent.data, {'user_id': 'u2'});
    expect(find.text('Request sent'), findsOneWidget);
  });

  testWidgets('a request from them can be accepted from their profile', (tester) async {
    kamau = {...kamau, 'relationship': 'request_received', 'circle_request_id': 'r5'};
    await open(tester, Routes.person('u2'));

    await tester.tap(find.text('Accept Circle request'));
    await tester.pumpAndSettle();

    expect(adapter.requests.any((r) => r.path == '/circle/requests/r5/accept'), isTrue);
    expect(find.text('In your Circle'), findsOneWidget);
  });

  testWidgets('the Circle screen: their posts, the people, and requests to answer', (tester) async {
    incoming = [request('r1', person('u3', 'Otieno A.'), 'incoming')];
    outgoing = [request('r2', person('u4', 'Wambui K.'), 'outgoing')];
    await open(tester, Routes.circle);

    expect(find.text('Settled in Nairobi, miss Nyeri mandazi'), findsOneWidget);

    await tester.tap(find.text('People'));
    await tester.pumpAndSettle();
    // Beyond my radius: the town, and no distance (decision C.6).
    expect(find.text('Njeri W.'), findsOneWidget);
    expect(find.text('Nairobi'), findsOneWidget);

    await tester.tap(find.text('Requests · 1'));
    await tester.pumpAndSettle();
    expect(find.text('Asking you'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Accept'));
    await tester.pumpAndSettle();
    expect(adapter.requests.any((r) => r.path == '/circle/requests/r1/accept'), isTrue);

    await tester.tap(find.text('Withdraw'));
    await tester.pumpAndSettle();
    expect(adapter.requests.any((r) => r.path == '/circle/requests/r2' && r.method == 'DELETE'), isTrue);
    expect(find.text('No requests waiting.'), findsOneWidget);
  });

  testWidgets('a post can be kept to neighbours only', (tester) async {
    await open(tester, Routes.compose);

    await tester.enterText(find.byType(TextField).first, 'Water is back on in Kamakwa');
    await tester.tap(find.text('Neighbours only'));
    await tester.pump();
    final post = find.widgetWithText(FilledButton, 'Post');
    await tester.ensureVisible(post);
    await tester.tap(post);
    await tester.pumpAndSettle();

    final sent = adapter.requests.singleWhere((r) => r.path == '/posts' && r.method == 'POST');
    expect((sent.data as Map)['audience'], 'neighbours_only');
  });

  testWidgets('with starter posts left, writing a post says so (decision L.3)', (tester) async {
    me = {...me, 'starter_posts_left': 2};
    await open(tester, Routes.compose);

    expect(find.textContaining('uses one of your 2 starter posts'), findsOneWidget);
    expect(find.textContaining("can't contain links"), findsOneWidget);
  });

  testWidgets('who can send Circle requests is set in Privacy', (tester) async {
    await open(tester, Routes.privacy);

    final setting = find.text('Who can send you Circle requests');
    await tester.scrollUntilVisible(setting, 200, scrollable: find.byType(Scrollable).last);
    await tester.ensureVisible(setting);
    await tester.pumpAndSettle();
    await tester.tap(setting);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Nobody'));
    await tester.pumpAndSettle();

    final patch = adapter.requests.singleWhere((r) => r.path == '/me' && r.method == 'PATCH');
    expect(patch.data, {'circle_request_policy': 'nobody'});
  });
}

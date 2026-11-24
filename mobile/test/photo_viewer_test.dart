import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:myradius/core/net_image.dart';
import 'package:myradius/core/photo_viewer.dart';
import 'package:myradius/core/theme.dart';
import 'package:myradius/features/feed/feed_models.dart';
import 'package:myradius/features/feed/widgets/post_card.dart';

import 'feed_test.dart' show postJson;

/// A photo that is already here, so nothing waits on the network or the cache.
class _ReadyPhoto extends ImageProvider<_ReadyPhoto> {
  _ReadyPhoto(this.url, this.image);

  final String url;
  final ui.Image image;

  @override
  Future<_ReadyPhoto> obtainKey(ImageConfiguration configuration) => SynchronousFuture(this);

  @override
  ImageStreamCompleter loadImage(_ReadyPhoto key, ImageDecoderCallback decode) =>
      OneFrameImageStreamCompleter(SynchronousFuture(ImageInfo(image: image.clone())));
}

/// Decision U.6: tap a photo to see it full screen, at the size the screen needs.
void main() {
  late List<String> requested;

  Future<void> readyPhotos(WidgetTester tester) async {
    final image = (await tester.runAsync(() => createTestImage(width: 4, height: 4)))!;
    requested = [];
    debugNetImageOverride = (url) {
      requested.add(url);
      return _ReadyPhoto(url, image);
    };
    addTearDown(() => debugNetImageOverride = null);
  }

  Map<String, dynamic> photo(String id) => {
    'media_id': id,
    'variants': {
      for (final width in [320, 720, 1280])
        '$width': {'url': 'https://media.test/public/post/$id/$width.webp', 'width': width, 'height': width},
    },
  };

  testWidgets("tapping a post photo opens it full screen, beside the post's others", (tester) async {
    tester.view.physicalSize = const Size(720, 1600);
    tester.view.devicePixelRatio = 2;
    addTearDown(tester.view.reset);
    await readyPhotos(tester);
    Palette.use(Brightness.light);
    final post = Post.fromJson({
      ...postJson('p1', category: 'general'),
      'images': [photo('a'), photo('b')],
    });
    await tester.pumpWidget(MaterialApp(
      theme: buildTheme(),
      home: Scaffold(body: SingleChildScrollView(child: PostCard(post: post, onReact: () {}))),
    ));

    await tester.tap(find.byType(NetImage).at(1));
    await tester.pumpAndSettle();

    expect(find.byType(PhotoViewerScreen), findsOneWidget);
    expect(find.text('2 / 2'), findsOneWidget);
    // The size this 720-pixel screen needs, not the 1280.
    expect(requested, contains('https://media.test/public/post/b/720.webp'));
    expect(requested, isNot(contains('https://media.test/public/post/b/1280.webp')));

    await tester.tap(find.byTooltip('Close'));
    await tester.pumpAndSettle();
    expect(find.byType(PhotoViewerScreen), findsNothing);
  });

  testWidgets('a wider screen gets the 1280 size', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    String? chosen;
    await tester.pumpWidget(MaterialApp(home: Builder(builder: (context) {
      chosen = fullScreenSize(context, {320: 's', 720: 'm', 1280: 'l'});
      return const SizedBox();
    })));
    expect(chosen, 'l');
  });

  testWidgets('a single photo has no counter, and nothing to open does nothing', (tester) async {
    await readyPhotos(tester);
    await tester.pumpWidget(MaterialApp(home: Builder(builder: (context) {
      return Column(children: [
        TextButton(onPressed: () => openPhotos(context, [{720: 'https://media.test/x.webp'}]), child: const Text('one')),
        TextButton(onPressed: () => openPhotos(context, [<int, String>{}]), child: const Text('none')),
      ]);
    })));

    await tester.tap(find.text('none'));
    await tester.pumpAndSettle();
    expect(find.byType(PhotoViewerScreen), findsNothing);

    await tester.tap(find.text('one'));
    await tester.pumpAndSettle();
    expect(find.byType(PhotoViewerScreen), findsOneWidget);
    expect(find.textContaining(' / '), findsNothing);
  });
}

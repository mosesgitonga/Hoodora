import 'dart:io';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:myradius/core/net_image.dart';

/// Decision U.1: every photo is cached by a key that a new signature can't change.
void main() {
  const signedA =
      'https://myradius.chatara.co/myradius-media/images/u1/m1/720.webp?X-Amz-Date=20261124T142800Z&X-Amz-Signature=aa';
  const signedB =
      'https://myradius.chatara.co/myradius-media/images/u1/m1/720.webp?X-Amz-Date=20261124T142801Z&X-Amz-Signature=bb';

  test('two signatures of one photo share a cache key, which is its path', () {
    expect(imageCacheKey(signedA), imageCacheKey(signedB));
    expect(imageCacheKey(signedA), '/myradius-media/images/u1/m1/720.webp');
  });

  test('different widths of one photo are different keys', () {
    expect(imageCacheKey(signedA), isNot(imageCacheKey(signedA.replaceFirst('/720.webp', '/320.webp'))));
  });

  test('the sizes are named by purpose, at the widths the server renders', () {
    expect([for (final size in ImageSize.values) size.width], [320, 720, 1280]);
  });

  testWidgets('the shared widget always passes the stable key', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: NetImage(signedA, width: 100, height: 100)));

    final image = tester.widget<CachedNetworkImage>(find.byType(CachedNetworkImage));
    expect(image.cacheKey, '/myradius-media/images/u1/m1/720.webp');
    expect(image.imageUrl, signedA);
    expect(image.fadeInDuration, const Duration(milliseconds: 150));
  });

  test('no screen loads a network image except through the shared widget', () {
    final offenders = <String>[];
    for (final file in Directory('lib').listSync(recursive: true).whereType<File>()) {
      if (!file.path.endsWith('.dart') || file.path.replaceAll(r'\', '/').endsWith('core/net_image.dart')) continue;
      final source = file.readAsStringSync();
      for (final pattern in ['CachedNetworkImage', 'Image.network(', 'NetworkImage(', 'cached_network_image']) {
        if (source.contains(pattern)) offenders.add('${file.path}: $pattern');
      }
    }
    expect(offenders, isEmpty, reason: 'use NetImage or netImageProvider from core/net_image.dart');
  });
}

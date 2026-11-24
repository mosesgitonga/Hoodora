import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import 'theme.dart';

/// The widths the server renders, named by what each is for (decision U.1).
/// Asking by purpose rather than by on-screen width keeps one image to one
/// cached file: a grid tile no longer rounds up to the feed's size.
enum ImageSize {
  /// Avatars, story rings, group pictures, marketplace grid tiles.
  small(320),

  /// Feed photos, listing and chat photos, covers.
  medium(720),

  /// Full screen: the story viewer.
  large(1280);

  const ImageSize(this.width);

  final int width;
}

/// What the cache knows an image by: the URL's path. A presigned or signed URL
/// changes on every load, but its path is the variant's storage key, unique to
/// that size of that photo and never reused (a new upload gets a new key), so the
/// cache hits however the URL was signed.
String imageCacheKey(String url) {
  final uri = Uri.tryParse(url);
  return uri == null || uri.path.isEmpty ? url : uri.path;
}

/// The same image as [NetImage] shows, for warming the cache ahead of time.
ImageProvider netImageProvider(String url) => CachedNetworkImageProvider(url, cacheKey: imageCacheKey(url));

/// Warms the cache with [urls] (the next page's first photos), quietly: a photo
/// that fails here is simply loaded when it scrolls into view.
void prefetchImages(BuildContext context, Iterable<String> urls) {
  for (final url in urls) {
    precacheImage(netImageProvider(url), context, onError: (_, _) {});
  }
}

/// Every network image in the app goes through here (a test checks), so each
/// has a stable cache key, a neutral placeholder in its space, and a short fade.
class NetImage extends StatelessWidget {
  const NetImage(
    this.url, {
    super.key,
    this.width,
    this.height,
    this.fit = BoxFit.cover,
    this.placeholder,
    this.error,
  });

  final String url;
  final double? width;
  final double? height;
  final BoxFit fit;

  /// Shown while loading; the theme's sand colour by default.
  final Widget? placeholder;

  /// Shown when the image can't be loaded; the placeholder by default.
  final Widget? error;

  @override
  Widget build(BuildContext context) {
    final waiting = placeholder ?? ColoredBox(color: Palette.sand);
    return CachedNetworkImage(
      imageUrl: url,
      cacheKey: imageCacheKey(url),
      width: width,
      height: height,
      fit: fit,
      fadeInDuration: const Duration(milliseconds: 150),
      fadeOutDuration: Duration.zero,
      placeholder: (_, _) => waiting,
      errorWidget: (_, _, _) => error ?? waiting,
    );
  }
}

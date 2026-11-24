import 'package:flutter/material.dart';

import '../features/feed/feed_models.dart' show sizeFor;
import 'net_image.dart';
import 'theme.dart';

/// The size of a photo to show across the whole screen: the smallest the server
/// has that is at least as wide as the screen in pixels, else the largest. On a
/// 720-pixel phone that is the 720 size, not 1280, which is two and a half times
/// the data for nothing the screen can show (decision U.6).
String? fullScreenSize(BuildContext context, Map<int, String> sizes) =>
    sizeFor(sizes, (MediaQuery.sizeOf(context).width * MediaQuery.devicePixelRatioOf(context)).round());

/// Opens photos full screen (decision U.6): swipe between them, pinch to zoom,
/// the close button or back to leave. Each photo is a map of its sizes by width.
Future<void> openPhotos(BuildContext context, List<Map<int, String>> photos, {int initial = 0}) {
  final shown = [for (final sizes in photos) if (sizes.isNotEmpty) sizes];
  if (shown.isEmpty) return Future.value();
  return Navigator.of(context, rootNavigator: true).push(
    PageRouteBuilder<void>(
      pageBuilder: (_, _, _) => PhotoViewerScreen(photos: shown, initial: initial.clamp(0, shown.length - 1)),
      transitionsBuilder: (_, animation, _, child) => FadeTransition(opacity: animation, child: child),
    ),
  );
}

class PhotoViewerScreen extends StatefulWidget {
  const PhotoViewerScreen({super.key, required this.photos, this.initial = 0});

  final List<Map<int, String>> photos;
  final int initial;

  @override
  State<PhotoViewerScreen> createState() => _PhotoViewerScreenState();
}

class _PhotoViewerScreenState extends State<PhotoViewerScreen> {
  late final _pages = PageController(initialPage: widget.initial);
  late int _at = widget.initial;

  /// While a photo is zoomed, a drag pans it rather than turning the page.
  bool _zoomed = false;

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final count = widget.photos.length;
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          PageView.builder(
            controller: _pages,
            physics: _zoomed ? const NeverScrollableScrollPhysics() : null,
            itemCount: count,
            onPageChanged: (index) => setState(() {
              _at = index;
              _zoomed = false;
            }),
            itemBuilder: (_, index) => _ZoomablePhoto(
              sizes: widget.photos[index],
              onZoomed: (zoomed) {
                if (zoomed != _zoomed) setState(() => _zoomed = zoomed);
              },
            ),
          ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(4, 4, 16, 0),
              child: Row(
                children: [
                  IconButton(
                    tooltip: 'Close',
                    icon: const Icon(Icons.close_rounded, color: Palette.onPrimary),
                    onPressed: () => Navigator.of(context).maybePop(),
                  ),
                  const Spacer(),
                  if (count > 1)
                    Text(
                      '${_at + 1} / $count',
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(color: Palette.onPrimary),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ZoomablePhoto extends StatefulWidget {
  const _ZoomablePhoto({required this.sizes, required this.onZoomed});

  final Map<int, String> sizes;
  final ValueChanged<bool> onZoomed;

  @override
  State<_ZoomablePhoto> createState() => _ZoomablePhotoState();
}

class _ZoomablePhotoState extends State<_ZoomablePhoto> {
  final _transform = TransformationController();

  @override
  void dispose() {
    _transform.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final full = fullScreenSize(context, widget.sizes);
    if (full == null) return const SizedBox.shrink();
    return InteractiveViewer(
      transformationController: _transform,
      minScale: 1,
      maxScale: 4,
      onInteractionEnd: (_) => widget.onZoomed(_transform.value.getMaxScaleOnAxis() > 1.01),
      // The feed's size is usually cached already: shown at once, then replaced by
      // the sharper one when it arrives.
      child: FullScreenImage(full, preview: sizeFor(widget.sizes, ImageSize.medium.width)),
    );
  }
}

/// A photo across the whole screen, from the shared image cache: a spinner, or
/// [preview] (a smaller size, usually cached), until it arrives.
class FullScreenImage extends StatelessWidget {
  const FullScreenImage(this.url, {super.key, this.preview});

  final String url;
  final String? preview;

  @override
  Widget build(BuildContext context) {
    const waiting = Center(child: CircularProgressIndicator(color: Palette.onPrimary));
    final small = preview;
    final before = small == null || small == url
        ? waiting
        : Image(
            image: netImageProvider(small),
            fit: BoxFit.contain,
            frameBuilder: (_, child, frame, synchronous) => frame == null && !synchronous ? waiting : child,
            errorBuilder: (_, _, _) => waiting,
          );
    return SizedBox.expand(
      child: Image(
        image: netImageProvider(url),
        fit: BoxFit.contain,
        frameBuilder: (_, child, frame, synchronous) => frame == null && !synchronous ? before : child,
        errorBuilder: (_, _, _) =>
            const Center(child: Icon(Icons.broken_image_outlined, color: Palette.onPrimary, size: 40)),
      ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/hints.dart';
import '../../../core/net_image.dart';
import '../../../core/providers.dart';
import '../../../core/router.dart';
import '../../../core/theme.dart';
import '../../../core/widgets.dart';
import '../../auth/auth_controller.dart';
import '../../chats/start_chat.dart';
import '../../profile/profile_screen.dart';
import '../../stories/stories_controller.dart';
import '../../stories/stories_strip.dart';
import '../explore.dart';
import '../feed_controller.dart';
import '../feed_models.dart';
import '../widgets/explore_widgets.dart';
import '../widgets/home_menu.dart';
import '../widgets/own_post_actions.dart';
import '../widgets/post_card.dart';
import '../widgets/report_sheet.dart';

class FeedScreen extends ConsumerStatefulWidget {
  const FeedScreen({super.key});

  @override
  ConsumerState<FeedScreen> createState() => _FeedScreenState();
}

class _FeedScreenState extends ConsumerState<FeedScreen> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels > _scroll.position.maxScrollExtent - 600) {
        ref.read(feedControllerProvider.notifier).loadMore();
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _toggleReaction(String postId) async {
    try {
      await ref.read(feedControllerProvider.notifier).toggleReaction(postId);
    } on ApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  void _postMenu(Post post, bool mine) {
    final postId = post.id;
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: Palette.cream,
      builder: (sheet) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (mine) ...ownPostTiles(sheet, context, ref, post, onDone: (_) {}),
            if (!mine)
              ListTile(
                leading: const Icon(Icons.chat_bubble_outline_rounded),
                title: Text('Message ${post.author.displayName}'),
                onTap: () {
                  Navigator.of(sheet).pop();
                  openDirectChat(context, ref, post.author.id);
                },
              ),
            if (!mine)
              ListTile(
                leading: const Icon(Icons.flag_outlined),
                title: const Text('Report post'),
                onTap: () {
                  Navigator.of(sheet).pop();
                  showReportSheet(
                    context,
                    what: 'post',
                    send: (reason, details) => ref.read(feedRepositoryProvider).report(
                          targetType: 'post',
                          targetId: postId,
                          reason: reason,
                          details: details,
                        ),
                  );
                },
              ),
            ListTile(
              leading: const Icon(Icons.close_rounded),
              title: const Text('Cancel'),
              onTap: () => Navigator.of(sheet).pop(),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final feed = ref.watch(feedControllerProvider);
    // As a later page arrives, warm the cache with its photos so they are there
    // by the time they scroll into view (decision U.1).
    ref.listen(feedControllerProvider.select((state) => state.posts.length), (was, now) {
      if (was == null || was == 0 || now <= was) return;
      prefetchImages(context, [
        for (final post in ref.read(feedControllerProvider).posts.skip(was))
          if (post.images.isNotEmpty) post.images.first.urlFor(ImageSize.medium.width),
      ]);
    });
    final auth = ref.watch(authControllerProvider);
    final me = auth is AuthSignedIn ? auth.me : null;
    final home = me?.areaLabel?.heading ?? 'Your area';
    final exploring = ref.watch(exploreProvider);
    // The header names where the phone is: away from home, the place the app
    // last sent; at home, home (decision L.1).
    final area = exploring == null
        ? home
        // An area too quiet to be named yet reads as "Around here" (decision U.4).
        : exploring.area.precision == 'generic'
            ? 'Around here'
            : exploring.area.label;
    final radius = feed.radiusKm;
    // Roughly where the phone is (decision L.4); left out when the title says it already.
    final near = ref.watch(nearProvider);
    final shownNear = near != null && near.name.toLowerCase() != area.toLowerCase() ? near : null;
    // "+ Post" until this account has posted, then just "+" (decision U.4): known
    // from this phone, a post of mine in the feed, or a starter post used.
    final hints = ref.watch(hintsProvider);
    final posted = me != null &&
        (hints.contains(Hint.posted(me.id)) ||
            me.starterPostsLeft < 3 ||
            feed.posts.any((post) => post.author.id == me.id));
    // Where the posts older than the radius's window begin (decision T.2).
    final olderFrom = firstOlderPost(feed.posts, feed.recentPostDays);
    final askButton = OutlinedButton.icon(
      onPressed: () => context.push(Routes.compose, extra: 'question'),
      style: OutlinedButton.styleFrom(minimumSize: const Size(0, 40)),
      icon: const Icon(Icons.help_outline_rounded, size: 18),
      label: const Text('Ask your neighbours something'),
    );

    return Scaffold(
      drawer: HomeMenu(area: home, radiusKm: radius),
      floatingActionButton: posted
          ? FloatingActionButton(
              onPressed: () => context.push(Routes.compose),
              tooltip: 'New post',
              backgroundColor: Palette.primary,
              foregroundColor: Palette.onPrimary,
              child: const Icon(Icons.add_rounded, size: 28),
            )
          : FloatingActionButton.extended(
              onPressed: () => context.push(Routes.compose),
              tooltip: 'New post',
              backgroundColor: Palette.primary,
              foregroundColor: Palette.onPrimary,
              icon: const Icon(Icons.add_rounded),
              label: const Text('Post'),
            ),
      body: SafeArea(
        child: RefreshIndicator(
          color: Palette.primary,
          onRefresh: () => Future.wait([
            ref.read(feedControllerProvider.notifier).refresh(),
            ref.read(storiesControllerProvider.notifier).refresh(),
          ]),
          child: CustomScrollView(
            controller: _scroll,
            physics: const AlwaysScrollableScrollPhysics(),
            slivers: [
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 18, 16, 12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Builder(
                            builder: (context) => IconButton(
                              icon: const Icon(Icons.menu_rounded),
                              tooltip: 'Menu',
                              color: Palette.ink,
                              visualDensity: VisualDensity.compact,
                              onPressed: () => Scaffold.of(context).openDrawer(),
                            ),
                          ),
                          const SizedBox(width: 4),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                // A Wrap, so on a narrow phone a long name moves the
                                // chip to the next line rather than squeezing either.
                                Wrap(
                                  spacing: 8,
                                  runSpacing: 4,
                                  crossAxisAlignment: WrapCrossAlignment.center,
                                  children: [
                                    Text(area, style: text.headlineSmall),
                                    if (shownNear != null) NearChip(place: shownNear),
                                  ],
                                ),
                                const SizedBox(height: 2),
                                // The reach, with the button that updates where it's from
                                // beside it rather than crowding the title (decision U.4).
                                ReachLine(
                                  info: Text(
                                    radius != null
                                        ? reachLabel(radius)
                                        // An unnamed area is already headed "Around here".
                                        : (area == 'Around here' ? 'Your neighbourhood' : 'Around here'),
                                    style: text.bodySmall,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      const StoriesStrip(),
                      const SizedBox(height: 10),
                      const _Shortcuts(),
                    ],
                  ),
                ),
              ),
              if (feed.loading && feed.posts.isEmpty)
                SliverFillRemaining(
                  hasScrollBody: false,
                  child: Center(child: CircularProgressIndicator(color: Palette.primary)),
                )
              else if (feed.error != null && feed.posts.isEmpty)
                SliverFillRemaining(
                  hasScrollBody: false,
                  child: _Message(
                    icon: Icons.wifi_off_rounded,
                    title: "Couldn't load the feed",
                    body: feed.error!.message,
                    action: 'Try again',
                    onAction: () => ref.read(feedControllerProvider.notifier).refresh(),
                  ),
                )
              else if (feed.posts.isEmpty)
                SliverFillRemaining(
                  hasScrollBody: false,
                  // Wherever the phone is, a post goes there: so the way on is to write one.
                  child: _Message(
                    icon: Icons.forum_outlined,
                    title: 'Nothing here yet',
                    body: exploring != null && exploring.area.precision == 'generic'
                        ? 'Be the first to post around here: a question, a recommendation, '
                            'something lost or found.'
                        : 'Be the first to post in $area: a question, a recommendation, '
                            'something lost or found.',
                    action: 'Write a post',
                    onAction: () => context.push(Routes.compose),
                  ),
                )
              else ...[
                // Nothing recent on the first page: the way on is to ask (decision T.2).
                if (olderFrom == 0)
                  SliverToBoxAdapter(
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(16, 4, 16, 14),
                      child: Column(
                        children: [
                          Text('Nothing new around here lately', style: text.bodySmall),
                          const SizedBox(height: 8),
                          askButton,
                        ],
                      ),
                    ),
                  ),
                SliverList.separated(
                  itemCount: feed.posts.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 10),
                  itemBuilder: (context, index) {
                    final post = feed.posts[index];
                    final mine = post.author.id == me?.id;
                    final card = Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      child: PostCard(
                        post: post,
                        mine: mine,
                        onReact: () => _toggleReaction(post.id),
                        onOpen: () => context.go(Routes.post(post.id)),
                        onMore: () => _postMenu(post, mine),
                        onAuthor: () => openProfile(context, ref, post.author.id),
                      ),
                    );
                    if (index != olderFrom) return card;
                    return Column(children: [const _OlderPostsDivider(), card]);
                  },
                ),
                SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
                    child: Center(
                      child: feed.loadingMore
                          ? CircularProgressIndicator(color: Palette.primary)
                          : feed.hasMore
                              ? const SizedBox.shrink()
                              // The end of the feed is a nudge to start something
                              // (decision U.4), unless the top already is.
                              : Column(
                                  children: [
                                    Text("You're all caught up", style: text.bodySmall),
                                    if (olderFrom != 0) ...[const SizedBox(height: 8), askButton],
                                  ],
                                ),
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// Above the first post older than the radius's window. The posts under it
/// are still near; they just no longer count toward the radius.
class _OlderPostsDivider extends StatelessWidget {
  const _OlderPostsDivider();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 6, 16, 16),
      child: Row(
        children: [
          Expanded(child: Divider(color: Palette.line, height: 1)),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10),
            child: Text('Older posts', style: Theme.of(context).textTheme.labelMedium?.copyWith(color: Palette.muted)),
          ),
          Expanded(child: Divider(color: Palette.line, height: 1)),
        ],
      ),
    );
  }
}

class _Message extends StatelessWidget {
  const _Message({
    required this.icon,
    required this.title,
    required this.body,
    required this.action,
    required this.onAction,
  });

  final IconData icon;
  final String title;
  final String body;
  final String action;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const HoodoraMark(size: 56),
          const SizedBox(height: 20),
          Text(title, style: text.titleLarge, textAlign: TextAlign.center),
          const SizedBox(height: 8),
          Text(body, style: text.bodyMedium?.copyWith(color: Palette.muted), textAlign: TextAlign.center),
          const SizedBox(height: 20),
          OutlinedButton(onPressed: onAction, child: Text(action)),
        ],
      ),
    );
  }
}

/// Services and Groups, one tap from Home, as chips below the stories
/// (decision U.4). The drawer keeps them too. Events joins when it has a screen.
class _Shortcuts extends StatelessWidget {
  const _Shortcuts();

  @override
  Widget build(BuildContext context) {
    Widget chip(IconData icon, String label, String route) => ActionChip(
          avatar: Icon(icon, size: 18, color: Palette.primary),
          label: Text(label),
          onPressed: () => context.go(route),
          backgroundColor: Palette.surface,
          side: BorderSide(color: Palette.lineStrong),
          visualDensity: VisualDensity.compact,
        );
    return Wrap(
      spacing: 8,
      children: [
        chip(Icons.handyman_outlined, 'Services', Routes.services),
        chip(Icons.groups_outlined, 'Groups', Routes.groups),
      ],
    );
  }
}

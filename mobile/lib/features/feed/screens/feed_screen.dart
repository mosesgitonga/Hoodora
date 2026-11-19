import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/location.dart';
import '../../../core/providers.dart';
import '../../../core/router.dart';
import '../../../core/theme.dart';
import '../../../core/widgets.dart';
import '../../auth/auth_controller.dart';
import '../../chats/start_chat.dart';
import '../../me/me_screen.dart';
import '../../profile/profile_screen.dart';
import '../../stories/stories_controller.dart';
import '../../stories/stories_strip.dart';
import '../explore.dart';
import '../feed_controller.dart';
import '../feed_models.dart';
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

  Future<void> _toggleHelpful(String postId) async {
    try {
      await ref.read(feedControllerProvider.notifier).toggleHelpful(postId);
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
    final auth = ref.watch(authControllerProvider);
    final me = auth is AuthSignedIn ? auth.me : null;
    final home = me?.areaLabel?.heading ?? 'Your area';
    final exploring = ref.watch(exploreProvider);
    // While exploring, the header names where the feed is from now.
    final area = exploring?.area.heading ?? home;
    final radius = feed.radiusKm;

    return Scaffold(
      drawer: HomeMenu(area: home, radiusKm: radius),
      floatingActionButton: FloatingActionButton(
        onPressed: () => context.push(Routes.compose),
        tooltip: 'New post',
        backgroundColor: Palette.primary,
        foregroundColor: Palette.onPrimary,
        child: const Icon(Icons.add_rounded, size: 28),
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
                                Text(area, style: text.headlineSmall),
                                const SizedBox(height: 2),
                                Text(
                                  exploring != null
                                      ? (radius == null ? 'Around you now' : 'Within ${_km(radius)} km of here')
                                      : radius == null
                                          ? 'Around you'
                                          : 'Within ${_km(radius)} km of home',
                                  style: text.bodySmall,
                                ),
                              ],
                            ),
                          ),
                          const _LocateButton(),
                        ],
                      ),
                      if (exploring != null) ...[
                        const SizedBox(height: 10),
                        _ExploringStrip(exploring: exploring, home: home),
                      ],
                      const SizedBox(height: 12),
                      const StoriesStrip(),
                      if (me != null && me.homeProvisional) ...[
                        const SizedBox(height: 12),
                        _ProvisionalHomeCard(area: home, confirmBy: me.homeConfirmBy),
                      ],
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
                  child: _Message(
                    icon: Icons.forum_outlined,
                    title: 'Nothing here yet',
                    body: 'Be the first to post in $area: a question, a recommendation, '
                        'something lost or found.',
                    action: 'Write a post',
                    onAction: () => context.push(Routes.compose),
                  ),
                )
              else ...[
                SliverList.separated(
                  itemCount: feed.posts.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 10),
                  itemBuilder: (context, index) {
                    final post = feed.posts[index];
                    final mine = post.author.id == me?.id;
                    return Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      child: PostCard(
                        post: post,
                        mine: mine,
                        onHelpful: () => _toggleHelpful(post.id),
                        onOpen: () => context.go(Routes.post(post.id)),
                        onMore: () => _postMenu(post, mine),
                        onAuthor: () => openProfile(context, ref, post.author.id),
                      ),
                    );
                  },
                ),
                SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
                    child: Center(
                      child: feed.loadingMore
                          ? CircularProgressIndicator(color: Palette.primary)
                          : Text(feed.hasMore ? '' : "You're all caught up", style: text.bodySmall),
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

  static String _km(double value) =>
      value == value.roundToDouble() ? value.toStringAsFixed(0) : value.toStringAsFixed(1);
}

/// Shown while home is provisional: the person signed up away from home and
/// should set the real one when they get there (decision M.10).
class _ProvisionalHomeCard extends StatelessWidget {
  const _ProvisionalHomeCard({required this.area, required this.confirmBy});

  final String area;
  final DateTime? confirmBy;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final by = confirmBy;
    final overdue = by != null && by.isBefore(DateTime.now());
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 8),
      decoration: BoxDecoration(
        color: Palette.surface,
        border: Border.all(color: Palette.line),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            overdue ? 'Set your home to post again' : "You're using Hoodora from $area for now",
            style: text.titleSmall,
          ),
          const SizedBox(height: 4),
          Text(
            overdue
                ? "When you're at home, set it and you can post, sell and offer services again."
                : "Set your home when you're there${by == null ? '' : ', by ${shortDate(by)}'}.",
            style: text.bodySmall?.copyWith(color: Palette.ink),
          ),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              onPressed: () => context.go(Routes.moveHome),
              child: const Text("I'm at home now"),
            ),
          ),
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


/// "Use my location now": reads GPS and, if the phone has left home's hexagon,
/// moves the feed to the one it is in.
class _LocateButton extends ConsumerStatefulWidget {
  const _LocateButton();

  @override
  ConsumerState<_LocateButton> createState() => _LocateButtonState();
}

class _LocateButtonState extends ConsumerState<_LocateButton> {
  bool _busy = false;

  Future<void> _locate() async {
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final outcome = await ref.read(exploreProvider.notifier).fromHere();
      if (outcome == ExploreOutcome.atHome) {
        messenger.showSnackBar(const SnackBar(content: Text("You're in your home area. The feed is from here.")));
      }
    } on LocationProblem catch (problem) {
      messenger.showSnackBar(SnackBar(content: Text(problem.message)));
    } on ApiException catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(error.message)));
    } catch (_) {
      messenger.showSnackBar(const SnackBar(content: Text("Couldn't read your location. Try again.")));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return IconButton(
      onPressed: _busy ? null : _locate,
      tooltip: 'Use my location now',
      color: Palette.ink,
      visualDensity: VisualDensity.compact,
      icon: _busy
          ? SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Palette.primary))
          : const Icon(Icons.my_location_rounded),
    );
  }
}

/// While the feed is from somewhere else: until when, the way back, and the way
/// to move home for good.
class _ExploringStrip extends ConsumerWidget {
  const _ExploringStrip({required this.exploring, required this.home});

  final Exploring exploring;
  final String home;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final text = Theme.of(context).textTheme;
    final until = TimeOfDay.fromDateTime(exploring.until).format(context);
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 4, 8),
      decoration: BoxDecoration(color: Palette.glowTint, borderRadius: BorderRadius.circular(12)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.explore_outlined, size: 18, color: Palette.primaryDark),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Exploring until $until. Your posts still go to $home.',
                  style: text.bodySmall?.copyWith(color: Palette.ink),
                ),
              ),
              TextButton(
                onPressed: () => ref.read(exploreProvider.notifier).backHome(),
                child: const Text('Back to home'),
              ),
            ],
          ),
          Padding(
            padding: const EdgeInsets.only(left: 26),
            child: InkWell(
              onTap: () => context.go(Routes.moveHome),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Text(
                  'Living here now? Move your home',
                  style: text.bodySmall?.copyWith(color: Palette.primary, fontWeight: FontWeight.w600),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

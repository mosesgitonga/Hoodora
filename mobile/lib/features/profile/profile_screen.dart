import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/providers.dart';
import '../../core/router.dart';
import '../../core/net_image.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import '../auth/auth_controller.dart';
import '../chats/start_chat.dart';
import '../circle/circle_button.dart';
import '../feed/feed_models.dart';
import '../feed/widgets/own_post_actions.dart';
import '../feed/widgets/post_card.dart';
import '../feed/widgets/report_sheet.dart';
import '../market/listing_models.dart';
import '../market/widgets/listing_card.dart';
import '../services/service_models.dart';
import '../services/widgets/service_cards.dart';
import 'profile_models.dart';

/// Opens someone's profile: the Me tab for myself, a page over the tabs for
/// anyone else.
void openProfile(BuildContext context, WidgetRef ref, String userId) {
  final auth = ref.read(authControllerProvider);
  if (auth is AuthSignedIn && auth.me.id == userId) {
    context.go(Routes.me);
  } else {
    context.push(Routes.person(userId));
  }
}

enum _Tab { posts, selling, services }

/// A profile: cover, photo, name, bio, and the person's posts, what they sell,
/// and what they offer. Mine has Edit and Settings; anyone else's has Message.
class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key, required this.userId});

  final String userId;

  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen> {
  Profile? _profile;
  String? _error;
  _Tab _tab = _Tab.posts;

  final List<Post> _posts = [];
  final List<Listing> _listings = [];
  final List<ServicePost> _services = [];
  final Map<_Tab, String?> _cursors = {};
  final Set<_Tab> _loaded = {};
  bool _loadingList = false;

  bool get _mine {
    final auth = ref.read(authControllerProvider);
    return auth is AuthSignedIn && auth.me.id == widget.userId;
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final profile = await ref.read(profileRepositoryProvider).profile(widget.userId);
      if (!mounted) return;
      setState(() {
        _profile = profile;
        _error = null;
        _posts.clear();
        _listings.clear();
        _services.clear();
        _cursors.clear();
        _loaded.clear();
      });
      await _loadList(_tab);
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _error = error.statusCode == 404 ? 'This profile is not available.' : error.message);
      }
    }
  }

  Future<void> _loadList(_Tab tab, {bool more = false}) async {
    if (_loadingList) return;
    setState(() => _loadingList = true);
    final repo = ref.read(profileRepositoryProvider);
    final cursor = more ? _cursors[tab] : null;
    try {
      switch (tab) {
        case _Tab.posts:
          final page = await repo.posts(widget.userId, cursor: cursor);
          _posts.addAll(page.items);
          _cursors[tab] = page.nextCursor;
        case _Tab.selling:
          final page = await repo.listings(widget.userId, cursor: cursor);
          _listings.addAll(page.items);
          _cursors[tab] = page.nextCursor;
        case _Tab.services:
          final page = await repo.services(widget.userId, cursor: cursor);
          _services.addAll(page.items);
          _cursors[tab] = page.nextCursor;
      }
      _loaded.add(tab);
    } on ApiException catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.message)));
    } finally {
      if (mounted) setState(() => _loadingList = false);
    }
  }

  void _choose(_Tab tab) {
    setState(() => _tab = tab);
    if (!_loaded.contains(tab)) _loadList(tab);
  }

  Future<void> _edit() async {
    await context.push(Routes.editProfile);
    if (mounted) await _load();
  }

  Future<void> _menu(String choice) async {
    final profile = _profile!;
    final repo = ref.read(profileRepositoryProvider);
    switch (choice) {
      case 'report':
        showReportSheet(
          context,
          what: 'person',
          send: (reason, details) => repo.report(profile.id, reason: reason, details: details),
        );
      case 'block':
        final sure = await showDialog<bool>(
          context: context,
          builder: (dialog) => AlertDialog(
            title: Text('Block ${profile.displayName}?'),
            content: const Text("You won't see each other anywhere in Hoodora, and they can't message you."),
            actions: [
              TextButton(onPressed: () => Navigator.of(dialog).pop(false), child: const Text('Cancel')),
              TextButton(
                onPressed: () => Navigator.of(dialog).pop(true),
                style: TextButton.styleFrom(foregroundColor: Palette.danger),
                child: const Text('Block'),
              ),
            ],
          ),
        );
        if (sure != true) return;
        try {
          await repo.block(profile.id);
          if (mounted) context.pop();
        } on ApiException catch (error) {
          if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.message)));
        }
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = _profile;
    final mine = _mine;
    if (profile == null) {
      return Scaffold(
        appBar: AppBar(),
        body: Center(
          child: _error == null
              ? CircularProgressIndicator(color: Palette.primary)
              : Padding(
                  padding: const EdgeInsets.all(32),
                  child: Text(
                    _error!,
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.bodyLarge,
                  ),
                ),
        ),
      );
    }
    final canPop = Navigator.of(context).canPop();

    return Scaffold(
      body: RefreshIndicator(
        color: Palette.primary,
        onRefresh: _load,
        child: CustomScrollView(
          slivers: [
            SliverToBoxAdapter(
              child: _Header(
                profile: profile,
                leading: canPop ? const _Round(child: BackButton()) : null,
                actions: [
                  if (mine)
                    _Round(
                      child: IconButton(
                        tooltip: 'Settings',
                        onPressed: () => context.go(Routes.accountSettings),
                        icon: const Icon(Icons.settings_outlined),
                      ),
                    )
                  else
                    _Round(
                      child: PopupMenuButton<String>(
                        tooltip: 'More',
                        onSelected: _menu,
                        itemBuilder: (_) => const [
                          PopupMenuItem(value: 'report', child: Text('Report')),
                          PopupMenuItem(value: 'block', child: Text('Block')),
                        ],
                      ),
                    ),
                ],
              ),
            ),
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
              sliver: SliverToBoxAdapter(child: _Details(profile: profile, mine: mine)),
            ),
            if (mine)
              const SliverPadding(
                padding: EdgeInsets.fromLTRB(16, 12, 16, 0),
                sliver: SliverToBoxAdapter(child: _TrustSignals()),
              ),
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 0),
              sliver: SliverToBoxAdapter(
                child: mine
                    ? OutlinedButton.icon(
                        onPressed: _edit,
                        icon: const Icon(Icons.edit_outlined, size: 18),
                        label: const Text('Edit profile'),
                      )
                    : Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          FilledButton.icon(
                            onPressed: () => openDirectChat(context, ref, profile.id),
                            icon: const Icon(Icons.chat_bubble_outline_rounded, size: 18),
                            label: Text('Message ${profile.displayName.split(' ').first}'),
                          ),
                          const SizedBox(height: 8),
                          CircleButton(
                            userId: profile.id,
                            firstName: profile.displayName.split(' ').first,
                            relationship: profile.relationship,
                            requestId: profile.circleRequestId,
                            onChanged: _load,
                          ),
                        ],
                      ),
              ),
            ),
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(16, 18, 16, 10),
              sliver: SliverToBoxAdapter(
                child: SegmentedButton<_Tab>(
                  showSelectedIcon: false,
                  segments: const [
                    ButtonSegment(value: _Tab.posts, label: Text('Posts')),
                    ButtonSegment(value: _Tab.selling, label: Text('Selling')),
                    ButtonSegment(value: _Tab.services, label: Text('Services')),
                  ],
                  selected: {_tab},
                  onSelectionChanged: (value) => _choose(value.single),
                ),
              ),
            ),
            ..._list(profile, mine),
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
                child: _loadingList
                    ? Center(child: CircularProgressIndicator(color: Palette.primary))
                    : _cursors[_tab] != null
                    ? TextButton(onPressed: () => _loadList(_tab, more: true), child: const Text('More'))
                    : const SizedBox.shrink(),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _ownPostMenu(Post post) {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: Palette.cream,
      builder: (sheet) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: ownPostTiles(sheet, context, ref, post, onDone: (edited) {
            if (!mounted) return;
            setState(() {
              final at = _posts.indexWhere((p) => p.id == post.id);
              if (at < 0) return;
              if (edited == null) {
                _posts.removeAt(at);
              } else {
                _posts[at] = edited;
              }
            });
          }),
        ),
      ),
    );
  }

  List<Widget> _list(Profile profile, bool mine) {
    final first = profile.displayName.split(' ').first;
    // An empty tab on my own profile offers the way to fill it (decision U.4).
    Widget empty(String text, {String? action, IconData? icon, VoidCallback? onAction}) => SliverToBoxAdapter(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(32, 24, 32, 8),
        child: Column(
          children: [
            Text(
              text,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: Palette.muted),
            ),
            if (action != null && onAction != null) ...[
              const SizedBox(height: 12),
              FilledButton.icon(
                onPressed: onAction,
                style: FilledButton.styleFrom(minimumSize: const Size(0, 40)),
                icon: Icon(icon ?? Icons.add_rounded, size: 18),
                label: Text(action),
              ),
            ],
          ],
        ),
      ),
    );
    // Saved listings and managing my own sit in my Selling tab, not the market's
    // header (decision U.4).
    final sellingLinks = SliverToBoxAdapter(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
        child: Wrap(
          spacing: 8,
          children: [
            ActionChip(
              avatar: Icon(Icons.bookmark_border_rounded, size: 18, color: Palette.primary),
              label: const Text('Saved'),
              onPressed: () => context.go(Routes.savedListings),
            ),
            ActionChip(
              avatar: Icon(Icons.storefront_outlined, size: 18, color: Palette.primary),
              label: const Text('Manage my listings'),
              onPressed: () => context.go(Routes.myListings),
            ),
          ],
        ),
      ),
    );
    if (!_loaded.contains(_tab)) return const [];
    switch (_tab) {
      case _Tab.posts:
        if (!mine && !profile.postsVisible) {
          return [empty("$first's posts are shown to neighbours nearby. You live further away.")];
        }
        if (_posts.isEmpty) {
          return [
            mine
                ? empty(
                    "You haven't posted yet. Say hello to your neighbours.",
                    action: 'Write a post',
                    onAction: () => context.push(Routes.compose),
                  )
                : empty("$first hasn't posted yet."),
          ];
        }
        return [
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            sliver: SliverList.separated(
              itemCount: _posts.length,
              separatorBuilder: (_, _) => const SizedBox(height: 10),
              itemBuilder: (context, index) {
                final post = _posts[index];
                void open() => context.go(Routes.post(post.id));
                return PostCard(
                  post: post,
                  mine: mine,
                  onOpen: open,
                  onReact: open,
                  onMore: mine ? () => _ownPostMenu(post) : null,
                );
              },
            ),
          ),
        ];
      case _Tab.selling:
        if (_listings.isEmpty) {
          return [
            if (mine) sellingLinks,
            mine
                ? empty('Nothing for sale yet.', action: 'Sell', onAction: () => context.push(Routes.sell))
                : empty('$first is not selling anything.'),
          ];
        }
        return [
          if (mine) sellingLinks,
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            sliver: SliverGrid.builder(
              itemCount: _listings.length,
              gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                maxCrossAxisExtent: 260,
                mainAxisSpacing: 10,
                crossAxisSpacing: 10,
                childAspectRatio: 0.78,
              ),
              itemBuilder: (context, index) {
                final listing = _listings[index];
                return ListingCard(listing: listing, onTap: () => context.go(Routes.listing(listing.id)));
              },
            ),
          ),
        ];
      case _Tab.services:
        if (_services.isEmpty) {
          return [
            mine
                ? empty(
                    'No services posted yet.',
                    action: 'Offer a service',
                    icon: Icons.handyman_outlined,
                    onAction: () => context.push(Routes.newService(ServiceKind.offering)),
                  )
                : empty('$first has no services posted.'),
          ];
        }
        return [
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            sliver: SliverList.separated(
              itemCount: _services.length,
              separatorBuilder: (_, _) => const SizedBox(height: 10),
              itemBuilder: (context, index) {
                final post = _services[index];
                return ServiceCard(post: post, onOpen: () => context.go(Routes.service(post.id)));
              },
            ),
          ),
        ];
    }
  }
}

/// The cover photo with the profile photo overlapping its bottom edge.
class _Header extends StatelessWidget {
  const _Header({required this.profile, required this.actions, this.leading});

  final Profile profile;
  final Widget? leading;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final coverUrl = sizeFor(profile.cover, ImageSize.medium.width);
    // Without a cover photo the gradient is only a backdrop, so it is kept short
    // (decision U.4).
    final coverHeight = coverUrl == null ? 104.0 : 170.0;
    const avatarRadius = 46.0;
    return SizedBox(
      height: coverHeight + avatarRadius,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Positioned.fill(
            bottom: avatarRadius,
            child: coverUrl == null
                ? DecoratedBox(
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        colors: [Palette.glowTint, Palette.sand],
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                      ),
                    ),
                  )
                : NetImage(coverUrl),
          ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: Row(children: [?leading, const Spacer(), ...actions]),
            ),
          ),
          Positioned(
            left: 16,
            bottom: 0,
            child: Container(
              padding: const EdgeInsets.all(3),
              decoration: BoxDecoration(color: Palette.cream, shape: BoxShape.circle),
              child: InitialsAvatar(author: profile.asAuthor, radius: avatarRadius - 3),
            ),
          ),
        ],
      ),
    );
  }
}

class _Details extends StatelessWidget {
  const _Details({required this.profile, required this.mine});

  final Profile profile;
  final bool mine;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final label = profile.areaLabel?.label;
    final facts = [
      // On my own profile, say it's what others see, so a bare "nearby" makes
      // sense (decision U.4).
      if (mine && label != null) 'Neighbours see: $label' else if (profile.where.isNotEmpty) profile.where,
      if (profile.ratingCount > 0)
        '★ ${profile.ratingAverage!.toStringAsFixed(1)} (${profile.ratingCount})'
      else if (mine)
        'Reviews appear after your first sale or job'
      else
        'No reviews yet',
      if (profile.memberSince != null) 'Joined ${_monthYear(profile.memberSince!)}',
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text(profile.displayName, style: text.headlineSmall),
            if (profile.isVerifiedNeighbour) const NeighbourBadge(long: true),
          ],
        ),
        const SizedBox(height: 4),
        Text(facts.join(' · '), style: text.bodyMedium?.copyWith(color: Palette.muted)),
        if (profile.bio != null) ...[const SizedBox(height: 10), Text(profile.bio!, style: text.bodyLarge)],
      ],
    );
  }

  static String _monthYear(DateTime date) {
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    final local = date.toLocal();
    return '${months[local.month - 1]} ${local.year}';
  }
}

/// A light disc behind a button on the cover, so it shows on any photo.
class _Round extends StatelessWidget {
  const _Round({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(4),
      child: DecoratedBox(
        decoration: BoxDecoration(color: Palette.surface, shape: BoxShape.circle),
        child: child,
      ),
    );
  }
}

/// The Me tab: my own profile.
class MyProfileScreen extends ConsumerWidget {
  const MyProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authControllerProvider);
    if (auth is! AuthSignedIn) return const Scaffold();
    return ProfileScreen(key: ValueKey(auth.me.id), userId: auth.me.id);
  }
}


/// On my own profile: what makes neighbours trust an account, and how far along
/// I am (decision U.5). From `GET /me`; nothing here is shown to anyone else.
class _TrustSignals extends ConsumerWidget {
  const _TrustSignals();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authControllerProvider);
    if (auth is! AuthSignedIn) return const SizedBox.shrink();
    final me = auth.me;
    final text = Theme.of(context).textTheme;
    final ageReached = me.badgeAccountAgeReachedAt;
    final tooNew = ageReached != null && ageReached.isAfter(DateTime.now());

    Widget line(IconData icon, String label, {Color? colour, VoidCallback? onTap}) => InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(8),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 5),
            child: Row(
              children: [
                Icon(icon, size: 18, color: colour ?? Palette.muted),
                const SizedBox(width: 8),
                Expanded(child: Text(label, style: text.bodyMedium)),
                if (onTap != null) Icon(Icons.chevron_right_rounded, size: 20, color: Palette.muted),
              ],
            ),
          ),
        );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (me.phoneNumber != null) line(Icons.verified_outlined, 'Phone verified', colour: Palette.trust),
        // A verified neighbour's badge already shows beside the name; until then,
        // how far along I am.
        if (!me.isVerifiedNeighbour) ...[
          line(
            Icons.home_outlined,
            'Neighbour badge: at home ${me.badgePresenceDays} of the ${me.badgePresenceDaysNeeded} days needed '
            '(last ${me.badgePresenceWindowDays})${tooNew ? ', from ${_dayMonth(ageReached)}' : ''}',
          ),
          if (me.vouchesReceived > 0)
            line(
              Icons.handshake_outlined,
              me.vouchesReceived == 1 ? '1 neighbour vouched for you' : '${me.vouchesReceived} neighbours vouched for you',
            ),
        ],
        line(
          Icons.group_outlined,
          me.circleCount == 1 ? '1 person in your Circle' : '${me.circleCount} people in your Circle',
          onTap: () => context.go(Routes.circle),
        ),
      ],
    );
  }

  static String _dayMonth(DateTime date) {
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    final local = date.toLocal();
    return '${local.day} ${months[local.month - 1]}';
  }
}

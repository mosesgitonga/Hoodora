import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/providers.dart';
import '../../core/router.dart';
import '../../core/theme.dart';
import '../auth/auth_controller.dart';
import '../feed/feed_models.dart';
import '../feed/widgets/post_card.dart';
import '../profile/profile_screen.dart';
import '../stories/story_models.dart';
import '../stories/story_viewer_screen.dart';
import 'circle_models.dart';

/// Your Circle: the people you keep up with wherever they live, mutual and
/// chosen. Their posts and stories shared with their Circle, the people, and the
/// requests to answer (decisions C.1–C.6).
class CircleScreen extends ConsumerStatefulWidget {
  const CircleScreen({super.key});

  @override
  ConsumerState<CircleScreen> createState() => _CircleScreenState();
}

class _CircleScreenState extends ConsumerState<CircleScreen> {
  List<Post> _posts = const [];
  String? _postsCursor;
  List<Story> _stories = const [];
  List<CircleMember> _members = const [];
  List<CircleRequest> _incoming = const [];
  List<CircleRequest> _outgoing = const [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final repo = ref.read(circleRepositoryProvider);
    try {
      final results = await Future.wait([
        repo.feed(),
        repo.stories(),
        repo.members(),
        repo.requests(incoming: true),
        repo.requests(incoming: false),
      ]);
      if (!mounted) return;
      final posts = results[0] as ResultPage<Post>;
      setState(() {
        _posts = posts.items;
        _postsCursor = posts.nextCursor;
        _stories = results[1] as List<Story>;
        _members = (results[2] as ResultPage<CircleMember>).items;
        _incoming = (results[3] as ResultPage<CircleRequest>).items;
        _outgoing = (results[4] as ResultPage<CircleRequest>).items;
        _loading = false;
        _error = null;
      });
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = error.message;
        });
      }
    }
  }

  Future<void> _morePosts() async {
    final cursor = _postsCursor;
    if (cursor == null) return;
    final page = await ref.read(circleRepositoryProvider).feed(cursor: cursor);
    if (mounted) {
      setState(() {
        _posts = [..._posts, ...page.items];
        _postsCursor = page.nextCursor;
      });
    }
  }

  Future<void> _act(Future<void> Function() action, {String? done}) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await action();
      if (done != null) messenger.showSnackBar(SnackBar(content: Text(done)));
      await _load();
    } on ApiException catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(error.message)));
    }
  }

  Future<void> _toggleReaction(Post post) async {
    final repo = ref.read(feedRepositoryProvider);
    final on = post.myReaction != null;
    void put(Post next) => setState(() => _posts = [for (final p in _posts) p.id == next.id ? next : p]);
    put(on
        ? post.copyWith(clearReaction: true, reactionCount: post.reactionCount - 1)
        : post.copyWith(myReaction: reactionKindFor(post.category), reactionCount: post.reactionCount + 1));
    try {
      if (on) {
        await repo.unreact(post.id);
      } else {
        await repo.react(post.id, reactionKindFor(post.category));
      }
    } on ApiException {
      put(post);
    }
  }

  Future<void> _remove(CircleMember member) async {
    final name = member.user.displayName.split(' ').first;
    final sure = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text('Remove $name from your Circle?'),
        content: const Text("They won't be told. They'll stop seeing posts you share with your Circle."),
        actions: [
          TextButton(onPressed: () => Navigator.of(dialog).pop(false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.of(dialog).pop(true), child: const Text('Remove')),
        ],
      ),
    );
    if (sure ?? false) {
      await _act(() => ref.read(circleRepositoryProvider).remove(member.user.id), done: 'Removed from your Circle');
    }
  }

  @override
  Widget build(BuildContext context) {
    final requestsLabel = _incoming.isEmpty ? 'Requests' : 'Requests · ${_incoming.length}';
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Your Circle'),
          bottom: TabBar(
            labelColor: Palette.primaryDark,
            indicatorColor: Palette.primary,
            tabs: [const Tab(text: 'Posts'), const Tab(text: 'People'), Tab(text: requestsLabel)],
          ),
        ),
        body: _loading
            ? Center(child: CircularProgressIndicator(color: Palette.primary))
            : _error != null
                ? _Empty(icon: Icons.wifi_off_rounded, text: _error!, action: 'Try again', onAction: _load)
                : TabBarView(children: [_postsTab(), _peopleTab(), _requestsTab()]),
      ),
    );
  }

  Widget _postsTab() {
    final auth = ref.watch(authControllerProvider);
    final myId = auth is AuthSignedIn ? auth.me.id : '';
    final groups = groupStories(_stories, myId: myId);
    return RefreshIndicator(
      color: Palette.primary,
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 32),
        children: [
          if (groups.isNotEmpty)
            SizedBox(
              height: 92,
              child: ListView(
                scrollDirection: Axis.horizontal,
                children: [
                  for (final (index, group) in groups.indexed)
                    _StoryBubble(
                      group: group,
                      onTap: () => Navigator.of(context, rootNavigator: true).push(
                        MaterialPageRoute<void>(
                          fullscreenDialog: true,
                          builder: (_) => StoryViewerScreen(groups: groups, startGroup: index),
                        ),
                      ),
                    ),
                ],
              ),
            ),
          if (_posts.isEmpty)
            const _Empty(
              icon: Icons.diversity_3_outlined,
              text: 'No Circle posts yet. When people in your Circle share a post with their '
                  'Circle, it shows here, wherever they live.',
            )
          else ...[
            for (final post in _posts)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: PostCard(
                  post: post,
                  mine: post.author.id == myId,
                  onReact: () => _toggleReaction(post),
                  onOpen: () => context.push(Routes.post(post.id)),
                  onAuthor: () => openProfile(context, ref, post.author.id),
                ),
              ),
            if (_postsCursor != null)
              TextButton(onPressed: _morePosts, child: const Text('Show more')),
          ],
        ],
      ),
    );
  }

  Widget _peopleTab() {
    final text = Theme.of(context).textTheme;
    if (_members.isEmpty) {
      return const _Empty(
        icon: Icons.group_add_outlined,
        text: 'Your Circle is empty. Add people from their profile: neighbours, family who '
            'moved away, friends from school. It always takes both of you.',
      );
    }
    return RefreshIndicator(
      color: Palette.primary,
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.symmetric(vertical: 8),
        children: [
          for (final member in _members)
            ListTile(
              leading: InitialsAvatar(author: member.user, radius: 22),
              title: Text(member.user.displayName),
              subtitle: Text(
                member.where.isEmpty ? 'In your Circle' : member.where,
                style: text.bodySmall,
              ),
              onTap: () => openProfile(context, ref, member.user.id),
              trailing: PopupMenuButton<String>(
                tooltip: 'More',
                onSelected: (_) => _remove(member),
                itemBuilder: (_) => const [PopupMenuItem(value: 'remove', child: Text('Remove from Circle'))],
              ),
            ),
        ],
      ),
    );
  }

  Widget _requestsTab() {
    final text = Theme.of(context).textTheme;
    final repo = ref.read(circleRepositoryProvider);
    if (_incoming.isEmpty && _outgoing.isEmpty) {
      return const _Empty(icon: Icons.mark_email_unread_outlined, text: 'No requests waiting.');
    }
    return RefreshIndicator(
      color: Palette.primary,
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(0, 8, 0, 32),
        children: [
          if (_incoming.isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
              child: Text('Asking you', style: text.titleSmall),
            ),
            for (final request in _incoming)
              ListTile(
                leading: InitialsAvatar(author: request.user, radius: 22),
                title: Text(request.user.displayName),
                onTap: () => openProfile(context, ref, request.user.id),
                trailing: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    // Silent: they aren't told (decision C.2).
                    TextButton(
                      style: TextButton.styleFrom(minimumSize: const Size(0, 40)),
                      onPressed: () => _act(() => repo.decline(request.id)),
                      child: const Text('Decline'),
                    ),
                    FilledButton(
                      style: FilledButton.styleFrom(minimumSize: const Size(0, 40)),
                      onPressed: () => _act(
                        () => repo.accept(request.id),
                        done: "${request.user.displayName.split(' ').first} is in your Circle",
                      ),
                      child: const Text('Accept'),
                    ),
                  ],
                ),
              ),
          ],
          if (_outgoing.isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
              child: Text('You asked', style: text.titleSmall),
            ),
            for (final request in _outgoing)
              ListTile(
                leading: InitialsAvatar(author: request.user, radius: 22),
                title: Text(request.user.displayName),
                subtitle: Text('Request sent', style: text.bodySmall),
                onTap: () => openProfile(context, ref, request.user.id),
                trailing: TextButton(
                  style: TextButton.styleFrom(minimumSize: const Size(0, 40)),
                  onPressed: () => _act(() => repo.withdraw(request.id), done: 'Request withdrawn'),
                  child: const Text('Withdraw'),
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _StoryBubble extends StatelessWidget {
  const _StoryBubble({required this.group, required this.onTap});

  final StoryGroup group;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 6),
        child: Column(
          children: [
            Container(
              padding: const EdgeInsets.all(2.5),
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                border: Border.all(color: group.allSeen ? Palette.line : Palette.primary, width: 2.5),
              ),
              child: InitialsAvatar(author: group.author, radius: 26),
            ),
            const SizedBox(height: 4),
            Text(group.author.displayName.split(' ').first, style: text.bodySmall),
          ],
        ),
      ),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty({required this.icon, required this.text, this.action, this.onAction});

  final IconData icon;
  final String text;
  final String? action;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final style = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(32, 48, 32, 32),
      child: Column(
        children: [
          Icon(icon, size: 40, color: Palette.muted),
          const SizedBox(height: 12),
          Text(text, textAlign: TextAlign.center, style: style.bodyMedium?.copyWith(color: Palette.muted)),
          if (action != null) ...[
            const SizedBox(height: 12),
            OutlinedButton(onPressed: onAction, child: Text(action!)),
          ],
        ],
      ),
    );
  }
}

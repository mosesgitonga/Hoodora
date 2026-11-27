import 'package:flutter/material.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/net_image.dart';
import '../../../core/photo_viewer.dart';
import '../../../core/theme.dart';
import '../../../core/widgets.dart';
import '../feed_models.dart';

/// A round avatar: the person's photo, or their initials while there is none
/// (or while it loads).
class InitialsAvatar extends StatelessWidget {
  const InitialsAvatar({super.key, required this.author, this.radius = 20});

  final Author author;
  final double radius;

  static const _tones = [
    Color(0xFFFBE7B5),
    Color(0xFFD6E4F7),
    Color(0xFFE8DDF5),
    Color(0xFFD7EFEA),
    Color(0xFFFDE2D5),
  ];

  @override
  Widget build(BuildContext context) {
    final tone = _tones[author.id.codeUnits.fold<int>(0, (a, b) => a + b) % _tones.length];
    final initials = CircleAvatar(
      radius: radius,
      backgroundColor: tone,
      child: Text(
        author.initials,
        // The tones are light in both modes, so the initials stay dark on them.
        style: Theme.of(context).textTheme.titleSmall?.copyWith(fontSize: radius * 0.7, color: PaletteColors.light.ink),
      ),
    );
    final url = sizeFor(author.avatar, ImageSize.small.width);
    if (url == null) return initials;
    return ClipOval(
      child: NetImage(url, width: radius * 2, height: radius * 2, placeholder: initials),
    );
  }
}

/// The line under an author's name: area · distance band · time. The generic
/// fallback label ("nearby", shown where too few people live to name the area)
/// is left out, since the distance band says as much (decision U.4). A stale
/// alert's time is written in full, "3 weeks ago" (decision T.2).
String postMeta(Post post) => [
      if (post.areaLabel.precision != 'generic') post.areaLabel.label,
      ?distanceLabel(post.distanceBucket),
      post.isStaleAlert ? timeAgoInFull(post.createdAt) : timeAgo(post.createdAt),
      if (post.editedAt != null) 'edited',
    ].join(' · ');

class CategoryTag extends StatelessWidget {
  const CategoryTag(this.category, {super.key, this.quiet = false});

  final String category;

  /// In the neutral colours whatever the category: an alert past its days.
  final bool quiet;

  @override
  Widget build(BuildContext context) {
    final (bg, ink) = switch (category) {
      _ when quiet => (Palette.sand, Palette.inkSoft),
      'alert' => (Palette.alertTint, Palette.alertInk),
      'lost_and_found' => (Palette.foundTint, Palette.foundInk),
      'question' => (Palette.trustTint, Palette.trustInk),
      'recommendation' => (Palette.recommendTint, Palette.recommendInk),
      _ => (Palette.sand, Palette.inkSoft),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(12)),
      child: Text(
        postCategories[category] ?? category,
        style: Theme.of(context).textTheme.labelSmall?.copyWith(color: ink, fontWeight: FontWeight.w600),
      ),
    );
  }
}

/// A post, as a card in the feed or at the top of its own page.
class PostCard extends StatelessWidget {
  const PostCard({
    super.key,
    required this.post,
    required this.onReact,
    this.onOpen,
    this.onMore,
    this.onAuthor,
    this.mine = false,
    this.onVote,
    this.onSeen,
  });

  final Post post;

  /// Toggles the one reaction the post's category offers (decision U.3).
  final VoidCallback onReact;
  final VoidCallback? onOpen;
  final VoidCallback? onMore;

  /// Opens the author's profile, from their photo or name.
  final VoidCallback? onAuthor;
  final bool mine;

  /// Votes in the post's poll and answers with its results. Null where voting
  /// isn't possible, such as for a visitor without an account.
  final Future<Poll> Function(String optionId)? onVote;

  /// Called once when the card is first shown, so the post's views count this
  /// person (decision F.1). Null where views aren't counted.
  final VoidCallback? onSeen;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    // Any reaction of mine counts as on: an older app may have sent another kind.
    final reacted = post.myReaction != null;
    final like = reactionKindFor(post.category) == 'like';
    final count = post.reactionCount;
    final card = Material(
      color: Palette.surface,
      borderRadius: BorderRadius.circular(16),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onOpen,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 14, 6, 6),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  GestureDetector(onTap: onAuthor, child: InitialsAvatar(author: post.author)),
                  const SizedBox(width: 10),
                  Expanded(
                    child: GestureDetector(
                      onTap: onAuthor,
                      behavior: HitTestBehavior.opaque,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Wrap(
                            spacing: 6,
                            crossAxisAlignment: WrapCrossAlignment.center,
                            children: [
                              Text(post.author.displayName, style: text.titleSmall),
                              if (post.author.isVerifiedNeighbour) const NeighbourBadge(),
                            ],
                          ),
                          Text(postMeta(post), style: text.bodySmall?.copyWith(fontSize: 12.5)),
                        ],
                      ),
                    ),
                  ),
                  // An Update needs no label; the others are worth flagging (decision U.4).
                  if (post.category != 'general') CategoryTag(post.category, quiet: post.isStaleAlert),
                  if (onMore != null)
                    IconButton(
                      onPressed: onMore,
                      tooltip: 'More',
                      icon: Icon(Icons.more_vert_rounded, color: Palette.muted),
                    )
                  else
                    const SizedBox(width: 8),
                ],
              ),
              if (mine && post.isHeld)
                Container(
                  margin: const EdgeInsets.only(top: 10, right: 8),
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: Palette.glowTint,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    'Waiting for a moderator. Only you can see this post for now.',
                    style: text.bodySmall?.copyWith(color: Palette.primaryDark),
                  ),
                ),
              Padding(
                padding: const EdgeInsets.fromLTRB(0, 10, 8, 0),
                child: Text(post.body, style: text.bodyMedium),
              ),
              if (post.poll case final poll?)
                Padding(
                  padding: const EdgeInsets.fromLTRB(0, 12, 8, 0),
                  child: PollView(key: ValueKey('poll-${post.id}'), poll: poll, onVote: onVote),
                ),
              if (post.images.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.fromLTRB(0, 10, 8, 0),
                  child: _Photos(images: post.images),
                ),
              Wrap(
                children: [
                  TextButton.icon(
                    onPressed: onReact,
                    style: TextButton.styleFrom(
                      foregroundColor: reacted ? Palette.primary : Palette.muted,
                      padding: const EdgeInsets.symmetric(horizontal: 6),
                    ),
                    icon: Icon(
                      like
                          ? (reacted ? Icons.favorite_rounded : Icons.favorite_border_rounded)
                          : (reacted ? Icons.thumb_up_alt_rounded : Icons.thumb_up_alt_outlined),
                      size: 18,
                    ),
                    // No zero counts: the label alone until someone reacts (decision U.4).
                    label: Text(switch ((like, count)) {
                      (true, 0) => 'Like',
                      (true, 1) => '1 like',
                      (true, _) => '$count likes',
                      (false, 0) => 'Helpful',
                      (false, _) => '$count helpful',
                    }),
                  ),
                  TextButton.icon(
                    onPressed: onOpen,
                    style: TextButton.styleFrom(
                      foregroundColor: Palette.muted,
                      padding: const EdgeInsets.symmetric(horizontal: 6),
                    ),
                    icon: const Icon(Icons.chat_bubble_outline_rounded, size: 18),
                    label: Text(switch (post.commentCount) {
                      0 => 'Comment',
                      1 => '1 comment',
                      final n => '$n comments',
                    }),
                  ),
                  // How many saw it, never who (decision F.1). Nothing until someone has.
                  if (post.viewCount > 0)
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 11),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.visibility_outlined, size: 17, color: Palette.muted),
                          const SizedBox(width: 6),
                          Text(
                            post.viewCount == 1 ? '1 view' : '${_compact(post.viewCount)} views',
                            style: text.labelLarge?.copyWith(color: Palette.muted),
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
    final seen = onSeen;
    return seen == null ? card : _SeenOnce(onSeen: seen, child: card);
  }
}

/// 1234 as "1.2K", for a view count.
String _compact(int n) {
  if (n < 1000) return '$n';
  if (n < 1000000) return '${(n / 1000).toStringAsFixed(n < 10000 ? 1 : 0)}K';
  return '${(n / 1000000).toStringAsFixed(1)}M';
}

/// Calls [onSeen] once, when its child is first built on screen.
class _SeenOnce extends StatefulWidget {
  const _SeenOnce({required this.onSeen, required this.child});

  final VoidCallback onSeen;
  final Widget child;

  @override
  State<_SeenOnce> createState() => _SeenOnceState();
}

class _SeenOnceState extends State<_SeenOnce> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) widget.onSeen();
    });
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// A post's poll (decision F.1): its answers to tap, then each answer's share
/// once voted. Votes are anonymous and final, so there is no "change vote", and
/// nothing says which answer was chosen.
class PollView extends StatefulWidget {
  const PollView({super.key, required this.poll, this.onVote});

  final Poll poll;
  final Future<Poll> Function(String optionId)? onVote;

  @override
  State<PollView> createState() => _PollViewState();
}

class _PollViewState extends State<PollView> {
  late Poll _poll = widget.poll;
  bool _busy = false;

  @override
  void didUpdateWidget(PollView old) {
    super.didUpdateWidget(old);
    // A fresher copy from the server (a refresh, or another screen) wins, unless
    // it knows less than this one: votes only ever add up.
    if (widget.poll != old.poll && widget.poll.totalVotes >= _poll.totalVotes) _poll = widget.poll;
  }

  Future<void> _vote(PollOption option) async {
    final onVote = widget.onVote;
    if (onVote == null || _busy) return;
    setState(() => _busy = true);
    try {
      final poll = await onVote(option.id);
      if (mounted) setState(() => _poll = poll);
    } on ApiException catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final poll = _poll;
    final canVote = !poll.resultsVisible && !poll.closed && widget.onVote != null;
    final total = poll.totalVotes;
    final top = poll.options.fold<int>(0, (best, option) => (option.votes ?? 0) > best ? option.votes ?? 0 : best);
    final footer = [
      total == 1 ? '1 vote' : '$total votes',
      if (poll.voted) 'You voted',
      poll.closed ? 'Final results' : pollClosesIn(poll.closesAt),
    ].join(' · ');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final option in poll.options)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: poll.resultsVisible
                ? _result(context, option, total, leading: total > 0 && option.votes == top)
                : OutlinedButton(
                    onPressed: canVote && !_busy ? () => _vote(option) : null,
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Palette.primary,
                      side: BorderSide(color: Palette.primary.withValues(alpha: 0.5)),
                      minimumSize: const Size.fromHeight(44),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                    child: Text(option.text, textAlign: TextAlign.center),
                  ),
          ),
        Text(footer, style: text.bodySmall?.copyWith(fontSize: 12.5)),
      ],
    );
  }

  Widget _result(BuildContext context, PollOption option, int total, {required bool leading}) {
    final text = Theme.of(context).textTheme;
    final votes = option.votes ?? 0;
    final share = total == 0 ? 0.0 : votes / total;
    final weight = leading ? FontWeight.w700 : FontWeight.w500;
    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: Container(
        constraints: const BoxConstraints(minHeight: 44),
        color: Palette.sand,
        child: Stack(
          children: [
            Positioned.fill(
              child: FractionallySizedBox(
                alignment: Alignment.centerLeft,
                widthFactor: share,
                child: ColoredBox(color: leading ? Palette.glowTint : Palette.line),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
              child: Row(
                children: [
                  Expanded(child: Text(option.text, style: text.bodyMedium?.copyWith(fontWeight: weight))),
                  const SizedBox(width: 8),
                  Text('${(share * 100).round()}%', style: text.bodyMedium?.copyWith(fontWeight: weight)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Photos extends StatelessWidget {
  const _Photos({required this.images});

  final List<PostImage> images;

  @override
  Widget build(BuildContext context) {
    if (images.length == 1) {
      return ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: AspectRatio(aspectRatio: 4 / 3, child: _photo(context, 0)),
      );
    }
    return SizedBox(
      height: 160,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: images.length,
        separatorBuilder: (_, _) => const SizedBox(width: 8),
        itemBuilder: (_, index) => ClipRRect(
          borderRadius: BorderRadius.circular(12),
          child: SizedBox(width: 200, child: _photo(context, index)),
        ),
      ),
    );
  }

  /// Tapping a photo opens it full screen, with the post's others beside it
  /// (decision U.6).
  Widget _photo(BuildContext context, int index) => GestureDetector(
        onTap: () => openPhotos(context, [for (final image in images) image.urlsByWidth], initial: index),
        child: NetImage(
          images[index].urlFor(ImageSize.medium.width),
          error: ColoredBox(
            color: Palette.sand,
            child: Center(child: Icon(Icons.broken_image_outlined, color: Palette.muted)),
          ),
        ),
      );
}

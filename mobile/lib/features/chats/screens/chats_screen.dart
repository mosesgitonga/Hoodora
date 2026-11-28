import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/providers.dart';
import '../../../core/router.dart';
import '../../../core/theme.dart';
import '../../../core/widgets.dart';
import '../../auth/auth_controller.dart';
import '../../feed/feed_models.dart';
import '../../feed/widgets/post_card.dart';
import '../../profile/profile_screen.dart';
import '../chat_models.dart';
import '../chats_controller.dart';
import '../typing.dart';

/// Which chats the inbox shows.
enum ChatFilter { all, unread, groups, requests }

/// The Chats tab: the inbox, searched or filtered, and the requests waiting on
/// me (decision P.2).
class ChatsScreen extends ConsumerStatefulWidget {
  const ChatsScreen({super.key});

  @override
  ConsumerState<ChatsScreen> createState() => _ChatsScreenState();
}

class _ChatsScreenState extends ConsumerState<ChatsScreen> {
  final _search = TextEditingController();
  var _filter = ChatFilter.all;
  var _searching = false;
  var _query = '';

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  void _closeSearch() => setState(() {
        _searching = false;
        _query = '';
        _search.clear();
      });

  @override
  Widget build(BuildContext context) {
    final chats = ref.watch(chatsControllerProvider);
    final requests = chats.requests.length;
    final unread = chats.chats.where((c) => c.unreadCount > 0).length;
    final hasGroups = chats.chats.any((c) => c.isGroup);
    // A filter whose chip went away shows everything instead.
    final filter = _filter == ChatFilter.groups && !hasGroups ? ChatFilter.all : _filter;

    return PopScope(
      canPop: !_searching,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _closeSearch();
      },
      child: Scaffold(
        body: SafeArea(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(height: 60, child: _searching ? _searchBar() : _titleBar()),
              SizedBox(
                height: 42,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  children: [
                    _FilterChip('All', selected: filter == ChatFilter.all, onTap: () => _show(ChatFilter.all)),
                    _FilterChip(
                      unread == 0 ? 'Unread' : 'Unread · $unread',
                      selected: filter == ChatFilter.unread,
                      onTap: () => _show(ChatFilter.unread),
                    ),
                    if (hasGroups)
                      _FilterChip('Groups', selected: filter == ChatFilter.groups, onTap: () => _show(ChatFilter.groups)),
                    _FilterChip(
                      requests == 0 ? 'Requests' : 'Requests · $requests',
                      selected: filter == ChatFilter.requests,
                      onTap: () => _show(ChatFilter.requests),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 4),
              Expanded(
                child: RefreshIndicator(
                  color: Palette.primary,
                  onRefresh: () => ref.read(chatsControllerProvider.notifier).refresh(),
                  child: filter == ChatFilter.requests
                      ? _Requests(
                          chats: chats,
                          query: _query,
                          onAccepted: () => setState(() => _filter = ChatFilter.all),
                        )
                      : _Inbox(chats: chats, filter: filter, query: _query),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _show(ChatFilter filter) => setState(() => _filter = filter);

  Widget _titleBar() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 8, 4),
      child: Row(
        children: [
          Expanded(child: Text('Chats', style: Theme.of(context).textTheme.headlineSmall)),
          IconButton(
            tooltip: 'Search chats',
            onPressed: () => setState(() => _searching = true),
            icon: Icon(Icons.search_rounded, color: Palette.ink),
          ),
        ],
      ),
    );
  }

  Widget _searchBar() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 8, 16, 4),
      child: Row(
        children: [
          IconButton(
            tooltip: 'Close search',
            onPressed: _closeSearch,
            icon: Icon(Icons.arrow_back_rounded, color: Palette.ink),
          ),
          Expanded(
            child: TextField(
              controller: _search,
              autofocus: true,
              textInputAction: TextInputAction.search,
              onChanged: (value) => setState(() => _query = value.trim()),
              decoration: InputDecoration(
                hintText: 'Search names and messages',
                isDense: true,
                prefixIcon: Icon(Icons.search_rounded, size: 20, color: Palette.muted),
                suffixIcon: _query.isEmpty
                    ? null
                    : IconButton(
                        tooltip: 'Clear',
                        onPressed: () => setState(() {
                          _search.clear();
                          _query = '';
                        }),
                        icon: Icon(Icons.close_rounded, size: 20, color: Palette.muted),
                      ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _FilterChip extends StatelessWidget {
  const _FilterChip(this.label, {required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ChoiceChip(
        label: Text(label),
        selected: selected,
        onSelected: (_) => onTap(),
        visualDensity: VisualDensity.compact,
        // Colours from the theme's chip style: orange and white when selected.
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(17)),
      ),
    );
  }
}

/// Whether [conversation] matches what was typed into search: its name, or
/// the text of its last message.
bool matchesSearch(Conversation conversation, String query) {
  if (query.isEmpty) return true;
  final wanted = query.toLowerCase();
  if (conversation.name.toLowerCase().contains(wanted)) return true;
  final last = conversation.lastMessage;
  return last != null && !last.deleted && (last.body ?? '').toLowerCase().contains(wanted);
}

class _Inbox extends ConsumerWidget {
  const _Inbox({required this.chats, required this.filter, required this.query});

  final ChatsState chats;
  final ChatFilter filter;
  final String query;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authControllerProvider);
    final myId = auth is AuthSignedIn ? auth.me.id : null;
    if (chats.loading && chats.chats.isEmpty) {
      return Center(child: CircularProgressIndicator(color: Palette.primary));
    }
    if (chats.error != null && chats.chats.isEmpty) {
      return _Empty(
        title: "Couldn't load your chats",
        body: chats.error!.message,
        action: 'Try again',
        onAction: () => ref.read(chatsControllerProvider.notifier).refresh(),
      );
    }
    if (chats.chats.isEmpty) {
      return const _Empty(
        title: 'No chats yet',
        body: 'Message a neighbour from one of their posts. Your conversations will be here.',
      );
    }
    final shown = [
      for (final c in chats.chats)
        if ((filter != ChatFilter.unread || c.unreadCount > 0) &&
            (filter != ChatFilter.groups || c.isGroup) &&
            matchesSearch(c, query))
          c,
    ];
    if (shown.isEmpty) {
      return query.isNotEmpty
          ? _Empty(title: 'No chats found', body: 'Nothing matches "$query".')
          : const _Empty(title: 'All caught up', body: "You've read every message.");
    }
    return NotificationListener<ScrollNotification>(
      onNotification: (n) {
        if (n.metrics.pixels > n.metrics.maxScrollExtent - 400) {
          ref.read(chatsControllerProvider.notifier).loadMore();
        }
        return false;
      },
      child: ListView.builder(
        physics: const AlwaysScrollableScrollPhysics(),
        itemCount: shown.length,
        itemBuilder: (context, index) {
          final conversation = shown[index];
          return _ChatRow(
            conversation: conversation,
            myId: myId,
            onTap: () => context.go(Routes.conversation(conversation.id)),
            onLongPress: () => _rowMenu(context, ref, conversation),
          );
        },
      ),
    );
  }

  Future<void> _rowMenu(BuildContext context, WidgetRef ref, Conversation conversation) async {
    HapticFeedback.selectionClick();
    final controller = ref.read(chatsControllerProvider.notifier);
    final messenger = ScaffoldMessenger.of(context);
    Future<void> attempt(Future<void> Function() action) async {
      try {
        await action();
      } on ApiException catch (error) {
        messenger.showSnackBar(SnackBar(content: Text(error.message)));
      }
    }

    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: Palette.cream,
      builder: (sheet) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: conversationAvatar(conversation, radius: 18),
              title: Text(conversation.name, style: Theme.of(sheet).textTheme.titleSmall),
            ),
            Divider(height: 1, color: Palette.line),
            if (conversation.unreadCount > 0)
              ListTile(
                leading: const Icon(Icons.mark_chat_read_outlined),
                title: const Text('Mark as read'),
                onTap: () {
                  Navigator.of(sheet).pop();
                  attempt(() => controller.markAllRead(conversation));
                },
              ),
            ListTile(
              leading: Icon(conversation.muted ? Icons.notifications_active_outlined : Icons.notifications_off_outlined),
              title: Text(conversation.muted ? 'Unmute' : 'Mute'),
              subtitle: conversation.muted ? null : const Text('No notifications from this chat'),
              onTap: () {
                Navigator.of(sheet).pop();
                attempt(() => controller.setMuted(conversation, !conversation.muted));
              },
            ),
            if (conversation.otherUser != null)
              ListTile(
                leading: const Icon(Icons.person_outline_rounded),
                title: const Text('View profile'),
                onTap: () {
                  Navigator.of(sheet).pop();
                  openProfile(context, ref, conversation.otherUser!.id);
                },
              ),
          ],
        ),
      ),
    );
  }
}

/// An avatar for a conversation: the other person's, or the group's initials.
Widget conversationAvatar(Conversation conversation, {double radius = 26}) => InitialsAvatar(
      radius: radius,
      author: conversation.otherUser ??
          Author(id: conversation.id, displayName: conversation.name, isVerifiedNeighbour: false),
    );

/// The line under a chat's name: its last message, said briefly.
String inboxPreview(Conversation conversation, {String? myId}) {
  final last = conversation.lastMessage;
  if (last == null) return conversation.isRequestSent ? 'Request sent' : 'No messages yet';
  if (last.deleted || last.isSystem) return messagePreview(last);
  final text = last.isPhoto ? 'Photo' : (last.body ?? '');
  final mine = myId != null && last.sender?.id == myId;
  if (!conversation.isGroup) return text;
  if (mine) return 'You: $text';
  final sender = last.sender;
  return sender == null ? text : '${firstName(sender.displayName)}: $text';
}

class _ChatRow extends ConsumerWidget {
  const _ChatRow({
    required this.conversation,
    required this.myId,
    required this.onTap,
    required this.onLongPress,
  });

  final Conversation conversation;
  final String? myId;
  final VoidCallback onTap;
  final VoidCallback onLongPress;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final text = Theme.of(context).textTheme;
    final typing = typingLine(
      ref.watch(typingProvider.select((all) => all[conversation.id])),
      group: false,
    );
    final unread = conversation.unreadCount;
    final last = conversation.lastMessage;
    final mine = last != null && myId != null && last.sender?.id == myId && !last.isSystem && !last.deleted;
    final otherRead = conversation.otherLastReadSeq;
    final seen = mine && otherRead != null && last.seq <= otherRead;
    final topic = conversation.listingId != null
        ? Icons.sell_outlined
        : (conversation.servicePostId != null ? Icons.handyman_outlined : null);
    final previewInk = unread > 0 ? Palette.ink : Palette.muted;

    return InkWell(
      onTap: onTap,
      onLongPress: onLongPress,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(
          children: [
            conversationAvatar(conversation),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          conversation.name,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: text.titleSmall?.copyWith(
                            fontSize: 15.5,
                            fontWeight: unread > 0 ? FontWeight.w700 : null,
                          ),
                        ),
                      ),
                      if (conversation.muted)
                        Padding(
                          padding: const EdgeInsets.only(right: 4),
                          child: Icon(Icons.notifications_off_outlined, size: 15, color: Palette.muted),
                        ),
                      Text(
                        inboxTime(conversation.activeAt),
                        style: text.bodySmall?.copyWith(
                          fontSize: 12.5,
                          color: unread > 0 && !conversation.muted ? Palette.primary : Palette.muted,
                          fontWeight: unread > 0 ? FontWeight.w600 : null,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 3),
                  Row(
                    children: [
                      if (typing != null)
                        Expanded(
                          child: Text(
                            typing,
                            maxLines: 1,
                            style: text.bodyMedium?.copyWith(
                              fontSize: 14,
                              color: Palette.primary,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        )
                      else ...[
                        if (mine && !conversation.isGroup)
                          Padding(
                            padding: const EdgeInsets.only(right: 3),
                            child: Icon(
                              seen ? Icons.done_all_rounded : Icons.done_rounded,
                              size: 16,
                              color: seen ? Palette.primary : Palette.muted,
                              semanticLabel: seen ? 'Read' : 'Sent',
                            ),
                          ),
                        if (topic != null)
                          Padding(
                            padding: const EdgeInsets.only(right: 3),
                            child: Icon(topic, size: 15, color: Palette.muted),
                          ),
                        if (last != null && last.isPhoto && !last.deleted)
                          Padding(
                            padding: const EdgeInsets.only(right: 3),
                            child: Icon(Icons.photo_camera_outlined, size: 15, color: previewInk),
                          ),
                        Expanded(
                          child: Text(
                            inboxPreview(conversation, myId: myId),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: text.bodyMedium?.copyWith(
                              fontSize: 14,
                              color: previewInk,
                              fontWeight: unread > 0 ? FontWeight.w600 : null,
                              fontStyle: last?.deleted == true ? FontStyle.italic : null,
                            ),
                          ),
                        ),
                      ],
                      if (unread > 0) ...[
                        const SizedBox(width: 8),
                        _Count(unread, muted: conversation.muted),
                      ],
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Count extends StatelessWidget {
  const _Count(this.count, {this.muted = false});

  final int count;
  final bool muted;

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(minWidth: 22),
      height: 22,
      padding: const EdgeInsets.symmetric(horizontal: 6),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: muted ? Palette.lineStrong : Palette.primary,
        borderRadius: BorderRadius.circular(11),
      ),
      child: Text(
        count > 99 ? '99+' : '$count',
        style: const TextStyle(color: Palette.onPrimary, fontSize: 12, fontWeight: FontWeight.w600),
      ),
    );
  }
}

class _Requests extends ConsumerWidget {
  const _Requests({required this.chats, required this.query, required this.onAccepted});

  final ChatsState chats;
  final String query;

  /// Back to the inbox, where the accepted conversation now is.
  final VoidCallback onAccepted;

  Future<void> _respond(BuildContext context, WidgetRef ref, Conversation c, bool accept) async {
    final repo = ref.read(chatRepositoryProvider);
    try {
      final updated = c.isInvitation
          ? await repo.respondToInvitation(c.id, accept: accept)
          : await repo.respondToRequest(c.id, accept: accept);
      ref.read(chatsControllerProvider.notifier).put(updated);
      if (accept && context.mounted) {
        onAccepted();
        context.go(Routes.conversation(c.id));
      }
    } on ApiException catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final text = Theme.of(context).textTheme;
    if (chats.loading && chats.requests.isEmpty) {
      return Center(child: CircularProgressIndicator(color: Palette.primary));
    }
    final shown = [for (final c in chats.requests) if (matchesSearch(c, query)) c];
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
      children: [
        Text(
          "People you haven't talked to yet, and group chats you've been invited to. "
          'Someone new can send one message until you reply.',
          style: text.bodyMedium?.copyWith(color: Palette.muted, fontSize: 13.5),
        ),
        const SizedBox(height: 12),
        if (shown.isEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 48),
            child: Text(
              chats.requests.isEmpty ? 'No requests' : 'No requests match "$query"',
              textAlign: TextAlign.center,
              style: text.titleMedium,
            ),
          ),
        for (final c in shown)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Material(
              color: Palette.surface,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14),
                side: BorderSide(color: Palette.line),
              ),
              child: InkWell(
                borderRadius: BorderRadius.circular(14),
                onTap: () => context.go(Routes.conversation(c.id)),
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(
                        children: [
                          conversationAvatar(c, radius: 20),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(c.name, style: text.titleSmall),
                                Text(
                                  c.isInvitation
                                      ? 'Invited you to a group chat · ${c.memberCount} members'
                                      : timeAgo(c.activeAt),
                                  style: text.bodySmall?.copyWith(fontSize: 12.5),
                                ),
                                if (c.requesterNewToArea) const NewToAreaChip(),
                              ],
                            ),
                          ),
                        ],
                      ),
                      if (!c.isInvitation && c.lastMessage != null) ...[
                        const SizedBox(height: 10),
                        Text(messagePreview(c.lastMessage!), style: text.bodyMedium),
                      ],
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          Expanded(
                            child: OutlinedButton(
                              onPressed: () => _respond(context, ref, c, false),
                              child: const Text('Decline'),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: FilledButton(
                              onPressed: () => _respond(context, ref, c, true),
                              child: const Text('Accept'),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty({required this.title, required this.body, this.action, this.onAction});

  final String title;
  final String body;
  final String? action;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: constraints.maxHeight),
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const HoodoraMark(size: 56),
                const SizedBox(height: 20),
                Text(title, style: text.titleLarge, textAlign: TextAlign.center),
                const SizedBox(height: 8),
                Text(
                  body,
                  style: text.bodyMedium?.copyWith(color: Palette.muted),
                  textAlign: TextAlign.center,
                ),
                if (action != null) ...[
                  const SizedBox(height: 20),
                  OutlinedButton(onPressed: onAction, child: Text(action!)),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

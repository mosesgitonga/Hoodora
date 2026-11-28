import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/providers.dart';
import '../../../core/router.dart';
import '../../../core/net_image.dart';
import '../../../core/photo_viewer.dart';
import '../../../core/theme.dart';
import '../../../core/widgets.dart';
import '../../auth/auth_controller.dart';
import '../../feed/widgets/report_sheet.dart';
import '../../market/listing_models.dart';
import '../../profile/profile_screen.dart';
import '../../market/widgets/listing_card.dart';
import '../../services/service_models.dart';
import '../chat_models.dart';
import '../conversation_controller.dart';
import '../message_text.dart';
import '../typing.dart';
import 'chats_screen.dart';

/// Messages from one person this close together read as one run: tighter, and
/// only the last has a tail.
const _runGap = Duration(minutes: 5);

/// One conversation: its messages, newest at the bottom, and a box to reply.
class ConversationScreen extends ConsumerStatefulWidget {
  const ConversationScreen({super.key, required this.conversationId});

  final String conversationId;

  @override
  ConsumerState<ConversationScreen> createState() => _ConversationScreenState();
}

class _ConversationScreenState extends ConsumerState<ConversationScreen> {
  final _text = TextEditingController();
  final _scroll = ScrollController();
  final _focus = FocusNode();
  final _keys = <String, GlobalKey>{};

  /// The message being answered, shown above the box.
  Message? _replyTo;
  bool _hasText = false;

  /// Scrolled up, away from the newest message; and the newest held then, to
  /// count what arrived since.
  bool _away = false;
  int _awaySeq = 0;

  /// A message flashed after jumping to it from a reply.
  String? _flashed;
  Timer? _flashTimer;

  ConversationController get _controller =>
      ref.read(conversationControllerProvider(widget.conversationId).notifier);

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
    _text.addListener(_onText);
  }

  @override
  void dispose() {
    _flashTimer?.cancel();
    _text.dispose();
    _scroll.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _onScroll() {
    final position = _scroll.position;
    // The list runs bottom-up, so the far end is the oldest message.
    if (position.pixels > position.maxScrollExtent - 400) _controller.loadEarlier();
    final away = position.pixels > 300;
    if (away != _away) {
      setState(() {
        _away = away;
        _awaySeq = ref.read(conversationControllerProvider(widget.conversationId)).lastSeq;
      });
    }
  }

  void _onText() {
    final hasText = _text.text.trim().isNotEmpty;
    if (hasText != _hasText) setState(() => _hasText = hasText);
    final conversation = ref.read(conversationControllerProvider(widget.conversationId)).conversation;
    // "typing…" only where the other side has accepted, as with read receipts.
    if (hasText && conversation != null && conversation.state == 'active') {
      ref.read(realtimeProvider).typing(widget.conversationId);
    }
  }

  void _toast(String message) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  /// Runs [action], showing the server's message if it fails. True on success.
  Future<bool> _attempt(Future<void> Function() action) async {
    try {
      await action();
      return true;
    } on ApiException catch (error) {
      _toast(error.message);
      return false;
    }
  }

  void _send() {
    final body = _text.text.trim();
    if (body.isEmpty) return;
    _text.clear();
    _controller.sendText(body, replyTo: _replyTo);
    setState(() => _replyTo = null);
    _jumpToLatest(animate: false);
  }

  Future<void> _attach() async {
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      backgroundColor: Palette.cream,
      builder: (sheet) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined),
              title: const Text('Take a photo'),
              onTap: () => Navigator.of(sheet).pop(ImageSource.camera),
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: const Text('Choose from gallery'),
              onTap: () => Navigator.of(sheet).pop(ImageSource.gallery),
            ),
          ],
        ),
      ),
    );
    if (source == null) return;
    final picked = await ImagePicker().pickImage(source: source, maxWidth: 2048, imageQuality: 85);
    if (picked == null) return;
    final bytes = await picked.readAsBytes();
    final replyTo = _replyTo;
    if (mounted) setState(() => _replyTo = null);
    _jumpToLatest(animate: false);
    await _controller.sendPhoto(bytes, replyTo: replyTo);
  }

  void _reply(Message message) {
    HapticFeedback.selectionClick();
    setState(() => _replyTo = message);
    _focus.requestFocus();
  }

  void _jumpToLatest({bool animate = true}) {
    if (!_scroll.hasClients) return;
    if (animate) {
      _scroll.animateTo(0, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
    } else {
      _scroll.jumpTo(0);
    }
  }

  /// Scrolls to [messageId] and flashes it. Older messages are built only as
  /// they come into view, so it scrolls a screen at a time until it finds it.
  Future<void> _scrollTo(String messageId) async {
    for (var step = 0; step < 30 && mounted; step++) {
      final target = _keys[messageId]?.currentContext;
      if (target != null && target.mounted) {
        await Scrollable.ensureVisible(target, alignment: 0.5, duration: const Duration(milliseconds: 250));
        _flashTimer?.cancel();
        setState(() => _flashed = messageId);
        _flashTimer = Timer(const Duration(milliseconds: 1200), () {
          if (mounted) setState(() => _flashed = null);
        });
        return;
      }
      if (!_scroll.hasClients) return;
      final position = _scroll.position;
      if (position.pixels >= position.maxScrollExtent) return;
      _scroll.jumpTo((position.pixels + position.viewportDimension * 0.8).clamp(0, position.maxScrollExtent));
      await WidgetsBinding.instance.endOfFrame;
    }
  }

  Future<bool> _confirm(String title, String body, String action) async {
    final answer = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text(title),
        content: Text(body),
        actions: [
          TextButton(onPressed: () => Navigator.of(dialog).pop(false), child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.of(dialog).pop(true),
            style: TextButton.styleFrom(foregroundColor: Palette.danger),
            child: Text(action),
          ),
        ],
      ),
    );
    return answer ?? false;
  }

  void _messageMenu(Message message, {required bool mine, required bool canReply}) {
    if (message.isSystem || message.deleted) return;
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: Palette.cream,
      builder: (sheet) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (message.sendState == SendState.failed) ...[
              if (message.error != null)
                ListTile(
                  leading: const Icon(Icons.info_outline_rounded),
                  title: Text(message.error!),
                ),
              // Sending a refused message again as it is would fail the same way.
              if (!message.refused)
                ListTile(
                  leading: const Icon(Icons.refresh_rounded),
                  title: const Text('Try again'),
                  onTap: () {
                    Navigator.of(sheet).pop();
                    _controller.retry(message.localId!);
                  },
                ),
              ListTile(
                leading: const Icon(Icons.delete_outline_rounded),
                title: const Text("Don't send"),
                onTap: () {
                  Navigator.of(sheet).pop();
                  _controller.discard(message.localId!);
                },
              ),
            ],
            if (canReply && !message.isPending)
              ListTile(
                leading: const Icon(Icons.reply_rounded),
                title: const Text('Reply'),
                onTap: () {
                  Navigator.of(sheet).pop();
                  _reply(message);
                },
              ),
            if (message.body != null)
              ListTile(
                leading: const Icon(Icons.copy_rounded),
                title: const Text('Copy'),
                onTap: () {
                  Navigator.of(sheet).pop();
                  Clipboard.setData(ClipboardData(text: message.body!));
                },
              ),
            if (mine && !message.isPending)
              ListTile(
                leading: Icon(Icons.delete_outline_rounded, color: Palette.danger),
                title: const Text('Delete for everyone'),
                onTap: () async {
                  Navigator.of(sheet).pop();
                  if (await _confirm('Delete this message?',
                      'It will say "Message deleted" for everyone in the chat.', 'Delete')) {
                    await _attempt(() => _controller.delete(message));
                  }
                },
              ),
            if (!mine)
              ListTile(
                leading: const Icon(Icons.flag_outlined),
                title: const Text('Report message'),
                onTap: () {
                  Navigator.of(sheet).pop();
                  showReportSheet(
                    context,
                    what: 'message',
                    send: (reason, details) => _controller.report(message, reason: reason, details: details),
                  );
                },
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _menu(String choice, Conversation conversation) async {
    switch (choice) {
      case 'mute':
        await _attempt(() => _controller.setMuted(!conversation.muted));
      case 'block':
        final name = conversation.otherUser?.displayName ?? 'this person';
        if (await _confirm('Block $name?',
                "You won't see each other anywhere in Hoodora, and they can't message you.", 'Block') &&
            await _attempt(_controller.blockOther) &&
            mounted) {
          context.go(Routes.chats);
        }
      case 'leave':
        if (await _confirm('Leave ${conversation.name}?',
                "You won't get its messages any more. Someone would have to add you again.", 'Leave') &&
            await _attempt(_controller.leave) &&
            mounted) {
          context.go(Routes.chats);
        }
    }
  }

  Future<void> _blockAndReport() async {
    var done = false;
    await showReportSheet(
      context,
      what: 'request',
      send: (reason, details) async {
        await _controller.blockAndReport(reason: reason, details: details);
        done = true;
      },
    );
    if (done && mounted) context.go(Routes.chats);
  }

  /// Whether the box to write in is showing: not while a request waits on me,
  /// nor while mine waits on them.
  bool _canWrite(Conversation conversation, ConversationState state, String? myId) =>
      !conversation.awaitsMe &&
      !(conversation.isRequestSent && state.messages.any((m) => m.sender?.id == myId && !m.isPending));

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final state = ref.watch(conversationControllerProvider(widget.conversationId));
    final auth = ref.watch(authControllerProvider);
    final myId = auth is AuthSignedIn ? auth.me.id : null;
    final conversation = state.conversation;
    final typing = conversation == null
        ? null
        : typingLine(
            ref.watch(typingProvider.select((all) => all[widget.conversationId])),
            group: conversation.isGroup,
            names: state.names,
          );
    final newSinceAway = _away
        ? state.messages.where((m) => !m.isPending && m.seq > _awaySeq && m.sender?.id != myId).length
        : 0;

    return Scaffold(
      backgroundColor: const Color(0xFFF7EDE4),
      appBar: AppBar(
        backgroundColor: Palette.surface,
        titleSpacing: 0,
        title: conversation == null
            ? null
            : GestureDetector(
                onTap: conversation.otherUser == null
                    ? null
                    : () => openProfile(context, ref, conversation.otherUser!.id),
                behavior: HitTestBehavior.opaque,
                child: Row(
                  children: [
                    conversationAvatar(conversation, radius: 18),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(conversation.name,
                              maxLines: 1, overflow: TextOverflow.ellipsis, style: text.titleMedium),
                          if (typing != null)
                            Text(
                              typing,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: text.bodySmall?.copyWith(fontSize: 12.5, color: Palette.primary),
                            )
                          else if (conversation.isGroup || conversation.muted)
                            Text(
                              [
                                if (conversation.isGroup) '${conversation.memberCount} members',
                                if (conversation.muted) 'Muted',
                              ].join(' · '),
                              style: text.bodySmall?.copyWith(fontSize: 12.5),
                            ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
        actions: [
          if (conversation != null && !conversation.awaitsMe)
            PopupMenuButton<String>(
              tooltip: 'More',
              onSelected: (choice) => _menu(choice, conversation),
              itemBuilder: (_) => [
                PopupMenuItem(value: 'mute', child: Text(conversation.muted ? 'Unmute' : 'Mute')),
                if (conversation.otherUser != null)
                  PopupMenuItem(value: 'block', child: Text('Block ${conversation.otherUser!.displayName}')),
                if (conversation.isGroup) const PopupMenuItem(value: 'leave', child: Text('Leave group')),
              ],
            ),
        ],
      ),
      body: Column(
        children: [
          if (conversation?.safetyNotice != null)
            Container(
              width: double.infinity,
              margin: const EdgeInsets.fromLTRB(12, 10, 12, 0),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: Palette.trustTint, borderRadius: BorderRadius.circular(12)),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(Icons.shield_outlined, size: 18, color: Palette.trustInk),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(conversation!.safetyNotice!,
                        style: text.bodySmall?.copyWith(color: Palette.trustInk)),
                  ),
                ],
              ),
            ),
          if (conversation?.servicePostId != null) _AboutService(postId: conversation!.servicePostId!),
          if (conversation?.listingId != null) _AboutListing(listingId: conversation!.listingId!),
          Expanded(
            child: Stack(
              children: [
                Positioned.fill(child: _messages(state, myId)),
                if (_away)
                  Positioned(
                    right: 12,
                    bottom: 12,
                    child: _JumpToLatest(count: newSinceAway, onTap: _jumpToLatest),
                  ),
              ],
            ),
          ),
          if (conversation != null) _bottom(conversation, state, myId),
        ],
      ),
    );
  }

  Widget _messages(ConversationState state, String? myId) {
    final text = Theme.of(context).textTheme;
    if (state.loading && state.messages.isEmpty) {
      return Center(child: CircularProgressIndicator(color: Palette.primary));
    }
    if (state.error != null && state.conversation == null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Text(
            state.error!.statusCode == 404 ? 'This conversation is no longer available.' : state.error!.message,
            textAlign: TextAlign.center,
            style: text.bodyLarge,
          ),
        ),
      );
    }
    final messages = state.messages;
    if (messages.isEmpty) {
      final other = state.conversation?.otherUser?.displayName;
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Text(
            other == null
                ? 'No messages yet.'
                : 'Say hello to ${other.endsWith('.') ? other : '$other.'} '
                    'Until they reply, you can send one message.',
            textAlign: TextAlign.center,
            style: text.bodyMedium?.copyWith(color: Palette.muted),
          ),
        ),
      );
    }

    final conversation = state.conversation;
    final canReply = conversation != null && _canWrite(conversation, state, myId);
    final byId = {for (final m in messages) if (m.id.isNotEmpty) m.id: m};
    // "Unread messages" goes above the first message from someone else that
    // was unread when the chat opened.
    final unreadFrom = state.unreadFrom;
    final firstUnread = unreadFrom == null
        ? null
        : messages
            .where((m) => !m.isPending && !m.isSystem && m.seq >= unreadFrom && m.sender?.id != myId)
            .firstOrNull;

    bool sameRun(Message? a, Message b) =>
        a != null &&
        !a.isSystem &&
        a.sender?.id == b.sender?.id &&
        b.createdAt.difference(a.createdAt).abs() < _runGap &&
        dayLabel(a.createdAt) == dayLabel(b.createdAt);

    String whoWrote(Message message) {
      if (message.sender?.id == myId) return 'You';
      return message.sender?.displayName ?? state.names[message.sender?.id] ?? 'Someone';
    }

    // Bottom-up: index 0 is the newest message.
    return ListView.builder(
      controller: _scroll,
      reverse: true,
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      itemCount: messages.length + (state.hasEarlier ? 1 : 0),
      itemBuilder: (context, index) {
        if (index == messages.length) {
          return Padding(
            padding: EdgeInsets.all(12),
            child: Center(child: CircularProgressIndicator(color: Palette.primary, strokeWidth: 2)),
          );
        }
        final message = messages[messages.length - 1 - index];
        final older = index + 1 < messages.length ? messages[messages.length - 2 - index] : null;
        final newer = index > 0 ? messages[messages.length - index] : null;
        final newDay = older == null || dayLabel(older.createdAt) != dayLabel(message.createdAt);
        final mine = message.sender?.id == myId;
        final runsOn = !message.isSystem && sameRun(older, message) && message != firstUnread;
        final runContinues = !message.isSystem &&
            newer != null &&
            !newer.isSystem &&
            newer != firstUnread &&
            sameRun(message, newer);
        final showName = conversation?.isGroup == true && !mine && !message.isSystem && !runsOn;
        final quoted = message.replyTo == null ? null : byId[message.replyTo!.id];
        final key = message.id.isEmpty ? null : _keys.putIfAbsent(message.id, GlobalKey.new);

        final bubble = _Bubble(
          message: message,
          mine: mine,
          senderName: showName ? message.sender?.displayName : null,
          read: _controller.seen(message),
          tail: !runContinues,
          flashed: message.id == _flashed,
          quote: message.replyTo == null
              ? null
              : _Quote(
                  author: quoted == null ? null : whoWrote(quoted),
                  snippet: quoted == null ? 'An earlier message' : replySnippet(quoted),
                  onMine: mine,
                  onTap: quoted == null ? null : () => _scrollTo(quoted.id),
                ),
          onLongPress: () => _messageMenu(message, mine: mine, canReply: canReply),
        );
        return Column(
          key: key,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (newDay) _DayChip(dayLabel(message.createdAt)),
            if (message == firstUnread) const _UnreadLine(),
            if (message.isSystem)
              _SystemLine(systemText(message.system, names: state.names))
            else
              Padding(
                padding: EdgeInsets.only(top: runsOn ? 0 : 4),
                child: canReply && !message.isPending && !message.deleted
                    ? _SwipeToReply(onReply: () => _reply(message), child: bubble)
                    : bubble,
              ),
          ],
        );
      },
    );
  }

  Widget _bottom(Conversation conversation, ConversationState state, String? myId) {
    final text = Theme.of(context).textTheme;
    if (conversation.awaitsMe) {
      return _Panel(
        children: [
          Text(
            conversation.isInvitation
                ? "You've been invited to ${conversation.name}. Accept to see its messages from now on."
                : '${conversation.name} wants to message you. They won\'t know if you decline.',
            style: text.bodyMedium,
          ),
          if (conversation.requesterNewToArea) ...[
            const SizedBox(height: 8),
            const NewToAreaChip(),
          ],
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: () async {
                    if (await _attempt(() => _controller.respond(accept: false)) && mounted) {
                      context.go(Routes.chats);
                    }
                  },
                  child: const Text('Decline'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: FilledButton(
                  onPressed: () => _attempt(() => _controller.respond(accept: true)),
                  child: const Text('Accept'),
                ),
              ),
            ],
          ),
          if (conversation.isRequestReceived)
            TextButton.icon(
              onPressed: _blockAndReport,
              style: TextButton.styleFrom(foregroundColor: Palette.danger),
              icon: const Icon(Icons.block_rounded, size: 18),
              label: const Text('Block and report'),
            ),
        ],
      );
    }
    if (!_canWrite(conversation, state, myId)) {
      return _Panel(
        children: [
          Text(
            'Waiting for ${conversation.name} to reply. You can send more once they do.',
            style: text.bodyMedium?.copyWith(color: Palette.muted),
            textAlign: TextAlign.center,
          ),
        ],
      );
    }
    final replyTo = _replyTo;
    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.fromLTRB(8, 8, 8, 8),
        decoration: BoxDecoration(
          color: Palette.surface,
          border: Border(top: BorderSide(color: Palette.line)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (replyTo != null)
              _ReplyBar(
                author: replyTo.sender?.id == myId ? 'yourself' : (replyTo.sender?.displayName ?? 'Someone'),
                snippet: replySnippet(replyTo),
                onCancel: () => setState(() => _replyTo = null),
              ),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                IconButton(
                  onPressed: _attach,
                  tooltip: 'Send a photo',
                  style: IconButton.styleFrom(backgroundColor: Palette.cream),
                  icon: Icon(Icons.add_photo_alternate_outlined, color: Palette.ink),
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: TextField(
                    controller: _text,
                    focusNode: _focus,
                    minLines: 1,
                    maxLines: 5,
                    maxLength: 20000,
                    textCapitalization: TextCapitalization.sentences,
                    decoration: const InputDecoration(
                      hintText: 'Message',
                      counterText: '',
                      contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                    ),
                  ),
                ),
                const SizedBox(width: 6),
                IconButton.filled(
                  onPressed: _send,
                  tooltip: 'Send',
                  style: IconButton.styleFrom(
                    backgroundColor: _hasText ? Palette.primary : Palette.lineStrong,
                  ),
                  icon: const Icon(Icons.send_rounded, color: Palette.onPrimary, size: 20),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// Drag a message to the right to answer it.
class _SwipeToReply extends StatefulWidget {
  const _SwipeToReply({required this.onReply, required this.child});

  final VoidCallback onReply;
  final Widget child;

  @override
  State<_SwipeToReply> createState() => _SwipeToReplyState();
}

class _SwipeToReplyState extends State<_SwipeToReply> {
  static const _trigger = 56.0;
  double _dx = 0;
  bool _dragging = false;
  bool _armed = false;

  void _reset() => setState(() {
        _dx = 0;
        _dragging = false;
        _armed = false;
      });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onHorizontalDragStart: (_) => setState(() => _dragging = true),
      onHorizontalDragUpdate: (details) {
        setState(() => _dx = (_dx + details.delta.dx).clamp(0.0, 76.0));
        if (!_armed && _dx >= _trigger) {
          _armed = true;
          HapticFeedback.selectionClick();
        } else if (_armed && _dx < _trigger) {
          _armed = false;
        }
      },
      onHorizontalDragEnd: (_) {
        if (_armed) widget.onReply();
        _reset();
      },
      onHorizontalDragCancel: _reset,
      child: Stack(
        alignment: Alignment.centerLeft,
        children: [
          Opacity(
            opacity: (_dx / _trigger).clamp(0.0, 1.0),
            child: Padding(
              padding: const EdgeInsets.only(left: 4),
              child: CircleAvatar(
                radius: 15,
                backgroundColor: Palette.surface,
                child: Icon(Icons.reply_rounded, size: 18, color: Palette.inkSoft),
              ),
            ),
          ),
          AnimatedContainer(
            duration: _dragging ? Duration.zero : const Duration(milliseconds: 180),
            curve: Curves.easeOut,
            transform: Matrix4.translationValues(_dx, 0, 0),
            child: widget.child,
          ),
        ],
      ),
    );
  }
}

/// Above the box: the message being answered, and a way to stop.
class _ReplyBar extends StatelessWidget {
  const _ReplyBar({required this.author, required this.snippet, required this.onCancel});

  final String author;
  final String snippet;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.fromLTRB(4, 0, 0, 8),
      padding: const EdgeInsets.fromLTRB(10, 6, 0, 6),
      decoration: BoxDecoration(
        color: Palette.cream,
        borderRadius: BorderRadius.circular(10),
        border: Border(left: BorderSide(color: Palette.primary, width: 3)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Replying to $author',
                    style: TextStyle(color: Palette.primaryDark, fontSize: 13, fontWeight: FontWeight.w600)),
                const SizedBox(height: 2),
                Text(snippet,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(color: Palette.inkSoft, fontSize: 13.5)),
              ],
            ),
          ),
          IconButton(
            tooltip: 'Cancel reply',
            onPressed: onCancel,
            visualDensity: VisualDensity.compact,
            icon: Icon(Icons.close_rounded, size: 20, color: Palette.muted),
          ),
        ],
      ),
    );
  }
}

/// Inside a bubble: the message it answers.
class _Quote extends StatelessWidget {
  const _Quote({required this.author, required this.snippet, required this.onMine, this.onTap});

  final String? author;
  final String snippet;
  final bool onMine;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final ink = onMine ? Palette.onPrimary : Palette.ink;
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: double.infinity,
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.fromLTRB(8, 5, 8, 6),
        decoration: BoxDecoration(
          color: onMine ? const Color(0x33FFFFFF) : Palette.cream,
          borderRadius: BorderRadius.circular(8),
          border: Border(left: BorderSide(color: onMine ? Palette.onPrimary : Palette.primary, width: 3)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (author != null)
              Text(author!,
                  style: TextStyle(
                    color: onMine ? Palette.onPrimary : Palette.primaryDark,
                    fontSize: 12.5,
                    fontWeight: FontWeight.w600,
                  )),
            Text(snippet,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(color: ink.withValues(alpha: 0.85), fontSize: 13.5, height: 1.3)),
          ],
        ),
      ),
    );
  }
}

class _UnreadLine extends StatelessWidget {
  const _UnreadLine();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        children: [
          Expanded(child: Divider(color: Palette.primary.withValues(alpha: 0.4))),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10),
            child: Text('Unread messages',
                style: TextStyle(color: Palette.primaryDark, fontSize: 12, fontWeight: FontWeight.w600)),
          ),
          Expanded(child: Divider(color: Palette.primary.withValues(alpha: 0.4))),
        ],
      ),
    );
  }
}

/// Back to the newest message, with how many arrived meanwhile.
class _JumpToLatest extends StatelessWidget {
  const _JumpToLatest({required this.count, required this.onTap});

  final int count;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Badge(
      isLabelVisible: count > 0,
      label: Text(count > 99 ? '99+' : '$count'),
      backgroundColor: Palette.primary,
      child: Material(
        color: Palette.surface,
        shape: const CircleBorder(),
        elevation: 3,
        child: IconButton(
          tooltip: 'Newest messages',
          onPressed: onTap,
          icon: Icon(Icons.keyboard_double_arrow_down_rounded, color: Palette.ink),
        ),
      ),
    );
  }
}

/// The post a conversation is about: its title and price, a tap away.
class _AboutService extends ConsumerStatefulWidget {
  const _AboutService({required this.postId});

  final String postId;

  @override
  ConsumerState<_AboutService> createState() => _AboutServiceState();
}

class _AboutServiceState extends ConsumerState<_AboutService> {
  ServicePost? _post;
  bool _gone = false;

  @override
  void initState() {
    super.initState();
    ref.read(serviceRepositoryProvider).post(widget.postId).then(
      (post) {
        if (mounted) setState(() => _post = post);
      },
      onError: (Object _) {
        if (mounted) setState(() => _gone = true);
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final post = _post;
    final detail = post == null
        ? (_gone ? 'This post is no longer available' : 'Loading…')
        : [
            post.categoryName,
            ?switch (post.kind) {
              ServiceKind.offering => post.rateInfo,
              ServiceKind.seeking => post.budgetInfo,
              ServiceKind.hiring => post.pay,
            },
            if (!post.isOpen) 'Closed',
          ].join(' · ');
    return Material(
      color: Palette.surface,
      child: InkWell(
        onTap: post == null ? null : () => context.go(Routes.service(post.id), extra: DateTime.now()),
        child: Container(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
          child: Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(color: Palette.cream, borderRadius: BorderRadius.circular(12)),
            child: Row(
              children: [
                Icon(Icons.handyman_outlined, color: Palette.inkSoft),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(post?.title ?? 'About a service post',
                          maxLines: 1, overflow: TextOverflow.ellipsis, style: text.titleSmall?.copyWith(fontSize: 13.5)),
                      Text(detail, maxLines: 1, overflow: TextOverflow.ellipsis, style: text.bodySmall?.copyWith(fontSize: 12.5)),
                    ],
                  ),
                ),
                if (post != null) Icon(Icons.chevron_right_rounded, color: Palette.muted),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// The listing a conversation is about: photo, title, price and whether it is
/// still for sale, a tap away.
class _AboutListing extends ConsumerStatefulWidget {
  const _AboutListing({required this.listingId});

  final String listingId;

  @override
  ConsumerState<_AboutListing> createState() => _AboutListingState();
}

class _AboutListingState extends ConsumerState<_AboutListing> {
  Listing? _listing;
  bool _gone = false;

  @override
  void initState() {
    super.initState();
    ref.read(listingRepositoryProvider).listing(widget.listingId).then(
      (listing) {
        if (mounted) setState(() => _listing = listing);
      },
      onError: (Object _) {
        if (mounted) setState(() => _gone = true);
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final listing = _listing;
    final detail = listing == null
        ? (_gone ? 'This listing is no longer available' : 'Loading…')
        : [
            listing.price,
            if (listing.isSold) 'Sold' else if (listing.isExpired) 'Expired' else if (listing.isReserved) 'Reserved' else 'Available',
          ].join(' · ');
    return Material(
      color: Palette.surface,
      child: InkWell(
        onTap: listing == null ? null : () => context.go(Routes.listing(listing.id), extra: DateTime.now()),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
          child: Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(color: Palette.cream, borderRadius: BorderRadius.circular(12)),
            child: Row(
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: SizedBox.square(
                    dimension: 40,
                    child: listing == null
                        ? ColoredBox(color: Palette.sand)
                        : ListingPhoto(listing: listing, width: 40),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(listing?.title ?? 'About a listing',
                          maxLines: 1, overflow: TextOverflow.ellipsis, style: text.titleSmall?.copyWith(fontSize: 13.5)),
                      Text(detail, maxLines: 1, overflow: TextOverflow.ellipsis, style: text.bodySmall?.copyWith(fontSize: 12.5)),
                    ],
                  ),
                ),
                if (listing != null) Icon(Icons.chevron_right_rounded, color: Palette.muted),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Panel extends StatelessWidget {
  const _Panel({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
        decoration: BoxDecoration(
          color: Palette.surface,
          border: Border(top: BorderSide(color: Palette.line)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: children,
        ),
      ),
    );
  }
}

class _DayChip extends StatelessWidget {
  const _DayChip(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 10),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(color: const Color(0xFFEFDFD2), borderRadius: BorderRadius.circular(10)),
        child: Text(label, style: TextStyle(fontSize: 12, color: Palette.inkSoft)),
      ),
    );
  }
}

class _SystemLine extends StatelessWidget {
  const _SystemLine(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 24),
      child: Text(
        text,
        textAlign: TextAlign.center,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(fontSize: 12.5),
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({
    required this.message,
    required this.mine,
    required this.read,
    required this.tail,
    required this.onLongPress,
    this.flashed = false,
    this.senderName,
    this.quote,
  });

  final Message message;
  final bool mine;

  /// Mine, and the other person has read it.
  final bool read;

  /// The last of a run from one person: it gets the pointed corner.
  final bool tail;
  final bool flashed;
  final String? senderName;
  final Widget? quote;
  final VoidCallback onLongPress;

  @override
  Widget build(BuildContext context) {
    final failed = message.sendState == SendState.failed;
    final ink = mine ? Palette.onPrimary : Palette.ink;
    final metaInk = mine ? const Color(0xFFF8D3C3) : Palette.muted;
    final metaStyle = TextStyle(color: failed ? _onFailed : metaInk, fontSize: 11);
    final meta = switch (message.sendState) {
      SendState.sending => Text('Sending…', style: metaStyle),
      SendState.failed => Text(message.refused ? 'Not sent' : 'Not sent · tap for options', style: metaStyle),
      SendState.sent => Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(clockTime(message.createdAt), style: metaStyle),
            if (mine && !message.deleted) ...[
              const SizedBox(width: 3),
              Icon(
                read ? Icons.done_all_rounded : Icons.done_rounded,
                size: 15,
                color: read ? Palette.onPrimary : metaInk,
                semanticLabel: read ? 'Read' : 'Sent',
              ),
            ],
          ],
        ),
    };

    Widget content;
    if (message.deleted) {
      content = Text('Message deleted', style: TextStyle(color: metaInk, fontStyle: FontStyle.italic, fontSize: 15));
    } else if (message.localImage != null || message.image != null) {
      content = ClipRRect(
        borderRadius: BorderRadius.circular(10),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 320),
          child: message.localImage != null
              ? Image.memory(Uint8List.fromList(message.localImage!), fit: BoxFit.cover)
              : GestureDetector(
                  onTap: () => openPhotos(context, [message.image!.urlsByWidth]),
                  child: NetImage(
                    message.image!.urlFor(ImageSize.medium.width),
                    placeholder: SizedBox(height: 200, child: ColoredBox(color: Palette.sand)),
                  ),
                ),
        ),
      );
    } else {
      final style = TextStyle(color: ink, fontSize: 15, height: 1.35);
      // Links only once sent: tapping a failed message opens its options.
      content = message.isPending
          ? Text(message.body ?? '', style: style)
          : MessageText(message.body ?? '', style: style, linkColor: mine ? Palette.onPrimary : Palette.primaryDark);
    }

    const round = Radius.circular(16);
    const pointed = Radius.circular(4);
    final colour = failed ? const Color(0xFFE8A28C) : (mine ? Palette.primary : Palette.surface);
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.78),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 1.5),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 300),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(18),
              boxShadow: flashed ? [BoxShadow(color: Palette.primary.withValues(alpha: 0.45), blurRadius: 12)] : null,
            ),
            child: Material(
              color: colour,
              borderRadius: BorderRadius.only(
                topLeft: round,
                topRight: round,
                bottomLeft: mine || !tail ? round : pointed,
                bottomRight: mine && tail ? pointed : round,
              ),
              child: InkWell(
                borderRadius: BorderRadius.circular(16),
                onLongPress: onLongPress,
                onTap: failed ? onLongPress : null,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(12, 8, 12, 6),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (senderName != null)
                        Align(
                          alignment: Alignment.centerLeft,
                          child: Padding(
                            padding: const EdgeInsets.only(bottom: 2),
                            child: Text(senderName!,
                                style: TextStyle(
                                    color: Palette.primaryDark, fontSize: 13, fontWeight: FontWeight.w600)),
                          ),
                        ),
                      ?quote,
                      Align(alignment: Alignment.centerLeft, widthFactor: 1, child: content),
                      const SizedBox(height: 3),
                      meta,
                      // Why it wasn't sent, from the server, on the message itself.
                      if (failed && message.error != null) ...[
                        const SizedBox(height: 2),
                        Text(
                          message.error!,
                          textAlign: TextAlign.end,
                          style: const TextStyle(color: _onFailed, fontSize: 12.5, height: 1.3),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Text on a message that wasn't sent: dark on its salmon colour in both themes.
const _onFailed = Color(0xFF3A1A0F);

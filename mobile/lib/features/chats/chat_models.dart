import '../feed/feed_models.dart';

/// Whether a message of mine has reached the server.
enum SendState { sent, sending, failed }

/// The message a message replies to. The server sends only which one; the
/// screen finds it among the messages it holds.
class ReplyRef {
  const ReplyRef({required this.id, required this.seq});

  factory ReplyRef.fromJson(Map<String, dynamic> json) =>
      ReplyRef(id: json['id'] as String, seq: json['seq'] as int);

  final String id;
  final int seq;
}

class Message {
  const Message({
    required this.id,
    required this.conversationId,
    required this.seq,
    required this.kind,
    required this.createdAt,
    this.sender,
    this.body,
    this.image,
    this.system,
    this.deleted = false,
    this.sendState = SendState.sent,
    this.localId,
    this.idempotencyKey,
    this.error,
    this.refused = false,
    this.localImage,
    this.replyTo,
  });

  factory Message.fromJson(Map<String, dynamic> json) {
    final image = json['image'];
    final replyTo = json['reply_to'];
    return Message(
      id: json['id'] as String,
      conversationId: json['conversation_id'] as String,
      seq: json['seq'] as int,
      kind: json['kind'] as String,
      sender: json['sender'] == null
          ? null
          : Author.fromJson(Map<String, dynamic>.from(json['sender'] as Map)),
      body: json['body'] as String?,
      image: image is Map
          ? PostImage(
              mediaId: json['id'] as String,
              urlsByWidth: {
                for (final entry in image.entries)
                  int.parse('${entry.key}'): (entry.value as Map)['url'] as String,
              },
            )
          : null,
      system: json['system'] is Map ? Map<String, dynamic>.from(json['system'] as Map) : null,
      deleted: json['deleted'] as bool? ?? false,
      createdAt: DateTime.parse(json['created_at'] as String),
      replyTo: replyTo is Map ? ReplyRef.fromJson(Map<String, dynamic>.from(replyTo)) : null,
    );
  }

  /// A message being sent: it has no ID or sequence number until the server
  /// answers.
  factory Message.pending({
    required String localId,
    required String conversationId,
    required Author sender,
    required String idempotencyKey,
    String? body,
    List<int>? localImage,
    ReplyRef? replyTo,
  }) =>
      Message(
        id: '',
        conversationId: conversationId,
        seq: 0,
        kind: localImage == null ? 'text' : 'image',
        createdAt: DateTime.now(),
        sender: sender,
        body: body,
        sendState: SendState.sending,
        localId: localId,
        idempotencyKey: idempotencyKey,
        localImage: localImage,
        replyTo: replyTo,
      );

  final String id;
  final String conversationId;
  final int seq;

  /// `text`, `image` or `system`.
  final String kind;
  final Author? sender;
  final String? body;
  final PostImage? image;
  final Map<String, dynamic>? system;
  final bool deleted;
  final DateTime createdAt;

  final SendState sendState;
  final String? localId;
  final String? idempotencyKey;
  final String? error;

  /// The server turned it down on purpose (a rule, such as no links yet), not the
  /// network: sending it again as it is would fail the same way.
  final bool refused;

  /// The photo's bytes while it is still being sent, so it shows at once.
  final List<int>? localImage;

  /// The message this one answers, if any.
  final ReplyRef? replyTo;

  /// Whether it is a photo, sent or still sending.
  bool get isPhoto => image != null || localImage != null || kind == 'image';

  bool get isSystem => kind == 'system';
  bool get isPending => sendState != SendState.sent;

  Message copyWith({bool? deleted, SendState? sendState, String? error, bool? refused}) => Message(
        id: id,
        conversationId: conversationId,
        seq: seq,
        kind: kind,
        createdAt: createdAt,
        sender: sender,
        body: deleted == true ? null : body,
        image: deleted == true ? null : image,
        system: system,
        deleted: deleted ?? this.deleted,
        sendState: sendState ?? this.sendState,
        localId: localId,
        idempotencyKey: idempotencyKey,
        error: error,
        refused: refused ?? false,
        localImage: localImage,
        replyTo: replyTo,
      );
}

class Conversation {
  const Conversation({
    required this.id,
    required this.kind,
    required this.state,
    required this.myRole,
    required this.myStatus,
    required this.muted,
    required this.memberCount,
    required this.lastSeq,
    required this.lastReadSeq,
    required this.unreadCount,
    required this.updatedAt,
    this.title,
    this.listingId,
    this.servicePostId,
    this.otherUser,
    this.otherLastReadSeq,
    this.requesterNewToArea = false,
    this.safetyNotice,
    this.lastMessage,
    this.lastMessageAt,
  });

  factory Conversation.fromJson(Map<String, dynamic> json) => Conversation(
        id: json['id'] as String,
        kind: json['kind'] as String,
        title: json['title'] as String?,
        listingId: json['listing_id'] as String?,
        servicePostId: json['service_post_id'] as String?,
        state: json['state'] as String,
        myRole: json['my_role'] as String,
        myStatus: json['my_status'] as String,
        muted: json['muted'] as bool? ?? false,
        otherUser: json['other_user'] == null
            ? null
            : Author.fromJson(Map<String, dynamic>.from(json['other_user'] as Map)),
        otherLastReadSeq: json['other_last_read_seq'] as int?,
        requesterNewToArea: json['requester_new_to_area'] as bool? ?? false,
        safetyNotice: json['safety_notice'] as String?,
        memberCount: json['member_count'] as int,
        lastSeq: json['last_seq'] as int,
        lastReadSeq: json['last_read_seq'] as int,
        unreadCount: json['unread_count'] as int,
        lastMessage: json['last_message'] == null
            ? null
            : Message.fromJson(Map<String, dynamic>.from(json['last_message'] as Map)),
        lastMessageAt:
            json['last_message_at'] == null ? null : DateTime.parse(json['last_message_at'] as String),
        updatedAt: DateTime.parse(json['updated_at'] as String),
      );

  final String id;

  /// `direct` or `group`. There is one direct chat per person: chats started
  /// from a listing or a service post are that chat (decision P.1).
  final String kind;
  final String? title;

  /// The listing or service post the chat is about now: the last one asked
  /// about in it, or the one I just opened it from.
  final String? listingId;
  final String? servicePostId;

  /// From my side: `active`, `request_sent`, `request_received` or `declined`.
  final String state;
  final String myRole;

  /// `active`, `invited`, `left` or `removed`.
  final String myStatus;
  final bool muted;
  final Author? otherUser;
  final int? otherLastReadSeq;

  /// To me, receiving a request: whoever sent it was new to the area they wrote
  /// from, not yet allowed to post there (decision L.2).
  final bool requesterNewToArea;
  final String? safetyNotice;
  final int memberCount;
  final int lastSeq;
  final int lastReadSeq;
  final int unreadCount;
  final Message? lastMessage;
  final DateTime? lastMessageAt;
  final DateTime updatedAt;

  bool get isGroup => kind == 'group';
  bool get isInvitation => myStatus == 'invited';
  bool get isRequestReceived => state == 'request_received';
  bool get isRequestSent => state == 'request_sent';

  /// In the Requests folder: someone wants to talk, and I have not said yes.
  /// As on the server, someone asking about my listing or service lands in the
  /// inbox instead, and I just reply.
  bool get awaitsMe =>
      isInvitation ||
      (isRequestReceived && kind == 'direct' && listingId == null && servicePostId == null);

  /// Gone from my lists: I left, was removed, or declined.
  bool get isClosed => myStatus == 'left' || myStatus == 'removed' || state == 'declined';

  String get name => title ?? otherUser?.displayName ?? 'Conversation';

  /// Sorting key for the inbox: most recently active first.
  DateTime get activeAt => lastMessageAt ?? updatedAt;

  Conversation copyWith({int? lastReadSeq, int? unreadCount, bool? muted, int? otherLastReadSeq}) =>
      Conversation(
        id: id,
        kind: kind,
        title: title,
        listingId: listingId,
        servicePostId: servicePostId,
        state: state,
        myRole: myRole,
        myStatus: myStatus,
        muted: muted ?? this.muted,
        otherUser: otherUser,
        otherLastReadSeq: otherLastReadSeq ?? this.otherLastReadSeq,
        requesterNewToArea: requesterNewToArea,
        safetyNotice: safetyNotice,
        memberCount: memberCount,
        lastSeq: lastSeq,
        lastReadSeq: lastReadSeq ?? this.lastReadSeq,
        unreadCount: unreadCount ?? this.unreadCount,
        lastMessage: lastMessage,
        lastMessageAt: lastMessageAt,
        updatedAt: updatedAt,
      );
}

class MessagePage {
  const MessagePage(this.items, {required this.hasMore});
  final List<Message> items;
  final bool hasMore;
}

/// A one-line preview of a message, for the inbox. [names] resolves user IDs
/// in system messages; [myId] turns my own messages into "You: …".
String messagePreview(Message message, {String? myId, Map<String, String> names = const {}}) {
  if (message.deleted) return 'Message deleted';
  if (message.isSystem) return systemText(message.system, names: names);
  final text = message.image != null || message.kind == 'image' ? 'Photo' : (message.body ?? '');
  if (myId != null && message.sender?.id == myId) return 'You: $text';
  return text;
}

/// A system message written out: "Otieno joined". Names come from the member
/// list, so they are always current; anyone not in it is "Someone".
String systemText(Map<String, dynamic>? system, {Map<String, String> names = const {}}) {
  if (system == null) return '';
  String who(Object? id) => names['$id'] ?? 'Someone';
  final actor = who(system['actor_id']);
  final users = [for (final id in (system['user_ids'] as List?) ?? const []) who(id)];
  return switch (system['event']) {
    'created' => system['title'] == null ? '$actor started the chat' : '$actor created "${system['title']}"',
    'members_added' => '$actor added ${_list(users)}',
    'member_joined' => '${who(system['user_id'])} joined',
    'member_left' => '${who(system['user_id'])} left',
    'member_removed' => '$actor removed ${who(system['user_id'])}',
    'renamed' => '$actor renamed the chat "${system['title']}"',
    'role_changed' => '$actor made ${who(system['user_id'])} ${_role(system['role'])}',
    _ => 'The chat was updated',
  };
}

String _role(Object? role) => switch (role) {
      'owner' => 'the owner',
      'admin' => 'an admin',
      _ => 'a member',
    };

String _list(List<String> names) {
  if (names.isEmpty) return 'people';
  if (names.length == 1) return names.single;
  if (names.length == 2) return '${names[0]} and ${names[1]}';
  return '${names[0]}, ${names[1]} and ${names.length - 2} more';
}

/// "Today", "Yesterday", a weekday within the week, else the date.
String dayLabel(DateTime moment, {DateTime? now}) {
  final local = moment.toLocal();
  final today = (now ?? DateTime.now()).toLocal();
  final day = DateTime(local.year, local.month, local.day);
  final days = DateTime(today.year, today.month, today.day).difference(day).inDays;
  if (days == 0) return 'Today';
  if (days == 1) return 'Yesterday';
  const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  if (days < 7) return weekdays[local.weekday - 1];
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  final year = local.year == today.year ? '' : ' ${local.year}';
  return '${local.day} ${months[local.month - 1]}$year';
}

/// The time on an inbox row: the clock today, then as [dayLabel] says.
String inboxTime(DateTime moment, {DateTime? now}) {
  final label = dayLabel(moment, now: now);
  return label == 'Today' ? clockTime(moment) : label;
}

/// "Wanjiku" from "Wanjiku M.": how a group chat names who wrote.
String firstName(String displayName) {
  final first = displayName.trim().split(RegExp(r'\s+')).first;
  return first.isEmpty ? displayName : first;
}

/// A one-line summary of a message being replied to.
String replySnippet(Message message) {
  if (message.deleted) return 'Message deleted';
  if (message.isPhoto) return 'Photo';
  return (message.body ?? '').replaceAll(RegExp(r'\s+'), ' ').trim();
}

/// "14:05", the time a message was sent.
String clockTime(DateTime moment) {
  final local = moment.toLocal();
  return '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
}

import 'dart:async';

import 'package:clock/clock.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/realtime.dart';

/// Who is typing where (decision P.2): conversation ID to the IDs of the
/// people typing in it.
///
/// Fed by the socket. Someone stays "typing" for [lasts] after the last signal,
/// which their app renews every few seconds while they type, and stops at once
/// when their message arrives.
class TypingController extends Notifier<Map<String, Set<String>>> {
  final _until = <String, Map<String, DateTime>>{};
  Timer? _timer;

  static const lasts = Duration(seconds: 6);

  @override
  Map<String, Set<String>> build() {
    final subscription = ref.read(realtimeProvider).events.listen(_onEvent);
    ref.onDispose(() {
      subscription.cancel();
      _timer?.cancel();
    });
    return const {};
  }

  void _onEvent(RealtimeEvent event) {
    final conversationId = event.conversationId;
    if (conversationId == null) return;
    switch (event.type) {
      case RealtimeEvent.typing:
        final userId = event.data['user_id'] as String?;
        if (userId == null) return;
        (_until[conversationId] ??= {})[userId] = clock.now().add(lasts);
        _publish();
      case 'message.created':
        final typing = _until[conversationId];
        if (typing == null) return;
        final sender = event.data['sender_id'] as String?;
        if (sender == null) {
          typing.clear();
        } else {
          typing.remove(sender);
        }
        _publish();
    }
  }

  /// Drops whoever stopped, publishes the rest, and wakes when the next stops.
  void _publish() {
    final now = clock.now();
    for (final typing in _until.values) {
      typing.removeWhere((_, until) => !until.isAfter(now));
    }
    _until.removeWhere((_, typing) => typing.isEmpty);
    state = {for (final entry in _until.entries) entry.key: entry.value.keys.toSet()};
    _timer?.cancel();
    _timer = null;
    if (_until.isEmpty) return;
    final next = _until.values.expand((typing) => typing.values).reduce((a, b) => a.isBefore(b) ? a : b);
    _timer = Timer(next.difference(now), _publish);
  }
}

final typingProvider =
    NotifierProvider.autoDispose<TypingController, Map<String, Set<String>>>(TypingController.new);

/// "typing…", or who is, for a group chat. Null when nobody is.
String? typingLine(Set<String>? typing, {required bool group, Map<String, String> names = const {}}) {
  if (typing == null || typing.isEmpty) return null;
  if (!group) return 'typing…';
  final who = [for (final id in typing) names[id]?.split(' ').first ?? 'Someone'];
  if (who.length == 1) return '${who.single} is typing…';
  if (who.length == 2) return '${who[0]} and ${who[1]} are typing…';
  return 'Several people are typing…';
}

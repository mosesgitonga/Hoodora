import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import 'circle_models.dart';

/// On someone else's profile: where I stand with their Circle, and the one thing
/// to do about it. [onChanged] reloads the profile, since being in each other's
/// Circle also changes whose posts it shows.
class CircleButton extends ConsumerStatefulWidget {
  const CircleButton({
    super.key,
    required this.userId,
    required this.firstName,
    required this.relationship,
    required this.requestId,
    required this.onChanged,
  });

  final String userId;
  final String firstName;
  final CircleRelationship relationship;
  final String? requestId;
  final Future<void> Function() onChanged;

  @override
  ConsumerState<CircleButton> createState() => _CircleButtonState();
}

class _CircleButtonState extends ConsumerState<CircleButton> {
  bool _busy = false;

  Future<void> _run(Future<void> Function() action, {String? done}) async {
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = true);
    try {
      await action();
      await widget.onChanged();
      if (done != null) messenger.showSnackBar(SnackBar(content: Text(done)));
    } on ApiException catch (error) {
      // Every refusal looks the same on purpose (decision C.1): the server's
      // words, and nothing about why.
      messenger.showSnackBar(SnackBar(content: Text(error.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<bool> _confirm({required String title, required String body, required String action}) async =>
      await showDialog<bool>(
        context: context,
        builder: (dialog) => AlertDialog(
          title: Text(title),
          content: Text(body),
          actions: [
            TextButton(onPressed: () => Navigator.of(dialog).pop(false), child: const Text('Cancel')),
            TextButton(onPressed: () => Navigator.of(dialog).pop(true), child: Text(action)),
          ],
        ),
      ) ??
      false;

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(circleRepositoryProvider);
    final name = widget.firstName;
    final requestId = widget.requestId;
    Widget spinner() => const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2));

    switch (widget.relationship) {
      case CircleRelationship.none:
        return OutlinedButton.icon(
          onPressed: _busy
              ? null
              : () {
                  final messenger = ScaffoldMessenger.of(context);
                  _run(() async {
                    final now = await repo.ask(widget.userId);
                    if (now == CircleRelationship.inCircle) {
                      // They had already asked me: we're in each other's Circle.
                      messenger.showSnackBar(SnackBar(content: Text("You and $name are in each other's Circle")));
                    }
                  });
                },
          icon: _busy ? spinner() : const Icon(Icons.group_add_outlined, size: 18),
          label: const Text('Add to Circle'),
        );
      case CircleRelationship.requestSent:
        return OutlinedButton.icon(
          onPressed: _busy || requestId == null
              ? null
              : () async {
                  if (await _confirm(
                    title: 'Withdraw your request?',
                    body: "$name won't be asked any more.",
                    action: 'Withdraw',
                  )) {
                    await _run(() => repo.withdraw(requestId), done: 'Request withdrawn');
                  }
                },
          icon: _busy ? spinner() : const Icon(Icons.schedule_rounded, size: 18),
          label: const Text('Request sent'),
        );
      case CircleRelationship.requestReceived:
        return Row(
          children: [
            Expanded(
              child: FilledButton.tonal(
                onPressed: _busy || requestId == null
                    ? null
                    : () => _run(() => repo.accept(requestId), done: "$name is in your Circle"),
                child: _busy ? spinner() : const Text('Accept Circle request'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: OutlinedButton(
                // Silent: they aren't told (decision C.2).
                onPressed: _busy || requestId == null ? null : () => _run(() => repo.decline(requestId)),
                child: const Text('Decline'),
              ),
            ),
          ],
        );
      case CircleRelationship.inCircle:
        return OutlinedButton.icon(
          style: OutlinedButton.styleFrom(foregroundColor: Palette.primaryDark),
          onPressed: _busy
              ? null
              : () async {
                  if (await _confirm(
                    title: 'Remove $name from your Circle?',
                    body: "They won't be told. They'll stop seeing posts you share with your Circle.",
                    action: 'Remove',
                  )) {
                    await _run(() => repo.remove(widget.userId), done: 'Removed from your Circle');
                  }
                },
          icon: _busy ? spinner() : const Icon(Icons.check_circle_outline_rounded, size: 18),
          label: const Text('In your Circle'),
        );
    }
  }
}

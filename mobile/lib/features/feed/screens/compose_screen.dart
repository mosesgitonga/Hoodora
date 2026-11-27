import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/hints.dart';
import '../../../core/providers.dart';
import '../../../core/theme.dart';
import '../../../core/widgets.dart';
import '../../auth/auth_controller.dart';
import '../../groups/group_models.dart' show groupPostPostedMessage;
import '../feed_controller.dart';
import '../feed_models.dart';

const _maxPhotos = 6;
const _maxLength = 2000;
const _maxPollOptions = 4;
const _maxPollOptionLength = 80;

/// Writing a post: a category, words, and up to six photos, or a poll of 2 to 4
/// answers instead of photos (decision F.1). To the area the
/// phone is in (decision L.1), or
/// with [groupId] to that group, in which case the new post is handed back to
/// the group screen when this closes. With [editing], it changes one of your
/// posts instead: text and category only (decision 2.22).
class ComposeScreen extends ConsumerStatefulWidget {
  const ComposeScreen({super.key, this.groupId, this.groupName, this.editing, this.initialCategory});

  final String? groupId;
  final String? groupName;
  final Post? editing;

  /// The category to start on, such as `question` from the end of the feed.
  final String? initialCategory;

  @override
  ConsumerState<ComposeScreen> createState() => _ComposeScreenState();
}

class _ComposeScreenState extends ConsumerState<ComposeScreen> {
  late final _body = TextEditingController(text: widget.editing?.body);
  late String _category = widget.editing?.category ??
      (postCategories.containsKey(widget.initialCategory) ? widget.initialCategory! : 'general');

  /// Who sees it besides neighbours: my Circle too, unless I say not.
  bool _withCircle = true;
  final List<Uint8List> _photos = [];

  /// A poll instead of photos: the text is the question (decision F.1).
  bool _pollOn = false;
  final List<TextEditingController> _options = [TextEditingController(), TextEditingController()];
  int _pollHours = 72;
  bool _busy = false;
  String? _progress;
  String? _error;

  int get _starterPostsLeft {
    final auth = ref.watch(authControllerProvider);
    return auth is AuthSignedIn ? auth.me.starterPostsLeft : 0;
  }

  /// Polls go to the neighbourhood only, and aren't added by editing.
  bool get _canPoll => widget.editing == null && widget.groupId == null;

  @override
  void dispose() {
    _body.dispose();
    for (final option in _options) {
      option.dispose();
    }
    super.dispose();
  }

  void _startPoll() => setState(() {
        _pollOn = true;
        // A poll asks something, so it starts as a question unless chosen otherwise.
        if (_category == 'general') _category = 'question';
      });

  void _removePoll() => setState(() {
        _pollOn = false;
        for (final option in _options) {
          option.clear();
        }
        while (_options.length > 2) {
          _options.removeLast().dispose();
        }
      });

  /// The answers, or null after saying what's wrong with them.
  List<String>? _pollAnswers() {
    final answers = [for (final option in _options) option.text.trim().replaceAll(RegExp(r'\s+'), ' ')];
    if (answers.any((answer) => answer.isEmpty)) {
      setState(() => _error = 'Fill in every answer, or remove the empty one.');
      return null;
    }
    if (answers.map((answer) => answer.toLowerCase()).toSet().length != answers.length) {
      setState(() => _error = 'Each answer must be different.');
      return null;
    }
    return answers;
  }

  Future<void> _addPhotos() async {
    final room = _maxPhotos - _photos.length;
    if (room <= 0) return;
    // Resized on the phone first: no point paying to upload pixels the server
    // would throw away.
    final picked = await ImagePicker().pickMultiImage(
      maxWidth: 2048,
      maxHeight: 2048,
      imageQuality: 85,
      limit: room,
    );
    for (final file in picked.take(room)) {
      final bytes = await file.readAsBytes();
      if (mounted) setState(() => _photos.add(bytes));
    }
  }

  Future<void> _post() async {
    final body = _body.text.trim();
    if (body.isEmpty) {
      setState(() => _error = _pollOn ? 'Write your question first.' : 'Write something first.');
      return;
    }
    final answers = _pollOn ? _pollAnswers() : null;
    if (_pollOn && answers == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final repo = ref.read(feedRepositoryProvider);
    final uploader = ref.read(mediaUploaderProvider);
    final editing = widget.editing;
    try {
      if (editing != null) {
        final post = await repo.editPost(editing.id, body: body, category: _category);
        if (!mounted) return;
        context.pop(post);
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(post.awaitsApproval && !editing.awaitsApproval
              ? 'Saved. It goes back to a moderator for approval.'
              : post.isHeld && !editing.isHeld
                  ? 'Saved. It will show again once a moderator has looked at it.'
                  : 'Post updated.'),
        ));
        return;
      }
      final mediaIds = <String>[];
      for (var i = 0; i < _photos.length; i++) {
        setState(() => _progress = 'Uploading photo ${i + 1} of ${_photos.length}…');
        mediaIds.add(await uploader.uploadPhoto(_photos[i], purpose: 'post'));
      }
      setState(() => _progress = 'Posting…');
      final groupId = widget.groupId;
      if (groupId != null) {
        final post = await ref
            .read(groupRepositoryProvider)
            .createPost(groupId, body: body, category: _category, mediaIds: mediaIds);
        if (!mounted) return;
        context.pop(post);
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(groupPostPostedMessage(post))));
        return;
      }
      final (post, reach) = await repo.createPost(
        body: body,
        category: _category,
        mediaIds: mediaIds,
        withCircle: _withCircle,
        pollOptions: answers,
        pollDurationHours: _pollHours,
      );
      ref.read(feedControllerProvider.notifier).prepend(post);
      final auth = ref.read(authControllerProvider);
      if (auth is AuthSignedIn) ref.read(hintsProvider.notifier).mark(Hint.posted(auth.me.id));
      if (!mounted) return;
      context.pop();
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(post.isHeld
            ? 'Posted. It will appear once a moderator has looked at it.'
            : 'Posted. Visible to about $reach neighbours.'),
      ));
    } on ApiException catch (error) {
      setState(() => _error = error.message);
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
          _progress = null;
        });
      }
    }
  }

  /// The answers, how long it runs, and a way back to a plain post.
  List<Widget> _pollEditor(TextTheme text) => [
        Row(
          children: [
            Icon(Icons.poll_outlined, size: 20, color: Palette.primary),
            const SizedBox(width: 8),
            Expanded(child: Text('Poll', style: text.titleSmall)),
            TextButton(onPressed: _busy ? null : _removePoll, child: const Text('Remove poll')),
          ],
        ),
        for (var i = 0; i < _options.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: TextField(
              key: Key('poll-option-$i'),
              controller: _options[i],
              enabled: !_busy,
              maxLength: _maxPollOptionLength,
              textCapitalization: TextCapitalization.sentences,
              decoration: InputDecoration(
                hintText: 'Answer ${i + 1}',
                counterText: '',
                suffixIcon: _options.length > 2
                    ? IconButton(
                        tooltip: 'Remove answer',
                        onPressed: _busy
                            ? null
                            : () => setState(() => _options.removeAt(i).dispose()),
                        icon: const Icon(Icons.close_rounded),
                      )
                    : null,
              ),
            ),
          ),
        if (_options.length < _maxPollOptions)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: _busy ? null : () => setState(() => _options.add(TextEditingController())),
              icon: const Icon(Icons.add_rounded),
              label: const Text('Add an answer'),
            ),
          ),
        const SizedBox(height: 4),
        Text('Runs for', style: text.labelMedium?.copyWith(color: Palette.muted)),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          children: [
            for (final entry in pollDurations.entries)
              ChoiceChip(
                label: Text(entry.value),
                selected: _pollHours == entry.key,
                onSelected: _busy ? null : (_) => setState(() => _pollHours = entry.key),
                selectedColor: Palette.selectedFill,
                labelStyle: text.labelMedium?.copyWith(
                  color: _pollHours == entry.key ? Palette.onPrimary : Palette.ink,
                ),
                showCheckmark: false,
                side: BorderSide(color: _pollHours == entry.key ? Palette.primary : Palette.lineStrong),
                backgroundColor: Palette.surface,
              ),
          ],
        ),
        const SizedBox(height: 12),
        const NotePanel(
          icon: Icons.lock_outline_rounded,
          text: 'Votes are anonymous: nobody, not even Hoodora, can see who chose what. '
              'Each person votes once.',
        ),
        const SizedBox(height: 4),
      ];

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final auth = ref.watch(authControllerProvider);
    final label = auth is AuthSignedIn ? auth.me.areaLabel : null;
    final area = label == null || label.precision == 'generic' ? 'your area' : label.label;

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          onPressed: _busy ? null : () => context.pop(),
          tooltip: 'Cancel',
          icon: const Icon(Icons.close_rounded),
        ),
        title: Text(
          widget.editing != null ? 'Edit post' : 'Post to ${widget.groupName ?? area}',
          overflow: TextOverflow.ellipsis,
        ),
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                children: [
                  Text('What kind of post?', style: text.labelMedium?.copyWith(color: Palette.muted)),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final entry in postCategories.entries)
                        ChoiceChip(
                          label: Text(entry.value),
                          selected: _category == entry.key,
                          onSelected: _busy ? null : (_) => setState(() => _category = entry.key),
                          selectedColor: Palette.selectedFill,
                          labelStyle: text.labelMedium?.copyWith(
                            color: _category == entry.key ? Palette.onPrimary : Palette.ink,
                          ),
                          showCheckmark: false,
                          side: BorderSide(color: _category == entry.key ? Palette.primary : Palette.lineStrong),
                          backgroundColor: Palette.surface,
                        ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: _body,
                    enabled: !_busy,
                    autofocus: true,
                    minLines: 5,
                    maxLines: 12,
                    maxLength: _maxLength,
                    textCapitalization: TextCapitalization.sentences,
                    decoration: InputDecoration(
                      hintText: _pollOn
                          ? 'Ask your question…'
                          : 'Ask a question, share a tip, report something lost or found…',
                    ),
                  ),
                  if (_pollOn) ..._pollEditor(text),
                  if (widget.editing != null)
                    NotePanel(
                      icon: Icons.history_rounded,
                      text: widget.editing!.images.isEmpty
                          ? 'The post will show it was edited.'
                          : "Photos can't be changed: to change them, delete the post and post again. "
                              'The post will show it was edited.',
                    ),
                  if (widget.editing == null && _photos.isNotEmpty)
                    SizedBox(
                      height: 96,
                      child: ListView.separated(
                        scrollDirection: Axis.horizontal,
                        itemCount: _photos.length,
                        separatorBuilder: (_, _) => const SizedBox(width: 8),
                        itemBuilder: (_, index) => Stack(
                          children: [
                            ClipRRect(
                              borderRadius: BorderRadius.circular(10),
                              child: Image.memory(_photos[index], width: 96, height: 96, fit: BoxFit.cover),
                            ),
                            Positioned(
                              top: 2,
                              right: 2,
                              child: IconButton.filled(
                                onPressed: _busy ? null : () => setState(() => _photos.removeAt(index)),
                                tooltip: 'Remove photo',
                                iconSize: 16,
                                visualDensity: VisualDensity.compact,
                                style: IconButton.styleFrom(backgroundColor: Palette.ink),
                                icon: const Icon(Icons.close_rounded, color: Palette.onPrimary),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  if (widget.editing == null && !_pollOn) ...[
                    const SizedBox(height: 12),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        OutlinedButton.icon(
                          onPressed: _busy || _photos.length >= _maxPhotos ? null : _addPhotos,
                          style: OutlinedButton.styleFrom(minimumSize: const Size(0, 44)),
                          icon: const Icon(Icons.add_photo_alternate_outlined),
                          label: Text(_photos.isEmpty ? 'Add photos' : 'Add photos (${_photos.length}/$_maxPhotos)'),
                        ),
                        // A poll or photos, not both.
                        if (_canPoll && _photos.isEmpty)
                          OutlinedButton.icon(
                            onPressed: _busy ? null : _startPoll,
                            style: OutlinedButton.styleFrom(minimumSize: const Size(0, 44)),
                            icon: const Icon(Icons.poll_outlined),
                            label: const Text('Add a poll'),
                          ),
                      ],
                    ),
                    const SizedBox(height: 16),
                  ],
                  if (widget.editing != null)
                    const SizedBox.shrink()
                  else if (widget.groupId != null)
                    const NotePanel(
                      icon: Icons.groups_outlined,
                      text: "Posted in the group only; it doesn't reach the neighbourhood feed. "
                          'Photo location data is removed.',
                    )
                  else ...[
                    if (_starterPostsLeft > 0) ...[
                      NotePanel(
                        icon: Icons.waving_hand_outlined,
                        text: "If you haven't been around here on 4 days this week, this uses one of your "
                            '$_starterPostsLeft starter ${_starterPostsLeft == 1 ? 'post' : 'posts'}, '
                            "which can't contain links.",
                      ),
                      const SizedBox(height: 12),
                    ],
                    const NotePanel(
                      icon: Icons.location_on_outlined,
                      text: "Posted to the area you're in now. Neighbours see the area and a rough "
                          'distance, never exactly where you are. Photo location data is removed.',
                    ),
                  ],
                  if (_progress != null) ...[
                    const SizedBox(height: 16),
                    Row(
                      children: [
                        SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Palette.primary),
                        ),
                        const SizedBox(width: 10),
                        Text(_progress!, style: text.bodyMedium),
                      ],
                    ),
                  ],
                  FormError(_error),
                ],
              ),
            ),
            // Who sees it, beside the button that sends it (decision U.4). Above the
            // keyboard, since the body shrinks for it.
            _ComposeBar(
              withCircle: widget.editing == null && widget.groupId == null ? _withCircle : null,
              onAudience: _busy ? null : (value) => setState(() => _withCircle = value),
              action: widget.editing != null ? 'Save' : 'Post',
              onAction: _busy ? null : _post,
            ),
          ],
        ),
      ),
    );
  }
}

class _ComposeBar extends StatelessWidget {
  const _ComposeBar({required this.withCircle, required this.onAudience, required this.action, required this.onAction});

  /// Null where there is no choice: in a group, or when editing.
  final bool? withCircle;
  final ValueChanged<bool>? onAudience;
  final String action;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final circle = withCircle;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Palette.surface,
        border: Border(top: BorderSide(color: Palette.line)),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 8, 12, 8),
        child: Row(
          children: [
            Expanded(
              child: circle == null
                  ? const SizedBox.shrink()
                  : Align(
                      alignment: Alignment.centerLeft,
                      child: PopupMenuButton<bool>(
                        tooltip: 'Who sees this',
                        enabled: onAudience != null,
                        initialValue: circle,
                        onSelected: onAudience,
                        itemBuilder: (_) => const [
                          PopupMenuItem(
                            value: true,
                            child: ListTile(
                              title: Text('Neighbours and Circle'),
                              subtitle: Text('Your Circle too, wherever they live'),
                            ),
                          ),
                          PopupMenuItem(
                            value: false,
                            child: ListTile(
                              title: Text('Neighbours only'),
                              subtitle: Text('Only people around where you post'),
                            ),
                          ),
                        ],
                        child: Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(circle ? Icons.group_outlined : Icons.home_outlined,
                                  size: 18, color: Palette.primary),
                              const SizedBox(width: 6),
                              Flexible(
                                child: Text(
                                  circle ? 'Neighbours and Circle' : 'Neighbours only',
                                  overflow: TextOverflow.ellipsis,
                                  style: text.labelLarge?.copyWith(color: Palette.ink),
                                ),
                              ),
                              Icon(Icons.arrow_drop_down_rounded, color: Palette.muted),
                            ],
                          ),
                        ),
                      ),
                    ),
            ),
            FilledButton(
              onPressed: onAction,
              style: FilledButton.styleFrom(
                minimumSize: const Size(88, 40),
                padding: const EdgeInsets.symmetric(horizontal: 18),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
              ),
              child: Text(action),
            ),
          ],
        ),
      ),
    );
  }
}

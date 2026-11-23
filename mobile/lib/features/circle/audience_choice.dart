import 'package:flutter/material.dart';

/// Who sees a post or a story besides the neighbours around where it's posted:
/// my Circle too, wherever they live (the default), or nobody else (decision C.4).
class AudienceChoice extends StatelessWidget {
  const AudienceChoice({super.key, required this.withCircle, required this.onChanged});

  final bool withCircle;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Who sees this', style: text.titleSmall),
        const SizedBox(height: 8),
        SegmentedButton<bool>(
          showSelectedIcon: false,
          segments: const [
            ButtonSegment(value: true, label: Text('Neighbours and Circle')),
            ButtonSegment(value: false, label: Text('Neighbours only')),
          ],
          selected: {withCircle},
          onSelectionChanged: onChanged == null ? null : (chosen) => onChanged!(chosen.first),
        ),
      ],
    );
  }
}

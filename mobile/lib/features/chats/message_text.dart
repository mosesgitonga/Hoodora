import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

/// Web addresses and Kenyan phone numbers in a message.
final _linkPattern = RegExp(
  r'(https?://[^\s<>"]+|www\.[^\s<>"]+|(?<![\d+])(?:\+254|0)[17]\d{8}(?!\d))',
  caseSensitive: false,
);

/// Punctuation that ends a sentence rather than an address.
final _trailing = RegExp(r'[.,!?;:)\]]+$');

/// One piece of a message: plain text, or a link and where it goes.
typedef TextPiece = ({String text, Uri? target});

/// [text] cut into plain pieces and links: web addresses open in the browser,
/// phone numbers in the dialler.
List<TextPiece> linkPieces(String text) {
  final pieces = <TextPiece>[];
  var at = 0;
  for (final match in _linkPattern.allMatches(text)) {
    var link = match.group(0)!;
    final tail = _trailing.firstMatch(link)?.group(0) ?? '';
    link = link.substring(0, link.length - tail.length);
    if (link.isEmpty) continue;
    if (match.start > at) pieces.add((text: text.substring(at, match.start), target: null));
    pieces.add((text: link, target: _targetFor(link)));
    at = match.start + link.length;
  }
  if (at < text.length) pieces.add((text: text.substring(at), target: null));
  return pieces;
}

Uri? _targetFor(String link) {
  final lower = link.toLowerCase();
  if (lower.startsWith('http')) return Uri.tryParse(link);
  if (lower.startsWith('www.')) return Uri.tryParse('https://$link');
  return Uri(scheme: 'tel', path: link);
}

/// A message's text, with its links tappable.
class MessageText extends StatefulWidget {
  const MessageText(this.text, {super.key, required this.style, required this.linkColor});

  final String text;
  final TextStyle style;
  final Color linkColor;

  @override
  State<MessageText> createState() => _MessageTextState();
}

class _MessageTextState extends State<MessageText> {
  final _recognizers = <TapGestureRecognizer>[];

  @override
  void dispose() {
    for (final recognizer in _recognizers) {
      recognizer.dispose();
    }
    super.dispose();
  }

  Future<void> _open(Uri target) async {
    final opened = await launchUrl(target, mode: LaunchMode.externalApplication).catchError((_) => false);
    if (!opened && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Couldn't open that link")));
    }
  }

  TapGestureRecognizer _tap(Uri target) {
    final recognizer = TapGestureRecognizer()..onTap = () => _open(target);
    _recognizers.add(recognizer);
    return recognizer;
  }

  @override
  Widget build(BuildContext context) {
    final pieces = linkPieces(widget.text);
    if (pieces.every((piece) => piece.target == null)) return Text(widget.text, style: widget.style);
    for (final recognizer in _recognizers) {
      recognizer.dispose();
    }
    _recognizers.clear();
    return Text.rich(TextSpan(
      style: widget.style,
      children: [
        for (final piece in pieces)
          if (piece.target == null)
            TextSpan(text: piece.text)
          else
            TextSpan(
              text: piece.text,
              style: TextStyle(color: widget.linkColor, decoration: TextDecoration.underline),
              recognizer: _tap(piece.target!),
            ),
      ],
    ));
  }
}

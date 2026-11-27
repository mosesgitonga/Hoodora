import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/phone_verification.dart';
import '../../../core/providers.dart';
import '../../../core/router.dart';
import '../../../core/widgets.dart';
import '../../auth/auth_controller.dart';
import '../../auth/phone.dart';

/// Adding a phone number to the account: the number, then the code Firebase
/// texts to it (decision A.2). Posting jobs and the verified-neighbour badge need
/// one (decision A.1).
///
/// Firebase checks the code on the phone and gives a proof, which the server
/// checks before adding the number. On Android Firebase may read the SMS itself,
/// and then no code needs typing.
class AddPhoneScreen extends ConsumerStatefulWidget {
  const AddPhoneScreen({super.key});

  @override
  ConsumerState<AddPhoneScreen> createState() => _AddPhoneScreenState();
}

class _AddPhoneScreenState extends ConsumerState<AddPhoneScreen> {
  final _number = TextEditingController();
  final _code = TextEditingController();

  /// The number a code was sent to, and the challenge it answers.
  String? _phone;
  PhoneCodeSent? _sent;

  /// Firebase's proof, kept so a failed save can be retried without a new code.
  String? _proof;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _number.dispose();
    _code.dispose();
    super.dispose();
  }

  Future<void> _sendCode({bool again = false}) async {
    final phone = again ? _phone : normaliseKenyanMobile(_number.text);
    if (phone == null) {
      setState(() => _error = 'Enter a Kenyan mobile number, like 0712 345 678.');
      return;
    }
    await _run(() async {
      final sent = await ref.read(phoneVerifierProvider).sendCode(
            phone,
            resendToken: again ? _sent?.resendToken : null,
            onAutoProof: _save,
          );
      if (!mounted) return;
      setState(() {
        _phone = phone;
        _sent = sent ?? _sent;
      });
    });
  }

  Future<void> _confirm() async {
    final code = _code.text.trim();
    final sent = _sent;
    if (sent == null || code.length != 6) {
      setState(() => _error = 'Enter the 6-digit code from the SMS.');
      return;
    }
    String? proof;
    await _run(() async => proof = await ref.read(phoneVerifierProvider).confirm(sent, code));
    if (proof != null) await _save(proof!);
  }

  /// Sends Firebase's proof to the server, which adds the number.
  Future<void> _save(String proof) async {
    _proof = proof;
    await _run(() async {
      final me = await ref.read(authRepositoryProvider).addPhone(proof);
      final auth = ref.read(authControllerProvider.notifier);
      if (!mounted) {
        auth.replaceMe(me);
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Phone number added')));
      // Leave first, then update the account. Updating it refreshes the router,
      // and a refresh before the pop puts this screen back.
      if (context.canPop()) {
        context.pop();
      } else {
        context.go(Routes.me);
      }
      auth.replaceMe(me);
    });
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } on PhoneVerificationFailure catch (error) {
      if (mounted) setState(() => _error = error.message);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _startOver() => setState(() {
        _phone = null;
        _sent = null;
        _proof = null;
        _code.clear();
        _error = null;
      });

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final codeSent = _sent != null || _proof != null;
    final proof = _proof;
    return Scaffold(
      appBar: AppBar(title: const Text('Add a phone number')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
          children: [
            Text(
              'You need a phone number to post jobs and to become a verified neighbour. '
              "It's never shown to neighbours.",
              style: text.bodyMedium,
            ),
            const SizedBox(height: 24),
            if (!codeSent) ...[
              Text('Your phone number', style: text.titleSmall),
              const SizedBox(height: 10),
              TextField(
                key: const Key('add-phone-number'),
                controller: _number,
                keyboardType: TextInputType.phone,
                autofillHints: const [AutofillHints.telephoneNumberNational],
                inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9+ ]'))],
                textInputAction: TextInputAction.done,
                onSubmitted: (_) => _sendCode(),
                decoration: const InputDecoration(hintText: '0712 345 678'),
              ),
              const SizedBox(height: 10),
              Text("We'll send a 6-digit code by SMS.", style: text.bodySmall),
            ] else ...[
              Text('Enter the code sent to ${_readable(_phone)}', style: text.titleSmall),
              const SizedBox(height: 10),
              TextField(
                key: const Key('add-phone-code'),
                controller: _code,
                enabled: proof == null,
                keyboardType: TextInputType.number,
                autofillHints: const [AutofillHints.oneTimeCode],
                inputFormatters: [
                  FilteringTextInputFormatter.digitsOnly,
                  LengthLimitingTextInputFormatter(6),
                ],
                textInputAction: TextInputAction.done,
                onSubmitted: (_) => _confirm(),
                decoration: const InputDecoration(hintText: '6-digit code'),
              ),
              Wrap(
                spacing: 4,
                children: [
                  if (proof == null)
                    TextButton(
                      onPressed: _busy ? null : () => _sendCode(again: true),
                      child: const Text('Send a new code'),
                    ),
                  TextButton(
                    onPressed: _busy ? null : _startOver,
                    child: const Text('Use a different number'),
                  ),
                ],
              ),
            ],
            FormError(_error),
            const SizedBox(height: 24),
            BusyButton(
              label: codeSent ? 'Add number' : 'Send code',
              busy: _busy,
              onPressed: !codeSent
                  ? _sendCode
                  : proof != null
                      ? () => _save(proof)
                      : _confirm,
            ),
          ],
        ),
      ),
    );
  }

  /// `+254712345678` as people read it: `0712 345 678`.
  static String _readable(String? e164) {
    if (e164 == null || !e164.startsWith('+254') || e164.length != 13) return e164 ?? 'your phone';
    final local = '0${e164.substring(4)}';
    return '${local.substring(0, 4)} ${local.substring(4, 7)} ${local.substring(7)}';
  }
}

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/providers.dart';
import '../../../core/router.dart';
import '../../../core/widgets.dart';
import '../../auth/auth_controller.dart';
import '../../auth/phone.dart';

/// Adding a phone number to an account that signed up with Google: the number,
/// then the code sent to it by SMS. Posting jobs and the verified-neighbour badge
/// need one (decision A.1).
class AddPhoneScreen extends ConsumerStatefulWidget {
  const AddPhoneScreen({super.key});

  @override
  ConsumerState<AddPhoneScreen> createState() => _AddPhoneScreenState();
}

class _AddPhoneScreenState extends ConsumerState<AddPhoneScreen> {
  final _number = TextEditingController();
  final _code = TextEditingController();

  /// Set once a code has been sent to it.
  String? _phone;
  String? _masked;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _number.dispose();
    _code.dispose();
    super.dispose();
  }

  Future<void> _sendCode() async {
    final phone = normaliseKenyanMobile(_number.text);
    if (phone == null) {
      setState(() => _error = 'Enter a Kenyan mobile number, like 0712 345 678.');
      return;
    }
    await _run(() async {
      final challenge = await ref.read(authRepositoryProvider).requestCode(phone);
      setState(() {
        _phone = phone;
        _masked = challenge.maskedNumber;
      });
    });
  }

  Future<void> _addNumber() async {
    final code = _code.text.trim();
    if (_phone == null || code.length != 6) {
      setState(() => _error = 'Enter the 6-digit code from the SMS.');
      return;
    }
    await _run(() async {
      final me = await ref.read(authRepositoryProvider).addPhone(_phone!, code);
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
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final codeSent = _phone != null;
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
              Text('Enter the code sent to $_masked', style: text.titleSmall),
              const SizedBox(height: 10),
              TextField(
                key: const Key('add-phone-code'),
                controller: _code,
                keyboardType: TextInputType.number,
                autofillHints: const [AutofillHints.oneTimeCode],
                inputFormatters: [
                  FilteringTextInputFormatter.digitsOnly,
                  LengthLimitingTextInputFormatter(6),
                ],
                textInputAction: TextInputAction.done,
                onSubmitted: (_) => _addNumber(),
                decoration: const InputDecoration(hintText: '6-digit code'),
              ),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton(
                  onPressed: _busy
                      ? null
                      : () => setState(() {
                            _phone = null;
                            _code.clear();
                            _error = null;
                          }),
                  child: const Text('Use a different number'),
                ),
              ),
            ],
            FormError(_error),
            const SizedBox(height: 24),
            BusyButton(
              label: codeSent ? 'Add number' : 'Send code',
              busy: _busy,
              onPressed: codeSent ? _addNumber : _sendCode,
            ),
          ],
        ),
      ),
    );
  }
}

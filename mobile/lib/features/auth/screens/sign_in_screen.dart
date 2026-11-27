import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/google_auth.dart';
import '../../../core/providers.dart';
import '../../../core/router.dart';
import '../../../core/theme.dart';
import '../../../core/widgets.dart';
import '../auth_controller.dart';
import '../auth_models.dart';

/// Signing in, and signing up: with Google only (decision A.2).
///
/// A phone number is added later, from Settings, when something needs one, and
/// Firebase texts the code for it.
class SignInScreen extends ConsumerStatefulWidget {
  const SignInScreen({super.key});

  @override
  ConsumerState<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends ConsumerState<SignInScreen> {
  bool _busy = false;
  String? _error;

  /// Google's account picker, then one of two ways on: signed in, or on to
  /// sign-up with the Google name suggested (decision A.1).
  Future<void> _continueWithGoogle(String serverClientId) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final credential = await ref.read(googleAuthProvider).signIn(serverClientId: serverClientId);
      if (credential == null) return; // Backed out of the picker: nothing to say.
      final outcome = await ref.read(authRepositoryProvider).signInWithGoogle(credential.idToken);
      switch (outcome) {
        case SignedIn():
          ref.read(signInFlowProvider.notifier).reset();
          await ref.read(authControllerProvider.notifier).sessionStarted();
        case SignupRequired(:final signupToken):
          ref
              .read(signInFlowProvider.notifier)
              .googleSignupRequired(signupToken, suggestedName: credential.displayName);
          if (mounted) context.go(Routes.signUp);
      }
    } on GoogleAuthFailure {
      if (mounted) setState(() => _error = "Google sign-in didn't work. Please try again.");
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final methods = ref.watch(signInMethodsProvider);
    final clientId = methods.value?.googleClientId;
    final unavailable = methods.hasError || (methods.hasValue && clientId == null);
    return Scaffold(
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(24, 32, 24, 24),
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: constraints.maxHeight - 56),
              child: IntrinsicHeight(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Align(alignment: Alignment.centerLeft, child: Wordmark()),
                    const SizedBox(height: 56),
                    Text("What's happening around you", style: text.displaySmall),
                    const SizedBox(height: 14),
                    Text(
                      'News, help, things for sale and events from people who live near you.',
                      style: text.bodyLarge?.copyWith(color: Palette.muted),
                    ),
                    const Spacer(),
                    const SizedBox(height: 24),
                    if (unavailable) ...[
                      Text(
                        "Signing in isn't available right now. Check your connection and try again.",
                        textAlign: TextAlign.center,
                        style: text.bodyMedium,
                      ),
                      const SizedBox(height: 12),
                      OutlinedButton(
                        onPressed: () => ref.invalidate(signInMethodsProvider),
                        child: const Text('Try again'),
                      ),
                    ] else
                      BusyButton(
                        label: 'Continue with Google',
                        busy: _busy || clientId == null,
                        onPressed: clientId == null ? null : () => _continueWithGoogle(clientId),
                      ),
                    FormError(_error),
                    const SizedBox(height: 14),
                    Text(
                      'For adults 18 and over. You will be asked to agree to the terms '
                      'and privacy policy before your account is created.',
                      textAlign: TextAlign.center,
                      style: text.bodySmall?.copyWith(fontSize: 12),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

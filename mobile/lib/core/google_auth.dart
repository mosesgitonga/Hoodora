import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_sign_in/google_sign_in.dart';

/// What Google sign-in hands the app: the ID token for the server, and the
/// account's name to suggest on the sign-up screen. Nothing else is read, and
/// the name goes nowhere unless the person keeps it (decision A.1).
class GoogleCredential {
  const GoogleCredential({required this.idToken, this.displayName});

  final String idToken;
  final String? displayName;
}

/// Google sign-in failed for a reason other than the person backing out.
class GoogleAuthFailure implements Exception {
  const GoogleAuthFailure([this.detail]);

  final String? detail;

  @override
  String toString() => 'GoogleAuthFailure(${detail ?? ''})';
}

/// Google sign-in on the phone, behind an interface so tests can stand in for
/// Google.
abstract class GoogleAuth {
  /// Shows Google's account picker. Null when the person backs out.
  ///
  /// [serverClientId] comes from `GET /v1/auth/methods`, so the token Google
  /// issues is for Hoodora's server.
  Future<GoogleCredential?> signIn({required String serverClientId});

  /// Forgets the Google account on this phone, so the next person to sign in
  /// chooses their own. Never throws.
  Future<void> signOut();
}

/// The real thing, through the `google_sign_in` plugin.
class PluginGoogleAuth implements GoogleAuth {
  // The plugin must be initialised exactly once per run, before anything else.
  // That happens the first time someone taps the button, with the server's ID.
  Future<void>? _initialised;

  Future<void> _initialise(String serverClientId) =>
      _initialised ??= GoogleSignIn.instance.initialize(serverClientId: serverClientId);

  @override
  Future<GoogleCredential?> signIn({required String serverClientId}) async {
    await _initialise(serverClientId);
    try {
      final account = await GoogleSignIn.instance.authenticate();
      final idToken = account.authentication.idToken;
      if (idToken == null) throw const GoogleAuthFailure('no ID token');
      return GoogleCredential(idToken: idToken, displayName: account.displayName);
    } on GoogleSignInException catch (error) {
      if (error.code == GoogleSignInExceptionCode.canceled) return null;
      throw GoogleAuthFailure(error.description ?? error.code.name);
    }
  }

  @override
  Future<void> signOut() async {
    // Not initialised means Google wasn't used since the app started. Android
    // shows the account picker at every sign-in anyway, so there's nothing to
    // clear that would let the next person in as this one.
    final initialised = _initialised;
    if (initialised == null) return;
    try {
      await initialised;
      await GoogleSignIn.instance.signOut();
    } catch (error) {
      debugPrint('google_sign_out_failed: $error');
    }
  }
}

final googleAuthProvider = Provider<GoogleAuth>((ref) => PluginGoogleAuth());

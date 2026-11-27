import 'dart:async';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// A code is on its way to the number, by SMS from Firebase.
class PhoneCodeSent {
  const PhoneCodeSent({required this.verificationId, this.resendToken});

  final String verificationId;

  /// Lets "Send a new code" go to the same number without starting over.
  final int? resendToken;
}

/// Verifying the number failed, with words fit to show the person.
class PhoneVerificationFailure implements Exception {
  const PhoneVerificationFailure(this.message);

  final String message;

  @override
  String toString() => 'PhoneVerificationFailure($message)';
}

/// Proving a phone number with Firebase, behind an interface so tests can stand
/// in for it (decision A.2).
///
/// Firebase texts the code and checks it. What comes out is a *proof*: the ID
/// token of a short-lived Firebase sign-in with that number, which the server
/// checks before adding the number to the account. Hoodora never sees the code.
abstract class PhoneVerifier {
  /// Has Firebase text a code to [phoneNumber] (E.164). Completes once it is sent.
  ///
  /// On Android, Firebase may read the SMS itself, or verify the number without
  /// one: [onAutoProof] then gets the proof and no code needs typing. If that
  /// happens before any code is sent, this completes with null.
  Future<PhoneCodeSent?> sendCode(
    String phoneNumber, {
    required void Function(String proof) onAutoProof,
    int? resendToken,
  });

  /// The code the person typed, for the [sent] challenge. Returns the proof.
  Future<String> confirm(PhoneCodeSent sent, String code);
}

/// The real thing, through `firebase_auth`.
///
/// Firebase keeps a user for every number that signs in. That record is deleted
/// as soon as the proof is in hand, so Firebase holds no list of Hoodora's
/// numbers: the account lives on Hoodora's server alone (decision A.1).
class FirebasePhoneVerifier implements PhoneVerifier {
  @override
  Future<PhoneCodeSent?> sendCode(
    String phoneNumber, {
    required void Function(String proof) onAutoProof,
    int? resendToken,
  }) async {
    if (Firebase.apps.isEmpty) {
      throw const PhoneVerificationFailure("Phone verification isn't available in this version of the app.");
    }
    final sent = Completer<PhoneCodeSent?>();
    try {
      await FirebaseAuth.instance.verifyPhoneNumber(
        phoneNumber: phoneNumber,
        forceResendingToken: resendToken,
        timeout: const Duration(seconds: 60),
        codeSent: (verificationId, token) {
          if (!sent.isCompleted) sent.complete(PhoneCodeSent(verificationId: verificationId, resendToken: token));
        },
        verificationCompleted: (credential) async {
          try {
            final proof = await _proofFrom(credential);
            if (!sent.isCompleted) sent.complete(null);
            onAutoProof(proof);
          } on PhoneVerificationFailure catch (error) {
            if (!sent.isCompleted) sent.completeError(error);
          }
        },
        verificationFailed: (error) {
          if (!sent.isCompleted) sent.completeError(_failure(error));
        },
        codeAutoRetrievalTimeout: (_) {},
      );
    } on FirebaseAuthException catch (error) {
      throw _failure(error);
    }
    return sent.future;
  }

  @override
  Future<String> confirm(PhoneCodeSent sent, String code) =>
      _proofFrom(PhoneAuthProvider.credential(verificationId: sent.verificationId, smsCode: code));

  Future<String> _proofFrom(PhoneAuthCredential credential) async {
    final auth = FirebaseAuth.instance;
    try {
      final signedIn = await auth.signInWithCredential(credential);
      final user = signedIn.user;
      final token = await user?.getIdToken(true);
      if (user == null || token == null) {
        throw const PhoneVerificationFailure("The number couldn't be verified. Try again.");
      }
      // The proof stays valid after this; Firebase just stops keeping the number.
      try {
        await user.delete();
      } catch (error) {
        debugPrint('firebase_phone_user_delete_failed: $error');
      }
      return token;
    } on FirebaseAuthException catch (error) {
      throw _failure(error);
    } finally {
      try {
        await auth.signOut();
      } catch (_) {
        // Nothing more to do.
      }
    }
  }

  static PhoneVerificationFailure _failure(FirebaseAuthException error) {
    debugPrint('firebase_phone_failed: ${error.code}');
    return PhoneVerificationFailure(switch (error.code) {
      'invalid-phone-number' => "That number doesn't look right.",
      'invalid-verification-code' => "That code isn't right. Check the SMS and try again.",
      'session-expired' || 'code-expired' => 'That code has expired. Send a new one.',
      'too-many-requests' => 'Too many tries. Wait a while, then try again.',
      'quota-exceeded' => "Codes can't be sent right now. Try again later.",
      'network-request-failed' => 'No connection. Check your internet and try again.',
      'operation-not-allowed' ||
      'app-not-authorized' ||
      'invalid-app-credential' ||
      'missing-client-identifier' =>
        "Phone verification isn't set up yet. Try again later.",
      _ => "The number couldn't be verified. Try again.",
    });
  }
}

final phoneVerifierProvider = Provider<PhoneVerifier>((ref) => FirebasePhoneVerifier());

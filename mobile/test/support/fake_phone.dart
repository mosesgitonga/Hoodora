import 'package:myradius/core/phone_verification.dart';

/// Stands in for Firebase's phone verification (decision A.2): the right code
/// gives a proof, any other is refused as Firebase would.
class FakePhoneVerifier implements PhoneVerifier {
  FakePhoneVerifier({this.code = '482093'});

  /// The code Firebase "texted".
  final String code;

  /// Numbers a code was sent to, in order.
  final List<String> sentTo = [];

  /// Set to have Android verify the number by itself, with no code typed.
  String? autoProof;

  @override
  Future<PhoneCodeSent?> sendCode(
    String phoneNumber, {
    required void Function(String proof) onAutoProof,
    int? resendToken,
  }) async {
    sentTo.add(phoneNumber);
    final proof = autoProof;
    if (proof != null) {
      onAutoProof(proof);
      return null;
    }
    return PhoneCodeSent(verificationId: 'verification-${sentTo.length}', resendToken: 7);
  }

  @override
  Future<String> confirm(PhoneCodeSent sent, String typed) async {
    if (typed != code) {
      throw const PhoneVerificationFailure("That code isn't right. Check the SMS and try again.");
    }
    return 'firebase-proof-for-${sent.verificationId}';
  }
}

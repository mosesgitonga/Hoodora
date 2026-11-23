import 'package:myradius/core/google_auth.dart';

/// Stands in for Google's account picker.
class FakeGoogleAuth implements GoogleAuth {
  FakeGoogleAuth({this.credential});

  /// What the picker returns; null is the person backing out.
  GoogleCredential? credential;
  final List<String> serverClientIds = [];
  int signOuts = 0;

  @override
  Future<GoogleCredential?> signIn({required String serverClientId}) async {
    serverClientIds.add(serverClientId);
    return credential;
  }

  @override
  Future<void> signOut() async => signOuts++;
}

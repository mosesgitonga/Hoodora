import '../../core/api/api_client.dart';
import '../feed/feed_models.dart';
import '../stories/story_models.dart';
import 'circle_models.dart';

/// Circle: requests, the people in it, and their posts and stories. The server
/// holds every rule (decisions C.1–C.6); the app shows what it's told.
class CircleRepository {
  CircleRepository(this._api);

  final ApiClient _api;

  /// Asks someone to join my Circle. Answers where we stand now: usually
  /// [CircleRelationship.requestSent], or [CircleRelationship.inCircle] when they
  /// had already asked me.
  Future<CircleRelationship> ask(String userId) async {
    final data = Map<String, dynamic>.from(
      await _api.post('/circle/requests', body: {'user_id': userId}) as Map,
    );
    return CircleRelationship.parse(data['relationship'] as String?);
  }

  Future<ResultPage<CircleRequest>> requests({required bool incoming, String? cursor}) async {
    final data = Map<String, dynamic>.from(await _api.get('/circle/requests', query: {
      'direction': incoming ? 'incoming' : 'outgoing',
      'cursor': ?cursor,
    }) as Map);
    return ResultPage(
      [for (final item in data['items'] as List) CircleRequest.fromJson(Map<String, dynamic>.from(item as Map))],
      data['next_cursor'] as String?,
    );
  }

  Future<void> accept(String requestId) => _api.post('/circle/requests/$requestId/accept');

  /// Silent: the sender keeps seeing "Request sent" until it would have expired.
  Future<void> decline(String requestId) => _api.post('/circle/requests/$requestId/decline');

  /// Withdraws a request I sent.
  Future<void> withdraw(String requestId) => _api.delete('/circle/requests/$requestId');

  Future<ResultPage<CircleMember>> members({String? cursor}) async {
    final data = Map<String, dynamic>.from(await _api.get('/circle', query: {'cursor': ?cursor}) as Map);
    return ResultPage(
      [for (final item in data['items'] as List) CircleMember.fromJson(Map<String, dynamic>.from(item as Map))],
      data['next_cursor'] as String?,
    );
  }

  /// Silent too: they just stop seeing my Circle posts.
  Future<void> remove(String userId) => _api.delete('/circle/$userId');

  /// Posts my Circle shared with their Circle, wherever they live.
  Future<ResultPage<Post>> feed({String? cursor}) async {
    final data = Map<String, dynamic>.from(await _api.get('/feed/circle', query: {'cursor': ?cursor}) as Map);
    return ResultPage(
      [for (final item in data['items'] as List) Post.fromJson(Map<String, dynamic>.from(item as Map))],
      data['next_cursor'] as String?,
    );
  }

  Future<List<Story>> stories() async {
    final data = Map<String, dynamic>.from(await _api.get('/stories/circle', query: {'limit': 50}) as Map);
    return [for (final item in data['items'] as List) Story.fromJson(Map<String, dynamic>.from(item as Map))];
  }
}

import '../auth/auth_models.dart';
import '../feed/feed_models.dart';

/// Where I stand with someone's Circle, as their profile says. A request they
/// declined still reads [requestSent] until it would have expired: declines are
/// silent (decision C.2).
enum CircleRelationship {
  none,
  requestSent,
  requestReceived,
  inCircle;

  static CircleRelationship parse(String? value) => switch (value) {
        'request_sent' => requestSent,
        'request_received' => requestReceived,
        'in_circle' => inCircle,
        _ => none,
      };
}

/// A pending Circle request: one somebody sent me, or one I sent.
class CircleRequest {
  const CircleRequest({
    required this.id,
    required this.user,
    required this.incoming,
    required this.createdAt,
    required this.expiresAt,
  });

  factory CircleRequest.fromJson(Map<String, dynamic> json) => CircleRequest(
        id: json['id'] as String,
        user: Author.fromJson(Map<String, dynamic>.from(json['user'] as Map)),
        incoming: json['direction'] == 'incoming',
        createdAt: DateTime.parse(json['created_at'] as String),
        expiresAt: DateTime.parse(json['expires_at'] as String),
      );

  final String id;

  /// Who asked me, or whom I asked.
  final Author user;
  final bool incoming;
  final DateTime createdAt;
  final DateTime expiresAt;
}

/// Someone in my Circle. Beyond my feed radius there's a town and no distance
/// (decision C.6).
class CircleMember {
  const CircleMember({
    required this.user,
    required this.withinFeedRadius,
    required this.since,
    this.area,
    this.distanceBucket,
  });

  factory CircleMember.fromJson(Map<String, dynamic> json) => CircleMember(
        user: Author.fromJson(Map<String, dynamic>.from(json['user'] as Map)),
        area: json['area_label'] == null
            ? null
            : AreaLabel.fromJson(Map<String, dynamic>.from(json['area_label'] as Map)),
        distanceBucket: json['distance_bucket'] as String?,
        withinFeedRadius: json['within_feed_radius'] as bool? ?? false,
        since: DateTime.parse(json['since'] as String),
      );

  final Author user;
  final AreaLabel? area;
  final String? distanceBucket;
  final bool withinFeedRadius;
  final DateTime since;

  /// "Kamakwa · 1–3 km", or just "Nairobi" beyond my radius.
  String get where => [?area?.label, ?distanceLabel(distanceBucket)].join(' · ');
}

/// Who may send me Circle requests, as `PATCH /me` takes it.
enum CirclePolicy {
  everyone('everyone', 'Everyone'),
  nearbyOnly('nearby_only', 'People nearby'),
  contactsOnly('contacts_only', "People I've chatted with"),
  nobody('nobody', 'Nobody');

  const CirclePolicy(this.value, this.label);

  final String value;
  final String label;

  static CirclePolicy parse(String? value) =>
      values.firstWhere((policy) => policy.value == value, orElse: () => everyone);
}

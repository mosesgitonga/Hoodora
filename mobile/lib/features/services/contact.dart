import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/providers.dart';
import '../../core/router.dart';
import 'service_models.dart';

/// Opens the chat with [post]'s author, made if need be, about this post. There
/// is one chat per person, so it is asked for every time: that makes this post
/// what the next message is about (decision P.1). As with any first contact, it
/// is a request until they reply.
Future<void> contactAuthor(BuildContext context, WidgetRef ref, ServicePost post) async {
  try {
    final id = (await ref.read(serviceRepositoryProvider).contact(post.id)).id;
    if (context.mounted) context.go(Routes.conversation(id));
  } on ApiException catch (error) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.message)));
    }
  }
}

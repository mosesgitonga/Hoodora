import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/net_image.dart';
import '../../../core/router.dart';
import '../../../core/theme.dart';
import '../../../core/widgets.dart';
import '../../feed/explore.dart';
import '../../feed/widgets/explore_widgets.dart';
import '../listing_models.dart';
import '../market_controller.dart';
import '../widgets/listing_card.dart';

/// The Market tab: what neighbours are selling, nearest first if asked.
class MarketScreen extends ConsumerStatefulWidget {
  const MarketScreen({super.key});

  @override
  ConsumerState<MarketScreen> createState() => _MarketScreenState();
}

class _MarketScreenState extends ConsumerState<MarketScreen> {
  final _search = TextEditingController();
  final _scroll = ScrollController();
  Timer? _debounce;

  MarketController get _controller => ref.read(marketControllerProvider.notifier);

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels > _scroll.position.maxScrollExtent - 600) _controller.loadMore();
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    _scroll.dispose();
    super.dispose();
  }

  /// Searches once typing pauses, not on every key.
  void _onSearch(String value) {
    setState(() {});
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), () => _controller.setQuery(value));
  }

  Future<void> _chooseSort(String current) async {
    final chosen = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: Palette.cream,
      builder: (sheet) => SafeArea(
        child: RadioGroup<String>(
          groupValue: current,
          onChanged: (value) => Navigator.of(sheet).pop(value),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final entry in listingSorts.entries)
                RadioListTile<String>(value: entry.key, title: Text(entry.value)),
            ],
          ),
        ),
      ),
    );
    if (chosen != null) _controller.setSort(chosen);
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final state = ref.watch(marketControllerProvider);
    // As a later page arrives, warm the cache with its tiles (decision U.1).
    ref.listen(marketControllerProvider.select((state) => state.listings.length), (was, now) {
      if (was == null || was == 0 || now <= was) return;
      prefetchImages(context, [
        for (final listing in ref.read(marketControllerProvider).listings.skip(was))
          if (listing.images.isNotEmpty) listing.images.first.urlFor(ImageSize.small.width),
      ]);
    });
    // Rebuilt when the phone's location arrives, so the reach below is current.
    ref.watch(exploreProvider);

    return Scaffold(
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 14, 8, 8),
              child: Row(
                children: [
                  // Saved and your listings live in your profile's Selling tab now
                  // (decision U.4); the header keeps the one thing people come to do.
                  Expanded(child: Text('Marketplace', style: text.headlineSmall)),
                  FilledButton.icon(
                    onPressed: () => context.push(Routes.sell),
                    style: FilledButton.styleFrom(
                      minimumSize: const Size(0, 40),
                      padding: const EdgeInsets.symmetric(horizontal: 14),
                    ),
                    icon: const Icon(Icons.add_rounded, size: 18),
                    label: const Text('Sell'),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: TextField(
                controller: _search,
                onChanged: _onSearch,
                textInputAction: TextInputAction.search,
                decoration: InputDecoration(
                  hintText: 'Search sofas, phones, mitumba…',
                  prefixIcon: Icon(Icons.search_rounded, color: Palette.muted),
                  suffixIcon: _search.text.isEmpty
                      ? null
                      : IconButton(
                          tooltip: 'Clear',
                          icon: const Icon(Icons.close_rounded),
                          onPressed: () {
                            _search.clear();
                            _onSearch('');
                          },
                        ),
                ),
              ),
            ),
            SizedBox(
              height: 52,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.fromLTRB(16, 10, 16, 6),
                children: [
                  _Chip(label: 'All', selected: state.category == null, onTap: () => _controller.setCategory(null)),
                  for (final entry in listingCategories.entries)
                    _Chip(
                      label: entry.value,
                      selected: state.category == entry.key,
                      onTap: () => _controller.setCategory(entry.key),
                    ),
                ],
              ),
            ),
            // The reach and the order, which aren't filters, on one line, with the
            // button that updates where the reach is from (decision U.4).
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 8, 2),
              child: ReachLine(
                info: Wrap(
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    if (state.radiusKm != null) Text('${reachLabel(state.radiusKm!)} · ', style: text.bodySmall),
                    InkWell(
                      onTap: () => _chooseSort(state.sort),
                      borderRadius: BorderRadius.circular(8),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 6),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              listingSorts[state.sort] ?? 'Newest',
                              style: text.bodySmall?.copyWith(color: Palette.ink, fontWeight: FontWeight.w600),
                            ),
                            Icon(Icons.arrow_drop_down_rounded, size: 18, color: Palette.ink),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            Expanded(
              child: RefreshIndicator(
                color: Palette.primary,
                onRefresh: _controller.refresh,
                child: _grid(state, text),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _grid(MarketState state, TextTheme text) {
    if (state.loading && state.listings.isEmpty) {
      return ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [SizedBox(height: 120), Center(child: CircularProgressIndicator(color: Palette.primary))],
      );
    }
    if (state.listings.isEmpty) {
      final (title, body) = state.error != null
          ? ("Couldn't load the marketplace", state.error!.message)
          : state.filtered
              ? ('Nothing matches', 'Try another word, or all categories.')
              : ('Nothing for sale nearby yet', 'Sell something you no longer need. Neighbours nearby will see it.');
      return ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(32),
        children: [
          const SizedBox(height: 24),
          const Center(child: HoodoraMark(size: 48)),
          const SizedBox(height: 16),
          Text(title, textAlign: TextAlign.center, style: text.titleLarge),
          const SizedBox(height: 8),
          Text(body, textAlign: TextAlign.center, style: text.bodyMedium?.copyWith(color: Palette.muted)),
        ],
      );
    }
    return CustomScrollView(
      controller: _scroll,
      physics: const AlwaysScrollableScrollPhysics(),
      slivers: [
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(12, 6, 12, 24),
          sliver: SliverGrid.builder(
            itemCount: state.listings.length,
            gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
              maxCrossAxisExtent: 260,
              mainAxisSpacing: 10,
              crossAxisSpacing: 10,
              // Photo (4:3) and three lines of text below it.
              childAspectRatio: 0.78,
            ),
            itemBuilder: (context, index) {
              final listing = state.listings[index];
              return ListingCard(listing: listing, onTap: () => context.go(Routes.listing(listing.id)));
            },
          ),
        ),
        if (state.loadingMore)
          SliverToBoxAdapter(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: CircularProgressIndicator(color: Palette.primary)),
            ),
          )
        else if (state.nextCursor == null)
          // The end of the results invites the other side of the market (decision U.4).
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 32),
              child: Column(
                children: [
                  Text(
                    state.radiusKm == null
                        ? 'Selling something? Neighbours nearby will see it.'
                        : 'Selling something? Neighbours within ${kmLabel(state.radiusKm!)} km will see it.',
                    textAlign: TextAlign.center,
                    style: text.bodyMedium?.copyWith(color: Palette.muted),
                  ),
                  const SizedBox(height: 10),
                  FilledButton.icon(
                    onPressed: () => context.push(Routes.sell),
                    style: FilledButton.styleFrom(minimumSize: const Size(0, 40)),
                    icon: const Icon(Icons.add_rounded, size: 18),
                    label: const Text('Sell'),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ChoiceChip(
        label: Text(label),
        selected: selected,
        onSelected: (_) => onTap(),
        // Colours from the theme's chip style: orange and white when selected.
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(17)),
      ),
    );
  }
}

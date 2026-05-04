import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:timeago/timeago.dart' as timeago;
import '../client.dart';
import '../models.dart';
import '../theme.dart';

class FeedTab extends StatefulWidget {
  const FeedTab({super.key});

  @override
  State<FeedTab> createState() => _FeedTabState();
}

class _FeedTabState extends State<FeedTab> {
  final _scroll = ScrollController();
  bool _paused = false;
  List<FeedEvent> _frozen = [];

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      final atTop = _scroll.position.pixels < 40;
      if (_paused && atTop) {
        setState(() => _paused = false);
      } else if (!_paused && !atTop) {
        setState(() {
          _paused = true;
          _frozen = context.read<WactorzClient>().feed.toList();
        });
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final client = context.watch<WactorzClient>();
    final events = _paused ? _frozen : client.feed;

    return Stack(
      children: [
        events.isEmpty
            ? const Center(
                child: Text('No events yet', style: TextStyle(color: kMuted)),
              )
            : ListView.separated(
                controller: _scroll,
                padding: const EdgeInsets.symmetric(vertical: 8),
                itemCount: events.length,
                separatorBuilder: (context, idx) =>
                    const Divider(height: 1, color: kBorder),
                itemBuilder: (_, i) => FeedTile(event: events[i]),
              ),
        if (_paused)
          Positioned(
            top: 8,
            left: 0,
            right: 0,
            child: Center(
              child: GestureDetector(
                onTap: () {
                  _scroll.animateTo(
                    0,
                    duration: const Duration(milliseconds: 300),
                    curve: Curves.easeOut,
                  );
                },
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                  decoration: BoxDecoration(
                    color: kPrimary.withAlpha(200),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: const Text(
                    '⏸ Paused — tap to resume',
                    style: TextStyle(fontSize: 12, color: kBg, fontWeight: FontWeight.w600),
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}

class FeedTile extends StatelessWidget {
  final FeedEvent event;
  const FeedTile({super.key, required this.event});

  Color get _typeColor {
    switch (event.type) {
      case 'alert':    return kRed;
      case 'spawned':  return kGreen;
      case 'completed': return kCyan;
      case 'command':  return kAmber;
      default:         return kMuted;
    }
  }

  IconData get _typeIcon {
    switch (event.type) {
      case 'alert':    return Icons.warning_amber_outlined;
      case 'spawned':  return Icons.add_circle_outline;
      case 'completed': return Icons.check_circle_outline;
      case 'command':  return Icons.terminal;
      case 'status':   return Icons.info_outline;
      default:         return Icons.circle_outlined;
    }
  }

  @override
  Widget build(BuildContext context) {
    final color = _typeColor;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(_typeIcon, color: color, size: 16),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      event.agentName.isEmpty ? event.agentId.substring(0, 8) : event.agentName,
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: kText,
                      ),
                    ),
                    const SizedBox(width: 6),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                      decoration: BoxDecoration(
                        color: color.withAlpha(20),
                        borderRadius: BorderRadius.circular(3),
                        border: Border.all(color: color.withAlpha(60)),
                      ),
                      child: Text(
                        event.type,
                        style: TextStyle(fontSize: 9, color: color),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 3),
                Text(
                  event.message,
                  style: const TextStyle(fontSize: 12, color: kMuted),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Text(
            event.timestamp > 0 ? timeago.format(event.dateTime) : '',
            style: const TextStyle(fontSize: 10, color: kMuted),
          ),
        ],
      ),
    );
  }
}

import 'package:flutter/material.dart';
import '../models.dart';
import '../theme.dart';
import 'status_dot.dart';

class AgentCard extends StatelessWidget {
  final Agent agent;
  final VoidCallback onTap;
  final VoidCallback onChat;
  final Future<void> Function() onDelete;
  final Future<void> Function() onTogglePause;

  const AgentCard({
    super.key,
    required this.agent,
    required this.onTap,
    required this.onChat,
    required this.onDelete,
    required this.onTogglePause,
  });

  Color get _stateColor {
    if (agent.isRunning) return kGreen;
    if (agent.isFailed)  return kRed;
    if (agent.isPaused)  return kAmber;
    return kMuted;
  }

  // Show first 8 chars if name looks like a UUID
  String get _displayName {
    final n = agent.name.isEmpty ? agent.id : agent.name;
    final looksLikeUuid = RegExp(r'^[0-9a-f]{8}-').hasMatch(n);
    return looksLikeUuid ? n.substring(0, 8) : n;
  }

  @override
  Widget build(BuildContext context) {
    final color = _stateColor;
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 400),
        decoration: BoxDecoration(
          color: kCard,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: agent.isRunning ? kGreen.withAlpha(80) : kBorder,
          ),
          boxShadow: agent.isRunning
              ? [BoxShadow(color: kGreen.withAlpha(30), blurRadius: 12, spreadRadius: 1)]
              : null,
        ),
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                StatusDot(agent: agent),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    _displayName,
                    style: const TextStyle(
                      fontWeight: FontWeight.w600,
                      fontSize: 13,
                      color: kText,
                    ),
                    overflow: TextOverflow.ellipsis,
                    maxLines: 1,
                  ),
                ),
                _MoreMenu(
                  agent: agent,
                  onChat: onChat,
                  onDelete: onDelete,
                  onTogglePause: onTogglePause,
                ),
              ],
            ),
            const SizedBox(height: 8),
            _StatRow(
              icon: Icons.chat_bubble_outline,
              label: '${agent.messagesProcessed} msgs',
              color: kPrimary,
            ),
            if (agent.costUsd > 0) ...[
              const SizedBox(height: 3),
              _StatRow(
                icon: Icons.attach_money,
                label: '\$${agent.costUsd.toStringAsFixed(4)}',
                color: kAmber,
              ),
            ],
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
              decoration: BoxDecoration(
                color: color.withAlpha(color == kMuted ? 0 : 20),
                borderRadius: BorderRadius.circular(4),
                border: Border.all(color: color.withAlpha(60)),
              ),
              child: Text(
                agent.state.replaceAll('_', ' '),
                style: TextStyle(fontSize: 10, color: color),
                overflow: TextOverflow.ellipsis,
                maxLines: 1,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  const _StatRow({required this.icon, required this.label, required this.color});

  @override
  Widget build(BuildContext context) => Row(
    children: [
      Icon(icon, size: 12, color: color),
      const SizedBox(width: 4),
      Expanded(
        child: Text(
          label,
          style: TextStyle(fontSize: 11, color: color),
          overflow: TextOverflow.ellipsis,
          maxLines: 1,
        ),
      ),
    ],
  );
}

class _MoreMenu extends StatelessWidget {
  final Agent agent;
  final VoidCallback onChat;
  final Future<void> Function() onDelete;
  final Future<void> Function() onTogglePause;

  const _MoreMenu({
    required this.agent,
    required this.onChat,
    required this.onDelete,
    required this.onTogglePause,
  });

  @override
  Widget build(BuildContext context) {
    return PopupMenuButton<String>(
      iconSize: 16,
      padding: EdgeInsets.zero,
      color: kCard,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: const BorderSide(color: kBorder),
      ),
      onSelected: (v) async {
        switch (v) {
          case 'chat':  onChat();
          case 'pause': await onTogglePause();
          case 'delete':
            final ok = await showDialog<bool>(
              context: context,
              builder: (_) => AlertDialog(
                backgroundColor: kCard,
                title: const Text('Delete agent?'),
                content: Text('Remove "${agent.name}" permanently.'),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: const Text('Cancel'),
                  ),
                  TextButton(
                    onPressed: () => Navigator.pop(context, true),
                    style: TextButton.styleFrom(foregroundColor: kRed),
                    child: const Text('Delete'),
                  ),
                ],
              ),
            );
            if (ok == true) await onDelete();
        }
      },
      itemBuilder: (_) => [
        const PopupMenuItem(value: 'chat', child: Text('Chat')),
        PopupMenuItem(
          value: 'pause',
          child: Text(agent.isPaused ? 'Resume' : 'Pause'),
        ),
        const PopupMenuItem(
          value: 'delete',
          child: Text('Delete', style: TextStyle(color: kRed)),
        ),
      ],
    );
  }
}

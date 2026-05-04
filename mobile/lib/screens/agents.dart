import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../client.dart';
import '../models.dart';
import '../theme.dart';
import '../widgets/agent_card.dart';
import 'chat.dart';

class AgentsTab extends StatelessWidget {
  const AgentsTab({super.key});

  @override
  Widget build(BuildContext context) {
    final client = context.watch<WactorzClient>();
    final agents = client.agents;

    return Column(
      children: [
        _StatsBar(
          agentCount: agents.length,
          runningCount: agents.where((a) => a.isRunning).length,
          totalCost: client.totalCostUsd,
          totalMessages: client.totalMessages,
        ),
        Expanded(
          child: agents.isEmpty
              ? const _Empty()
              : RefreshIndicator(
                  color: kPrimary,
                  backgroundColor: kCard,
                  onRefresh: () async {},
                  child: GridView.builder(
                    padding: const EdgeInsets.all(12),
                    gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 2,
                      crossAxisSpacing: 10,
                      mainAxisSpacing: 10,
                      childAspectRatio: 1.1,
                    ),
                    itemCount: agents.length,
                    itemBuilder: (ctx, i) => _AgentCardWrapper(agent: agents[i]),
                  ),
                ),
        ),
      ],
    );
  }
}

class _AgentCardWrapper extends StatelessWidget {
  final Agent agent;
  const _AgentCardWrapper({required this.agent});

  @override
  Widget build(BuildContext context) {
    final client = context.read<WactorzClient>();

    return AgentCard(
      agent: agent,
      onTap: () => _openChat(context),
      onChat: () => _openChat(context),
      onDelete: () async {
        await client.deleteAgent(agent.id);
      },
      onTogglePause: () async {
        if (agent.isPaused) {
          await client.resumeAgent(agent.id);
        } else {
          await client.pauseAgent(agent.id);
        }
      },
    );
  }

  void _openChat(BuildContext context) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ChatScreen(agent: agent),
      ),
    );
  }
}

class _StatsBar extends StatelessWidget {
  final int agentCount;
  final int runningCount;
  final double totalCost;
  final int totalMessages;

  const _StatsBar({
    required this.agentCount,
    required this.runningCount,
    required this.totalCost,
    required this.totalMessages,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      color: kSurface,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      child: Row(
        children: [
          _Stat(label: 'Agents', value: '$agentCount', color: kPrimary),
          const SizedBox(width: 20),
          _Stat(label: 'Running', value: '$runningCount', color: kGreen),
          const SizedBox(width: 20),
          _Stat(label: 'Messages', value: '$totalMessages', color: kCyan),
          const Spacer(),
          if (totalCost > 0)
            _Stat(
              label: 'Cost',
              value: '\$${totalCost.toStringAsFixed(4)}',
              color: kAmber,
            ),
        ],
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  final String label;
  final String value;
  final Color color;
  const _Stat({required this.label, required this.value, required this.color});

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(value, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: color)),
      Text(label, style: const TextStyle(fontSize: 10, color: kMuted)),
    ],
  );
}

class _Empty extends StatelessWidget {
  const _Empty();

  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.hub_outlined, color: kMuted, size: 48),
        const SizedBox(height: 12),
        Text('No agents', style: Theme.of(context).textTheme.bodyMedium!.copyWith(color: kMuted)),
        const SizedBox(height: 4),
        Text(
          'Waiting for connection...',
          style: Theme.of(context).textTheme.bodySmall!.copyWith(color: kMuted),
        ),
      ],
    ),
  );
}

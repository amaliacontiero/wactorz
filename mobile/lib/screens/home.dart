import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../client.dart' as client_lib;
import '../theme.dart';
import 'agents.dart';
import 'feed.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tab = 0;

  static const _tabs = [
    _Tab(icon: Icons.hub_outlined,    label: 'Agents', body: AgentsTab()),
    _Tab(icon: Icons.list_alt_outlined, label: 'Feed',   body: FeedTab()),
  ];

  @override
  Widget build(BuildContext context) {
    final client = context.watch<client_lib.WactorzClient>();
    final conn   = client.connState;

    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            const Text('wactorz', style: TextStyle(fontWeight: FontWeight.w700)),
            const SizedBox(width: 10),
            _ConnBadge(state: conn),
          ],
        ),
        actions: [
          if (conn == client_lib.WsState.connected)
            Padding(
              padding: const EdgeInsets.only(right: 4),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    '${client.agents.length}',
                    style: const TextStyle(fontSize: 12, color: kMuted),
                  ),
                  const SizedBox(width: 2),
                  const Icon(Icons.hub_outlined, size: 14, color: kMuted),
                  const SizedBox(width: 12),
                ],
              ),
            ),
          IconButton(
            icon: const Icon(Icons.logout_outlined, size: 20),
            tooltip: 'Disconnect',
            onPressed: () => _confirmDisconnect(context),
          ),
        ],
      ),
      body: IndexedStack(
        index: _tab,
        children: _tabs.map((t) => t.body).toList(),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: _tabs
            .map((t) => NavigationDestination(icon: Icon(t.icon), label: t.label))
            .toList(),
      ),
    );
  }

  Future<void> _confirmDisconnect(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: kCard,
        title: const Text('Disconnect?'),
        content: const Text('Return to setup screen.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            style: TextButton.styleFrom(foregroundColor: kRed),
            child: const Text('Disconnect'),
          ),
        ],
      ),
    );
    if (ok == true && context.mounted) {
      // Pop back to setup — main.dart will handle re-gating
      Navigator.of(context).popUntil((r) => r.isFirst);
    }
  }
}

class _Tab {
  final IconData icon;
  final String label;
  final Widget body;
  const _Tab({required this.icon, required this.label, required this.body});
}

class _ConnBadge extends StatelessWidget {
  final client_lib.WsState state;
  const _ConnBadge({required this.state});

  @override
  Widget build(BuildContext context) {
    final (color, label) = switch (state) {
      client_lib.WsState.connected    => (kGreen, 'live'),
      client_lib.WsState.connecting   => (kAmber, 'connecting'),
      client_lib.WsState.disconnected => (kRed,   'offline'),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color: color.withAlpha(20),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withAlpha(60)),
      ),
      child: Text(label, style: TextStyle(fontSize: 10, color: color)),
    );
  }
}

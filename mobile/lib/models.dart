class Agent {
  final String id;
  final String name;
  final String state; // running, stopped, paused, failed, initializing
  final double costUsd;
  final int messagesProcessed;
  final double lastUpdate;

  const Agent({
    required this.id,
    required this.name,
    required this.state,
    this.costUsd = 0.0,
    this.messagesProcessed = 0,
    this.lastUpdate = 0,
  });

  factory Agent.fromJson(Map<String, dynamic> j) => Agent(
    id: j['agent_id'] as String? ?? j['id'] as String? ?? '',
    name: j['name'] as String? ?? '',
    state: _extractState(j),
    costUsd: (j['cost_usd'] as num?)?.toDouble() ?? 0.0,
    messagesProcessed: (j['messages_processed'] as num?)?.toInt() ?? 0,
    lastUpdate: (j['last_update'] as num?)?.toDouble() ?? 0,
  );

  static String _extractState(Map<String, dynamic> j) {
    final s = j['state'];
    if (s is String) return s;
    if (s is Map) return s['type'] as String? ?? 'stopped';
    final status = j['status'];
    if (status is Map) return status['state'] as String? ?? 'stopped';
    return 'stopped';
  }

  bool get isRunning => state == 'running';
  bool get isPaused  => state == 'paused';
  bool get isFailed  => state.startsWith('failed');
}

class FeedEvent {
  final String type;
  final String agentId;
  final String agentName;
  final double timestamp;
  final String message;

  const FeedEvent({
    required this.type,
    required this.agentId,
    required this.agentName,
    required this.timestamp,
    required this.message,
  });

  factory FeedEvent.fromJson(Map<String, dynamic> j) {
    final ts = (j['timestamp'] as num?)?.toDouble() ?? 0;
    final name = j['name'] as String? ?? j['agent_id'] as String? ?? '';
    final msg = _buildMessage(j);
    return FeedEvent(
      type: j['type'] as String? ?? 'log',
      agentId: j['agent_id'] as String? ?? '',
      agentName: name,
      timestamp: ts,
      message: msg,
    );
  }

  static String _buildMessage(Map<String, dynamic> j) {
    final type = j['type'] as String? ?? '';
    final name = j['name'] as String? ?? j['agent_id'] as String? ?? '?';
    switch (type) {
      case 'spawned':   return '$name spawned';
      case 'completed': return '$name task completed';
      case 'status':
        final s = j['status'];
        final st = s is Map ? s['state'] ?? s['status'] : s;
        return '$name → $st';
      case 'alert':
        return j['message'] as String? ?? '$name alert';
      case 'command':
        return '${j['command']} → $name';
      default:
        return j['message'] as String? ?? j['log'] as String? ?? '$name $type';
    }
  }

  DateTime get dateTime =>
      DateTime.fromMillisecondsSinceEpoch((timestamp * 1000).toInt());
}

class ChatMessage {
  final String role; // user | assistant
  final String content;
  final DateTime time;
  final bool isStreaming;

  const ChatMessage({
    required this.role,
    required this.content,
    required this.time,
    this.isStreaming = false,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> j) {
    final ts = j['ts'] as int? ?? 0;
    final dt = ts > 0
        ? DateTime.fromMillisecondsSinceEpoch(ts < 1e10.toInt() ? ts * 1000 : ts)
        : DateTime.now();
    return ChatMessage(
      role: j['role'] as String? ?? 'assistant',
      content: j['content'] as String? ?? '',
      time: dt,
    );
  }

  ChatMessage copyWith({String? content, bool? isStreaming}) => ChatMessage(
    role: role,
    content: content ?? this.content,
    time: time,
    isStreaming: isStreaming ?? this.isStreaming,
  );
}

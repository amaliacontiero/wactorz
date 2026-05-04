import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import 'models.dart';

enum WsState { disconnected, connecting, connected }

class WactorzClient extends ChangeNotifier {
  String _baseUrl = '';
  String get baseUrl => _baseUrl;

  WsState _connState = WsState.disconnected;
  WsState get connState => _connState;

  List<Agent> agents = [];
  List<FeedEvent> feed = [];
  double totalCostUsd = 0;
  int totalMessages = 0;

  WebSocketChannel? _ws;
  Timer? _reconnectTimer;
  bool _disposed = false;

  // Streams for chat screen
  final _chatStreamController = StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get chatStream => _chatStreamController.stream;

  void configure(String url) {
    _baseUrl = url.endsWith('/') ? url.substring(0, url.length - 1) : url;
    _reconnectTimer?.cancel();
    _ws?.sink.close();
    _connect();
  }

  void _connect() {
    if (_disposed || _baseUrl.isEmpty) return;
    _setConn(WsState.connecting);

    final wsUrl = _baseUrl
        .replaceFirst('https://', 'wss://')
        .replaceFirst('http://', 'ws://');

    try {
      _ws = WebSocketChannel.connect(Uri.parse('$wsUrl/ws'));
      _setConn(WsState.connected);

      _ws!.stream.listen(
        (raw) {
          try {
            if (raw is! String) return;
            final msg = jsonDecode(raw) as Map<String, dynamic>;
            _handleMessage(msg);
          } catch (_) {}
        },
        onDone: _scheduleReconnect,
        onError: (_) => _scheduleReconnect(),
      );
    } catch (_) {
      _scheduleReconnect();
    }
  }

  void _handleMessage(Map<String, dynamic> msg) {
    final type = msg['type'] as String?;
    switch (type) {
      case 'full_snapshot':
      case 'patch':
        final s = msg['state'] as Map<String, dynamic>?;
        if (s != null) _applyState(s);
        // also forward to chat screen if it has an event
        if (msg.containsKey('event')) {
          _chatStreamController.add(msg);
        }
      case 'stream_chunk':
      case 'stream_end':
      case 'chat':
        _chatStreamController.add(msg);
      case 'delete_agent':
        final id = msg['agent_id'] as String?;
        if (id != null) {
          agents.removeWhere((a) => a.id == id);
          notifyListeners();
        }
        final s = msg['state'] as Map<String, dynamic>?;
        if (s != null) _applyState(s);
    }
  }

  void _applyState(Map<String, dynamic> s) {
    final rawAgents = s['agents'] as List<dynamic>? ?? [];
    agents = rawAgents
        .map((e) => Agent.fromJson(e as Map<String, dynamic>))
        .toList();

    final rawFeed = s['log_feed'] as List<dynamic>? ?? [];
    feed = rawFeed
        .map((e) => FeedEvent.fromJson(e as Map<String, dynamic>))
        .toList();

    totalCostUsd = (s['total_cost_usd'] as num?)?.toDouble() ?? 0;
    totalMessages = (s['total_messages'] as num?)?.toInt() ?? 0;
    notifyListeners();
  }

  void _scheduleReconnect() {
    if (_disposed) return;
    _setConn(WsState.disconnected);
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 3), _connect);
  }

  void _setConn(WsState s) {
    _connState = s;
    notifyListeners();
  }

  void sendChat(String content) {
    _ws?.sink.add(jsonEncode({'type': 'chat', 'content': content}));
  }

  Future<List<ChatMessage>> fetchChatHistory(String agentName) async {
    try {
      final uri = Uri.parse(
        '$_baseUrl/api/chats?agent=${Uri.encodeComponent(agentName)}&limit=200',
      );
      final res = await http.get(uri).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) {
        final rows = jsonDecode(res.body) as List<dynamic>;
        return rows
            .map((e) => ChatMessage.fromJson(e as Map<String, dynamic>))
            .toList()
            .reversed
            .toList();
      }
    } catch (_) {}
    return [];
  }

  Future<List<FeedEvent>> fetchFeed({int limit = 100}) async {
    try {
      final uri = Uri.parse('$_baseUrl/api/feed?limit=$limit');
      final res = await http.get(uri).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        final items = (data is Map ? data['events'] ?? data['items'] : data) as List<dynamic>? ?? [];
        return items
            .map((e) => FeedEvent.fromJson(e as Map<String, dynamic>))
            .toList();
      }
    } catch (_) {}
    return [];
  }

  Future<bool> deleteAgent(String agentId) async {
    try {
      final uri = Uri.parse('$_baseUrl/api/actors/$agentId');
      final res = await http.delete(uri).timeout(const Duration(seconds: 10));
      return res.statusCode < 300;
    } catch (_) {
      return false;
    }
  }

  Future<bool> pauseAgent(String agentId) async {
    try {
      final uri = Uri.parse('$_baseUrl/api/actors/$agentId/pause');
      final res = await http.post(uri).timeout(const Duration(seconds: 10));
      return res.statusCode < 300;
    } catch (_) {
      return false;
    }
  }

  void disconnect() {
    _reconnectTimer?.cancel();
    _ws?.sink.close();
    _ws = null;
    _baseUrl = '';
    agents = [];
    feed = [];
    totalCostUsd = 0;
    totalMessages = 0;
    _setConn(WsState.disconnected);
  }

  Future<bool> resumeAgent(String agentId) async {
    try {
      final uri = Uri.parse('$_baseUrl/api/actors/$agentId/resume');
      final res = await http.post(uri).timeout(const Duration(seconds: 10));
      return res.statusCode < 300;
    } catch (_) {
      return false;
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _reconnectTimer?.cancel();
    _ws?.sink.close();
    _chatStreamController.close();
    super.dispose();
  }
}

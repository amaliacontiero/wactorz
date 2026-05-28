import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:provider/provider.dart';
import 'package:timeago/timeago.dart' as timeago;
import '../client.dart';
import '../models.dart';
import '../services/tts_service.dart';
import '../theme.dart';
import '../widgets/voice_button.dart';

class ChatScreen extends StatefulWidget {
  final Agent agent;
  const ChatScreen({super.key, required this.agent});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _scroll = ScrollController();
  final _input  = TextEditingController();
  final List<ChatMessage> _messages = [];
  bool _loadingHistory = true;
  bool _streaming = false;
  StreamSubscription<Map<String, dynamic>>? _sub;

  @override
  void initState() {
    super.initState();
    _loadHistory();
    _sub = context.read<WactorzClient>().chatStream.listen(_onChatEvent);
  }

  @override
  void dispose() {
    _sub?.cancel();
    _scroll.dispose();
    _input.dispose();
    super.dispose();
  }

  Future<void> _loadHistory() async {
    final client = context.read<WactorzClient>();
    final history = await client.fetchChatHistory(widget.agent.name);
    if (mounted) {
      setState(() {
        _messages.addAll(history);
        _loadingHistory = false;
      });
      _scrollToBottom();
    }
  }

  void _onChatEvent(Map<String, dynamic> msg) {
    final type = msg['type'] as String?;
    switch (type) {
      case 'stream_chunk':
        final chunk = msg['content'] as String? ?? '';
        setState(() {
          if (_streaming && _messages.isNotEmpty && _messages.last.isStreaming) {
            final last = _messages.removeLast();
            _messages.add(last.copyWith(content: last.content + chunk));
          } else {
            _streaming = true;
            _messages.add(ChatMessage(
              role: 'assistant',
              content: chunk,
              time: DateTime.now(),
              isStreaming: true,
            ));
          }
        });
        _scrollToBottom();
      case 'stream_end':
        if (_streaming && _messages.isNotEmpty) {
          final finalMsg = _messages.last;
          setState(() {
            _messages.removeLast();
            _messages.add(finalMsg.copyWith(isStreaming: false));
            _streaming = false;
          });
          if (mounted) context.read<TtsService>().speak(finalMsg.content);
        }
      case 'chat':
        final from = msg['from'] as String?;
        final content = msg['content'] as String? ?? '';
        if (content.isNotEmpty && from != 'user') {
          setState(() => _messages.add(ChatMessage(
            role: 'assistant',
            content: content,
            time: DateTime.now(),
          )));
          _scrollToBottom();
        }
    }
  }

  void _send() {
    final text = _input.text.trim();
    if (text.isEmpty) return;
    _input.clear();
    setState(() => _messages.add(ChatMessage(
      role: 'user',
      content: text,
      time: DateTime.now(),
    )));
    context.read<WactorzClient>().sendChat(text);
    _scrollToBottom();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(
          _scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final tts = context.watch<TtsService>();
    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            Text(widget.agent.name),
            const SizedBox(width: 8),
            Container(
              width: 7,
              height: 7,
              decoration: BoxDecoration(
                color: widget.agent.isRunning ? kGreen : kMuted,
                shape: BoxShape.circle,
              ),
            ),
          ],
        ),
        actions: [
          if (tts.playing)
            const Padding(
              padding: EdgeInsets.only(right: 4),
              child: Center(
                child: SizedBox(
                  width: 14, height: 14,
                  child: CircularProgressIndicator(strokeWidth: 1.5, color: kCyan),
                ),
              ),
            ),
          IconButton(
            onPressed: tts.toggle,
            icon: Icon(tts.enabled ? Icons.volume_up : Icons.volume_off_outlined),
            color: tts.enabled ? kCyan : kMuted,
            tooltip: tts.enabled ? 'TTS on' : 'TTS off',
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: _loadingHistory
                ? const Center(child: CircularProgressIndicator(color: kPrimary))
                : _messages.isEmpty
                    ? _EmptyChat(agentName: widget.agent.name)
                    : ListView.builder(
                        controller: _scroll,
                        padding: const EdgeInsets.all(12),
                        itemCount: _messages.length,
                        itemBuilder: (_, i) => ChatBubble(msg: _messages[i]),
                      ),
          ),
          _InputBar(controller: _input, onSend: _send),
        ],
      ),
    );
  }
}

class ChatBubble extends StatelessWidget {
  final ChatMessage msg;
  const ChatBubble({super.key, required this.msg});

  bool get _isUser => msg.role == 'user';

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        mainAxisAlignment:
            _isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        children: [
          if (!_isUser) ...[
            const CircleAvatar(
              radius: 14,
              backgroundColor: kCard,
              child: Icon(Icons.smart_toy_outlined, size: 14, color: kPrimary),
            ),
            const SizedBox(width: 8),
          ],
          Flexible(
            child: Container(
              constraints: BoxConstraints(
                maxWidth: MediaQuery.of(context).size.width * 0.75,
              ),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: _isUser ? kPrimary.withAlpha(30) : kCard,
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(14),
                  topRight: const Radius.circular(14),
                  bottomLeft: _isUser ? const Radius.circular(14) : Radius.zero,
                  bottomRight: _isUser ? Radius.zero : const Radius.circular(14),
                ),
                border: Border.all(
                  color: _isUser ? kPrimary.withAlpha(60) : kBorder,
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (!_isUser)
                    MarkdownBody(
                      data: msg.content + (msg.isStreaming ? ' ▌' : ''),
                      styleSheet: MarkdownStyleSheet(
                        p: const TextStyle(color: kText, fontSize: 14, height: 1.5),
                        code: const TextStyle(
                          color: kCyan,
                          backgroundColor: kSurface,
                          fontFamily: 'monospace',
                          fontSize: 12,
                        ),
                        codeblockDecoration: BoxDecoration(
                          color: kSurface,
                          borderRadius: BorderRadius.circular(6),
                          border: Border.all(color: kBorder),
                        ),
                      ),
                    )
                  else
                    Text(
                      msg.content,
                      style: const TextStyle(color: kText, fontSize: 14, height: 1.5),
                    ),
                  const SizedBox(height: 4),
                  Text(
                    timeago.format(msg.time),
                    style: const TextStyle(fontSize: 10, color: kMuted),
                  ),
                ],
              ),
            ),
          ),
          if (_isUser) ...[
            const SizedBox(width: 8),
            const CircleAvatar(
              radius: 14,
              backgroundColor: kPrimary,
              child: Icon(Icons.person_outline, size: 14, color: kBg),
            ),
          ],
        ],
      ),
    );
  }
}

class _InputBar extends StatefulWidget {
  final TextEditingController controller;
  final VoidCallback onSend;
  const _InputBar({required this.controller, required this.onSend});

  @override
  State<_InputBar> createState() => _InputBarState();
}

class _InputBarState extends State<_InputBar> {
  bool _voiceMode = false;

  void _onVoiceResult(String text) {
    widget.controller.text = text;
    setState(() => _voiceMode = false);
    widget.onSend();
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.of(context).viewInsets.bottom;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 250),
      color: kSurface,
      padding: EdgeInsets.fromLTRB(12, _voiceMode ? 24 : 8, 12, (_voiceMode ? 24 : 8) + bottom),
      child: SafeArea(
        top: false,
        child: _voiceMode
            ? Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  VoiceButton(onResult: _onVoiceResult),
                  const SizedBox(height: 12),
                  TextButton.icon(
                    onPressed: () => setState(() => _voiceMode = false),
                    icon: const Icon(Icons.keyboard_outlined, size: 16),
                    label: const Text('Switch to keyboard'),
                    style: TextButton.styleFrom(foregroundColor: kMuted),
                  ),
                ],
              )
            : Row(
                children: [
                  IconButton(
                    onPressed: () => setState(() => _voiceMode = true),
                    icon: const Icon(Icons.mic_none_outlined),
                    color: kMuted,
                    tooltip: 'Voice input',
                    style: IconButton.styleFrom(
                      backgroundColor: kCard,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: TextField(
                      controller: widget.controller,
                      minLines: 1,
                      maxLines: 5,
                      textCapitalization: TextCapitalization.sentences,
                      onSubmitted: (_) => widget.onSend(),
                      decoration: const InputDecoration(
                        hintText: 'Message...',
                        contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton(
                    onPressed: widget.onSend,
                    icon: const Icon(Icons.send_rounded),
                    color: kPrimary,
                    style: IconButton.styleFrom(
                      backgroundColor: kPrimary.withAlpha(20),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                  ),
                ],
              ),
      ),
    );
  }
}

class _EmptyChat extends StatelessWidget {
  final String agentName;
  const _EmptyChat({required this.agentName});

  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.chat_bubble_outline, color: kMuted, size: 48),
        const SizedBox(height: 12),
        Text(
          'Start a conversation',
          style: Theme.of(context).textTheme.bodyMedium!.copyWith(color: kMuted),
        ),
        const SizedBox(height: 4),
        Text(
          'Talking to $agentName',
          style: Theme.of(context).textTheme.bodySmall!.copyWith(color: kMuted),
        ),
      ],
    ),
  );
}

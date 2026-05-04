import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:provider/provider.dart';
import 'package:timeago/timeago.dart' as timeago;
import '../client.dart';
import '../models.dart';
import '../theme.dart';
import '../widgets/voice_button.dart';

class GlobalChatTab extends StatefulWidget {
  const GlobalChatTab({super.key});

  @override
  State<GlobalChatTab> createState() => _GlobalChatTabState();
}

class _GlobalChatTabState extends State<GlobalChatTab> {
  final _scroll = ScrollController();
  final _input  = TextEditingController();
  final List<ChatMessage> _messages = [];
  bool _streaming = false;
  StreamSubscription<Map<String, dynamic>>? _sub;

  @override
  void initState() {
    super.initState();
    _sub = context.read<WactorzClient>().chatStream.listen(_onEvent);
  }

  @override
  void dispose() {
    _sub?.cancel();
    _scroll.dispose();
    _input.dispose();
    super.dispose();
  }

  void _onEvent(Map<String, dynamic> msg) {
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
          setState(() {
            final last = _messages.removeLast();
            _messages.add(last.copyWith(isStreaming: false));
            _streaming = false;
          });
        }
      case 'chat':
        final from = msg['from'] as String? ?? '';
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
    final client = context.watch<WactorzClient>();
    final connected = client.connState == WsState.connected;

    return Column(
      children: [
        if (!connected)
          Container(
            width: double.infinity,
            color: kAmber.withAlpha(20),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
            child: const Text(
              'Not connected — messages will be sent once reconnected',
              style: TextStyle(fontSize: 12, color: kAmber),
              textAlign: TextAlign.center,
            ),
          ),
        Expanded(
          child: _messages.isEmpty
              ? const _EmptyHint()
              : ListView.builder(
                  controller: _scroll,
                  padding: const EdgeInsets.all(12),
                  itemCount: _messages.length,
                  itemBuilder: (_, i) => _Bubble(msg: _messages[i]),
                ),
        ),
        _InputBar(controller: _input, onSend: _send, enabled: connected),
      ],
    );
  }
}

class _Bubble extends StatelessWidget {
  final ChatMessage msg;
  const _Bubble({required this.msg});

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
                  bottomLeft: _isUser
                      ? const Radius.circular(14)
                      : Radius.zero,
                  bottomRight: _isUser
                      ? Radius.zero
                      : const Radius.circular(14),
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
  final bool enabled;
  const _InputBar({
    required this.controller,
    required this.onSend,
    required this.enabled,
  });

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
                    onPressed: widget.enabled ? () => setState(() => _voiceMode = true) : null,
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
                      enabled: widget.enabled,
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
                    onPressed: widget.enabled ? widget.onSend : null,
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

class _EmptyHint extends StatelessWidget {
  const _EmptyHint();

  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.chat_bubble_outline, color: kMuted, size: 48),
        const SizedBox(height: 12),
        Text(
          'Global chat',
          style: Theme.of(context)
              .textTheme
              .bodyMedium!
              .copyWith(color: kMuted),
        ),
        const SizedBox(height: 4),
        Text(
          'Messages are routed to the main actor.\nTry /help for available commands.',
          textAlign: TextAlign.center,
          style: Theme.of(context)
              .textTheme
              .bodySmall!
              .copyWith(color: kMuted),
        ),
      ],
    ),
  );
}

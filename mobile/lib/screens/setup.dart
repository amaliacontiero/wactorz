import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../theme.dart';

class SetupScreen extends StatefulWidget {
  final void Function(String url) onConnect;
  const SetupScreen({super.key, required this.onConnect});

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  final _ctrl = TextEditingController(text: 'http://');
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((p) {
      final saved = p.getString('server_url');
      if (saved != null && saved.isNotEmpty) {
        _ctrl.text = saved;
      }
    });
  }

  Future<void> _connect() async {
    final url = _ctrl.text.trim();
    if (url.isEmpty || url == 'http://') return;
    setState(() => _busy = true);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('server_url', url);
    widget.onConnect(url);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const _Logo(),
              const SizedBox(height: 48),
              Text(
                'Server URL',
                style: Theme.of(context)
                    .textTheme
                    .labelMedium!
                    .copyWith(color: kMuted),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _ctrl,
                keyboardType: TextInputType.url,
                autocorrect: false,
                onSubmitted: (_) => _connect(),
                decoration: const InputDecoration(
                  hintText: 'http://192.168.x.x:8888',
                  prefixIcon: Icon(Icons.dns_outlined, color: kMuted, size: 18),
                ),
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: _busy ? null : _connect,
                style: FilledButton.styleFrom(
                  backgroundColor: kPrimary,
                  foregroundColor: kBg,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
                child: _busy
                    ? const SizedBox(
                        height: 18,
                        width: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Text('Connect', style: TextStyle(fontWeight: FontWeight.w600)),
              ),
              const SizedBox(height: 24),
              Text(
                'Point to your wactorz monitor instance.\nHTTPS required for PWA / service worker.',
                textAlign: TextAlign.center,
                style: Theme.of(context)
                    .textTheme
                    .bodySmall!
                    .copyWith(color: kMuted),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Logo extends StatelessWidget {
  const _Logo();

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Container(
          width: 72,
          height: 72,
          decoration: BoxDecoration(
            color: kPrimary.withAlpha(20),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: kPrimary.withAlpha(60)),
          ),
          child: const Icon(Icons.hub_outlined, color: kPrimary, size: 36),
        ),
        const SizedBox(height: 16),
        Text(
          'wactorz',
          style: Theme.of(context).textTheme.headlineMedium!.copyWith(
            color: kPrimary,
            fontWeight: FontWeight.w700,
            letterSpacing: -0.5,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          'actor monitoring',
          style: Theme.of(context)
              .textTheme
              .bodySmall!
              .copyWith(color: kMuted),
        ),
      ],
    );
  }
}

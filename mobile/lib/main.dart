import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'client.dart';
import 'services/tts_service.dart';
import 'theme.dart';
import 'screens/setup.dart';
import 'screens/home.dart';

Future<void> clearSavedUrl() async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.remove('server_url');
}

void main() {
  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => WactorzClient()),
        ChangeNotifierProvider(create: (_) => TtsService()),
      ],
      child: const WactorzApp(),
    ),
  );
}

class WactorzApp extends StatelessWidget {
  const WactorzApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'wactorz',
      theme: buildTheme(),
      debugShowCheckedModeBanner: false,
      home: const _Gate(),
    );
  }
}

class _Gate extends StatefulWidget {
  const _Gate();

  @override
  State<_Gate> createState() => _GateState();
}

class _GateState extends State<_Gate> {
  bool _ready = false;
  bool _hasUrl = false;

  @override
  void initState() {
    super.initState();
    _checkSaved();
  }

  Future<void> _checkSaved() async {
    final prefs = await SharedPreferences.getInstance();
    final url = prefs.getString('server_url') ?? '';
    if (url.isNotEmpty && url != 'http://') {
      if (mounted) {
        context.read<WactorzClient>().configure(url);
        context.read<TtsService>().setBaseUrl(url);
      }
      setState(() { _ready = true; _hasUrl = true; });
    } else {
      setState(() { _ready = true; _hasUrl = false; });
    }
  }

  void _onConnect(String url) {
    context.read<WactorzClient>().configure(url);
    context.read<TtsService>().setBaseUrl(url);
    setState(() => _hasUrl = true);
  }

  Future<void> _onDisconnect() async {
    await clearSavedUrl();
    if (!mounted) return;
    context.read<WactorzClient>().disconnect();
    context.read<TtsService>().stop();
    setState(() => _hasUrl = false);
  }

  @override
  Widget build(BuildContext context) {
    if (!_ready) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator(color: kPrimary)),
      );
    }
    if (!_hasUrl) {
      return SetupScreen(onConnect: _onConnect);
    }
    return HomeScreen(onDisconnect: _onDisconnect);
  }
}

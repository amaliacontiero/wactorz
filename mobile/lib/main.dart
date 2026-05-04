import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'client.dart';
import 'theme.dart';
import 'screens/setup.dart';
import 'screens/home.dart';

void main() {
  runApp(
    ChangeNotifierProvider(
      create: (_) => WactorzClient(),
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
      if (mounted) context.read<WactorzClient>().configure(url);
      setState(() { _ready = true; _hasUrl = true; });
    } else {
      setState(() { _ready = true; _hasUrl = false; });
    }
  }

  void _onConnect(String url) {
    context.read<WactorzClient>().configure(url);
    setState(() => _hasUrl = true);
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
    return const HomeScreen();
  }
}

import 'package:flutter_test/flutter_test.dart';
import 'package:wactorz/main.dart';

void main() {
  testWidgets('app renders without crashing', (tester) async {
    await tester.pumpWidget(const WactorzApp());
    await tester.pump();
    expect(find.byType(WactorzApp), findsOneWidget);
  });
}

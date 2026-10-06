import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';

/// Which source the QR picture comes from.
///
/// Both apps used to load Razorpay's hosted image_url with Image.network, so
/// showing a code depended on the phone reaching rzp.io - a different host from
/// the API, over whatever wifi the stall is on. It worked in the rider app and
/// answered "Couldn't load the QR" in the merchant app over a perfectly good
/// order, with a customer standing there waiting to pay.
void main() {
  // A 1x1 png, so the decoder has something real to chew on.
  final onePixelPng = base64Decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGMAAQAABQAB'
    'oIJXOQAAAABJRU5ErkJggg==',
  );

  test('the bytes are preferred over the link when both arrive', () {
    final qr = UpiQr.fromJson({
      'image_url': 'https://rzp.io/i/unreachable',
      'image_png': base64Encode(onePixelPng),
      'amount': '150',
      'expires_at': '2026-01-01T14:30:00Z',
    });

    expect(qr.pngBytes, isNotNull);
    expect(qr.pngBytes, onePixelPng);
    expect(qr.imageUrl, 'https://rzp.io/i/unreachable');
  });

  test('a response without the bytes still parses, for an older server', () {
    final qr = UpiQr.fromJson({
      'image_url': 'https://rzp.io/i/abc',
      'amount': '150',
      'expires_at': '2026-01-01T14:30:00Z',
    });

    expect(qr.pngBytes, isNull);
    expect(qr.imageUrl, 'https://rzp.io/i/abc');
  });

  test('an empty image_png counts as absent rather than as empty bytes', () {
    final qr = UpiQr.fromJson({
      'image_url': 'https://rzp.io/i/abc',
      'image_png': '',
      'amount': '150',
      'expires_at': '2026-01-01T14:30:00Z',
    });

    expect(qr.pngBytes, isNull);
  });

  testWidgets('with bytes it renders them and never touches the network',
      (tester) async {
    // The regression. Image.network in a test throws on the HTTP attempt, so a
    // widget that reached for the link here would fail this outright.
    final qr = UpiQr(
      'https://rzp.io/i/unreachable',
      150,
      DateTime(2026, 1, 1),
      pngBytes: onePixelPng,
    );

    await tester.pumpWidget(
      MaterialApp(home: Scaffold(body: UpiQrImage(qr: qr))),
    );
    await tester.pumpAndSettle();

    expect(find.byType(Image), findsOneWidget);
    final image = tester.widget<Image>(find.byType(Image));
    expect(image.image, isA<MemoryImage>());
    expect(find.textContaining("Couldn't show the QR"), findsNothing);
  });

  testWidgets('without bytes it falls back to the link', (tester) async {
    final qr = UpiQr('https://rzp.io/i/abc', 150, DateTime(2026, 1, 1));

    await tester.pumpWidget(
      MaterialApp(home: Scaffold(body: UpiQrImage(qr: qr))),
    );

    final image = tester.widget<Image>(find.byType(Image));
    expect(image.image, isA<NetworkImage>());
  });
}

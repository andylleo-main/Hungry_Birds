import 'package:flutter/material.dart';

import '../api/api_client.dart';

/// The QR picture, from whichever source arrived.
///
/// One widget for both apps so they cannot disagree about the preference. They
/// did disagree in effect once already: both loaded Razorpay's hosted
/// `image_url` with Image.network, which makes showing a QR depend on the phone
/// reaching rzp.io - a different host from the API, over whatever wifi the
/// stall is on. One app managed it and the other answered "Couldn't load the
/// QR" over a perfectly good order with a customer waiting to pay.
///
/// So the bytes the API now sends down come first, and the link is only the
/// fallback for when that fetch failed server-side.
class UpiQrImage extends StatelessWidget {
  const UpiQrImage({super.key, required this.qr, this.maxHeight = 280});

  final UpiQr qr;
  final double maxHeight;

  @override
  Widget build(BuildContext context) {
    final bytes = qr.pngBytes;

    return ConstrainedBox(
      constraints: BoxConstraints(maxHeight: maxHeight),
      child: bytes != null
          ? Image.memory(bytes, fit: BoxFit.contain, errorBuilder: _failed)
          : Image.network(
              qr.imageUrl,
              fit: BoxFit.contain,
              errorBuilder: _failed,
              loadingBuilder: (_, child, progress) => progress == null
                  ? child
                  : const Padding(
                      padding: EdgeInsets.all(40),
                      child: CircularProgressIndicator(),
                    ),
            ),
    );
  }

  /// Says what to do rather than only what broke. Cash is always available and
  /// is the right move when the code will not appear.
  static Widget _failed(BuildContext _, Object __, StackTrace? ___) =>
      const Padding(
        padding: EdgeInsets.all(24),
        child: Text(
          "Couldn't show the QR. Take cash instead.",
          textAlign: TextAlign.center,
        ),
      );
}

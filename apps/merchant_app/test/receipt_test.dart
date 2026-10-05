import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:merchant_app/services/receipt.dart';

/// The kitchen ticket, checked without a printer.
///
/// The transport cannot be tested here - there is no Android SDK and no
/// hardware - which is exactly why the bytes are built in pure Dart instead of
/// inside a plugin. What a stall actually tears off is decided in this file, and
/// this file can be run.
///
/// The decoded text is asserted rather than the raw bytes, because the escape
/// sequences are not the interesting part: the layout is. A ticket where a long
/// dish name silently loses its tail is a ticket that gets the wrong food made.
void main() {
  Order order({
    PaymentStatus paymentStatus = PaymentStatus.paid,
    List<OrderLineItem> items = const [],
    String? note,
    int? token = 7,
    String orderNumber = '014237-5096',
    bool delivery = false,
    String? location,
    double total = 150,
  }) =>
      Order(
        id: 'o1',
        orderNumber: orderNumber,
        tokenNumber: token,
        vendorId: 'v1',
        customerId: 'c1',
        status: OrderStatus.accepted,
        paymentMethod: paymentStatus == PaymentStatus.due ? 'cod' : 'online',
        paymentStatus: paymentStatus,
        totalAmount: total,
        note: note,
        createdAt: DateTime(2026, 1, 1, 13, 42),
        updatedAt: DateTime(2026, 1, 1, 13, 42),
        items: items,
        customerName: 'Student',
        customerPhone: '+919876543210',
        fulfilmentType: delivery ? FulfilmentType.delivery : FulfilmentType.dineIn,
        deliveryLocation: delivery ? 'hostel_3' : null,
        deliveryLocationLabel: location,
      );

  OrderLineItem item(String name, int qty, {String? variant, double price = 60}) =>
      OrderLineItem(
        id: 'li-$name',
        menuItemId: 'm1',
        nameSnapshot: name,
        variantName: variant,
        priceSnapshot: price,
        quantity: qty,
      );

  /// Strips the ESC/POS commands and returns the lines a human would read.
  ///
  /// Walks the byte stream rather than filtering control characters, because the
  /// parameter bytes of a command are themselves printable: `ESC a 1` (centre)
  /// is 0x1B 0x61 0x31, and dropping only the 0x1B leaves a literal "a1" in the
  /// middle of the receipt. Asking a regex to do this is what produced a first
  /// run where every expectation failed on invisible junk.
  ///
  /// Unknown commands throw rather than being skipped, so if the builder ever
  /// emits a sequence this does not model, the tests say so instead of quietly
  /// measuring the wrong text.
  List<String> printed(Order o, {int columns = 32}) {
    const lengths = <int, Map<int, int>>{
      0x1B: {0x40: 2, 0x61: 3, 0x45: 3, 0x64: 3}, // reset, align, bold, feed
      0x1D: {0x21: 3, 0x56: 4}, // size, cut
    };

    final bytes = Receipt(columns: columns).build(o);
    final out = <int>[];
    var i = 0;
    while (i < bytes.length) {
      final b = bytes[i];
      final command = lengths[b];
      if (command == null) {
        out.add(b);
        i++;
        continue;
      }
      final length = command[bytes[i + 1]];
      if (length == null) {
        fail('unmodelled ESC/POS command '
            '0x${b.toRadixString(16)} 0x${bytes[i + 1].toRadixString(16)} at $i');
      }
      i += length;
    }

    return latin1.decode(out).split('\n').map((l) => l.trimRight()).toList();
  }

  group('what the slip says', () {
    test('the fulfilment mode is the headline', () {
      // It decides what happens to the bag once it is packed, so it is the one
      // thing that has to be readable from across a counter.
      expect(printed(order()).first, 'DINE IN');
      expect(printed(order(delivery: true, location: 'Hostel 3')).first, 'DELIVERY');
    });

    test('a delivery says where it is going', () {
      expect(printed(order(delivery: true, location: 'Hostel 3')), contains('Hostel 3'));
    });

    test('the token is on it, because that is what gets called out', () {
      expect(printed(order(token: 7)), contains('TOKEN 7'));
    });

    test('the long number is on it too, for when somebody rings up', () {
      expect(printed(order()), contains('Order no. 014237-5096'));
    });

    test('an order with no token still prints', () {
      // Null until payment lands, and an older order never had one. A ticket
      // that throws rather than printing is worse than a ticket with a gap.
      final lines = printed(order(token: null));
      expect(lines.any((l) => l.startsWith('TOKEN')), isFalse);
      expect(lines, contains('Order no. 014237-5096'));
    });

    test('every line item is there with its quantity', () {
      final lines = printed(order(items: [item('Paneer Chilli', 1), item('Roti', 4)]));
      expect(lines, contains('1x Paneer Chilli'));
      expect(lines, contains('4x Roti'));
    });

    test('the size prints beside the dish', () {
      final lines = printed(order(items: [item('Butter Paneer', 1, variant: 'Half')]));
      expect(lines, contains('1x Butter Paneer (Half)'));
    });

    test('the time is on it', () {
      expect(printed(order()), contains('Ordered at 1:42 PM'));
    });

    test('the total is right-aligned against the edge', () {
      final lines = printed(order(total: 150));
      final total = lines.firstWhere((l) => l.startsWith('TOTAL'));
      // Trimmed above, so what is checked is that both halves made it onto one
      // line rather than wrapping.
      expect(total, startsWith('TOTAL'));
      expect(total, endsWith('Rs.150'));
    });
  });

  group('money the stall still has to collect', () {
    test('a pay-on-delivery ticket says COLLECT, loudly', () {
      // The one line that changes what the person packing the bag does. A
      // prepaid order is handed over; a cash one is handed over and money comes
      // back.
      final lines = printed(order(paymentStatus: PaymentStatus.due, total: 150));
      expect(lines, contains('COLLECT Rs.150'));
      expect(lines, contains('ON DELIVERY'));
    });

    test('a prepaid ticket says nothing about collecting', () {
      final lines = printed(order(total: 150));
      expect(lines.any((l) => l.contains('COLLECT')), isFalse);
    });

    test('the amount to collect matches the total', () {
      final lines = printed(order(paymentStatus: PaymentStatus.due, total: 1250));
      expect(lines.firstWhere((l) => l.startsWith('TOTAL')), endsWith('Rs.1250'));
      expect(lines, contains('COLLECT Rs.1250'));
    });

    test('it still fits 58mm paper', () {
      final lines = printed(order(paymentStatus: PaymentStatus.due, total: 123456));
      for (final l in lines) {
        expect(l.length, lessThanOrEqualTo(32), reason: '"$l" is ${l.length} chars');
      }
    });
  });

  group('the note', () {
    test('prints under its own heading', () {
      final lines = printed(order(note: 'No onions please'));
      expect(lines, contains('NOTE'));
      expect(lines, contains('No onions please'));
    });

    test('is absent when there is none, rather than an empty heading', () {
      expect(printed(order()).contains('NOTE'), isFalse);
    });

    test('a long note wraps instead of being cut off', () {
      final lines = printed(order(
        note: 'Please make it extra spicy and pack the chutney separately in a '
            'small box, and ring when you are outside',
      ));
      expect(lines.any((l) => l.contains('chutney')), isTrue);
      expect(lines.any((l) => l.contains('outside')), isTrue);
      for (final l in lines) {
        expect(l.length, lessThanOrEqualTo(32), reason: 'overflowed the paper: "$l"');
      }
    });
  });

  group('fitting the paper', () {
    test('a long dish name wraps under its quantity', () {
      final lines = printed(order(
        items: [item('Paneer Butter Masala with extra gravy and two rotis', 2)],
      ));
      // The whole name survives somewhere.
      final joined = lines.join(' ');
      expect(joined, contains('Paneer Butter Masala'));
      expect(joined, contains('two rotis'));
      for (final l in lines) {
        expect(l.length, lessThanOrEqualTo(32), reason: 'overflowed the paper: "$l"');
      }
    });

    test('nothing overflows 32 columns on 58mm paper', () {
      final lines = printed(order(
        items: [
          item('Hyderabadi Dum Biryani', 2, variant: 'Full Plate'),
          item('Chicken 65 Dry', 1),
        ],
        note: 'Less oil, no coriander',
        total: 1250,
      ));
      for (final l in lines) {
        expect(l.length, lessThanOrEqualTo(32), reason: '"$l" is ${l.length} chars');
      }
    });

    test('80mm paper uses the wider line', () {
      final lines = printed(
        order(items: [item('Paneer Butter Masala with extra gravy', 1)]),
        columns: 48,
      );
      // At 48 columns this fits on one line, where at 32 it would not.
      expect(lines, contains('1x Paneer Butter Masala with extra gravy'));
    });

    test('a single unbreakable word is cut rather than lost', () {
      // Z because it appears nowhere else on the slip - counting A's picked up
      // the one in "TOTAL".
      final lines = printed(order(items: [item('Z' * 60, 1)]));
      for (final l in lines) {
        expect(l.length, lessThanOrEqualTo(32));
      }
      // Nothing is lost - every character of the name is on the paper
      // somewhere, just across several lines.
      expect(lines.join().split('Z').length - 1, 60);
    });
  });

  group('what the printer can actually render', () {
    test('the rupee sign becomes Rs. rather than a blank box', () {
      // A thermal printer's default code page is single-byte and has no ₹.
      final bytes = Receipt().build(order(total: 99));
      expect(latin1.decode(bytes), contains('Rs.99'));
    });

    test('a name it cannot print does not stop the ticket', () {
      // A stall with no ticket cannot cook. Imperfect beats absent.
      final bytes = Receipt().build(order(items: [item('पनीर टिक्का', 1)]));
      final text = latin1.decode(bytes);
      expect(text, contains('1x'));
      expect(text, contains('TOTAL'));
    });

    test('it starts with a reset and ends with a cut', () {
      final bytes = Receipt().build(order());
      expect(bytes.take(2).toList(), [0x1B, 0x40]);
      expect(bytes.sublist(bytes.length - 4), [0x1D, 0x56, 0x42, 0x00]);
    });

    test('the test page prints a ruler the width of the paper', () {
      // So somebody can see at a glance whether the column setting matches the
      // paper actually loaded - the one thing that cannot be checked from here.
      final text = latin1.decode(Receipt(columns: 32).testPage());
      expect(text, contains('1234567890'));
      expect(text, contains('32 columns'));
    });
  });
}

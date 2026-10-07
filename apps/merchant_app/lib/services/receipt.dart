import 'dart:convert';
import 'dart:typed_data';

import 'package:hb_shared/hb_shared.dart';
import 'package:intl/intl.dart';

/// Turns an order into the bytes a thermal printer understands.
///
/// Hand-written ESC/POS rather than a package. The command set used here is six
/// escape sequences that have not changed since the 1990s, the layout is fixed,
/// and the alternative was a dependency last published two years ago whose paper
/// -size handling could not be verified from here. Writing it out also makes the
/// whole thing pure Dart with no plugin, which is the only reason any of this is
/// testable in a project with no printer and no Android SDK.
///
/// Everything about the physical device lives in printer.dart; this file knows
/// only about columns.
class Receipt {
  /// Characters per line. 32 for 58mm paper, 48 for 80mm.
  ///
  /// 58mm is the common size for a printer that pairs with a phone, and is what
  /// this stall uses. Kept a parameter rather than a constant because the only
  /// thing that changes with the paper is this number, so a different printer
  /// should be a setting rather than a rebuild.
  final int columns;

  const Receipt({this.columns = 32});

  // --- ESC/POS ---------------------------------------------------------------
  static const _esc = 0x1B;
  static const _gs = 0x1D;

  List<int> _init() => [_esc, 0x40]; // reset
  List<int> _align(int n) => [_esc, 0x61, n]; // 0 left, 1 centre, 2 right
  List<int> _bold(bool on) => [_esc, 0x45, on ? 1 : 0];
  List<int> _size(int w, int h) => [_gs, 0x21, (w << 4) | h]; // 0..7 each
  List<int> _feed(int lines) => [_esc, 0x64, lines];
  List<int> _cut() => [_gs, 0x56, 0x42, 0x00]; // partial cut, feed first

  /// Latin-1 rather than UTF-8.
  ///
  /// A thermal printer's default code page is single-byte; handing it UTF-8
  /// prints mojibake for anything above ASCII. Characters outside Latin-1 are
  /// replaced rather than allowed to throw - a dish named in Devanagari should
  /// print as something imperfect rather than stop the ticket from printing at
  /// all, because a stall with no ticket cannot cook.
  List<int> _text(String s) {
    final safe = s.replaceAll('₹', 'Rs.');
    return latin1.encode(safe.replaceAll(RegExp(r'[^\x00-\xFF]'), '?'));
  }

  List<int> _line(String s) => [..._text(s), 0x0A];

  /// Wraps on spaces so a long dish name does not lose its tail.
  ///
  /// [hanging] indents continuation lines, so a wrapped item still reads as one
  /// entry under its quantity rather than looking like a second dish.
  List<String> wrap(String text, int width, {int hanging = 0}) {
    if (width <= 0) return [text];
    final words = text.split(RegExp(r'\s+')).where((w) => w.isNotEmpty).toList();
    if (words.isEmpty) return [''];

    final lines = <String>[];
    var current = '';
    var limit = width;

    void push() {
      lines.add(lines.isEmpty ? current : ' ' * hanging + current);
      current = '';
      limit = width - hanging;
    }

    for (final word in words) {
      if (current.isEmpty) {
        current = word;
      } else if (current.length + 1 + word.length <= limit) {
        current = '$current $word';
      } else {
        push();
        current = word;
      }
      // A single word longer than the line has to be cut somewhere.
      while (current.length > limit) {
        lines.add((lines.isEmpty ? '' : ' ' * hanging) + current.substring(0, limit));
        current = current.substring(limit);
      }
    }
    if (current.isNotEmpty) push();
    return lines;
  }

  /// A label on the left and a value hard against the right edge.
  String _spread(String left, String right) {
    final gap = columns - left.length - right.length;
    if (gap < 1) return '$left $right';
    return left + ' ' * gap + right;
  }

  String _rule() => '-' * columns;

  /// The ticket, in the format the stall asked for.
  Uint8List build(Order order, {String stallName = 'Hungry Birds'}) {
    final bytes = <int>[];

    bytes.addAll(_init());

    // How it is being handed over, biggest thing on the slip - it decides what
    // happens to the bag once it is packed.
    bytes.addAll(_align(1));
    bytes.addAll(_size(1, 1));
    bytes.addAll(_bold(true));
    bytes.addAll(_line(order.isDelivery ? 'DELIVERY' : 'DINE IN'));
    bytes.addAll(_size(0, 0));
    if (order.isDelivery && order.deliveryLocationLabel != null) {
      bytes.addAll(_line(order.deliveryLocationLabel!));
    }
    bytes.addAll(_bold(false));
    bytes.addAll(_line(stallName));
    bytes.addAll(_line(''));

    // The token, big, because it is what gets called across the counter.
    bytes.addAll(_align(1));
    if (order.tokenNumber != null) {
      bytes.addAll(_size(1, 1));
      bytes.addAll(_bold(true));
      bytes.addAll(_line('TOKEN ${order.tokenNumber}'));
      bytes.addAll(_bold(false));
      bytes.addAll(_size(0, 0));
    }
    if (order.orderNumber.isNotEmpty) {
      bytes.addAll(_line('Order no. ${order.orderNumber}'));
    }

    bytes.addAll(_align(0));
    bytes.addAll(_line(_rule()));

    for (final item in order.items) {
      final qty = '${item.quantity}x ';
      final name = item.variantName == null
          ? item.nameSnapshot
          : '${item.nameSnapshot} (${item.variantName})';
      final wrapped = wrap(name, columns - qty.length, hanging: qty.length);
      bytes.addAll(_line('$qty${wrapped.first}'));
      for (final extra in wrapped.skip(1)) {
        bytes.addAll(_line(extra));
      }
    }

    bytes.addAll(_line(_rule()));

    // Three lines rather than one when cashback was spent, because the COLLECT
    // figure below is then smaller than the food and the stall has to be able to
    // see why from the slip alone. Printed as a subtraction - order value, the
    // discount, then what is owed - so it reads the way a bill reads.
    //
    // TOTAL stays the value of the food, because that is what the stall is owed
    // and what it reconciles against. Hungry Birds funds the discount.
    if (order.hasDiscount) {
      bytes.addAll(_line(_spread('Order', 'Rs.${order.totalAmount.toStringAsFixed(0)}')));
      bytes.addAll(
        _line(_spread('Cashback', '-Rs.${order.cashbackApplied.toStringAsFixed(0)}')),
      );
      bytes.addAll(_bold(true));
      bytes.addAll(_line(_spread('TO PAY', 'Rs.${order.amountDue.toStringAsFixed(0)}')));
      bytes.addAll(_bold(false));
    } else {
      bytes.addAll(_bold(true));
      bytes.addAll(_line(_spread('TOTAL', 'Rs.${order.totalAmount.toStringAsFixed(0)}')));
      bytes.addAll(_bold(false));
    }

    // The one line that changes what somebody does with the bag. A prepaid order
    // is handed over; a cash one is handed over *and* money comes back. Printing
    // it big, rather than as a note, because this is read at a counter during
    // service by whoever is packing - not by whoever took the order.
    if (order.isAwaitingCollection) {
      bytes.addAll(_line(''));
      bytes.addAll(_align(1));
      bytes.addAll(_size(1, 1));
      bytes.addAll(_bold(true));
      // amountDue, not the total. Whoever is packing the bag reads this line
      // and nothing else, so printing the gross here would have them ask the
      // customer for money the customer does not owe.
      bytes.addAll(_line('COLLECT Rs.${order.amountDue.toStringAsFixed(0)}'));
      bytes.addAll(_size(0, 0));
      bytes.addAll(_line('ON DELIVERY'));
      bytes.addAll(_bold(false));
      bytes.addAll(_align(0));
    }

    // Boxed and bold, to match how loudly the app shows it.
    //
    // A note is "no onion", "less spicy", an allergy. It is the one line on the
    // slip that changes what goes in the pan, and it is read side-on at a
    // counter mid-service - so it gets rules above and below to stop the eye
    // rather than sitting as another paragraph among the totals and times.
    //
    // Deliberately not double-height: that halves the usable width to sixteen
    // characters, and a note is the one field whose length nobody controls.
    // Legible and unmissable beats large and wrapped into nonsense.
    final note = order.note?.trim();
    if (note != null && note.isNotEmpty) {
      bytes.addAll(_line(''));
      bytes.addAll(_line(_rule()));
      bytes.addAll(_align(1));
      bytes.addAll(_bold(true));
      bytes.addAll(_line('** NOTE **'));
      bytes.addAll(_align(0));
      for (final line in wrap(note, columns)) {
        bytes.addAll(_line(line));
      }
      bytes.addAll(_bold(false));
      bytes.addAll(_line(_rule()));
    }

    bytes.addAll(_line(''));
    bytes.addAll(_line(
      'Ordered at ${DateFormat('h:mm a').format(order.createdAt.toLocal())}',
    ));

    // What the customer was told. Printed because the person packing the bag is
    // usually not the person who accepted the order, and this is the only place
    // they will see the promise somebody else made on their behalf.
    //
    // For a delivery this is the time at the door, buffer included - the stall
    // needs it in the kitchen's hands earlier than that, which is why the label
    // says where the clock is being read, not just when.
    if (order.readyBy != null) {
      bytes.addAll(_bold(true));
      bytes.addAll(_line(
        '${order.isDelivery ? 'At door by' : 'Ready by'} '
        '${DateFormat('h:mm a').format(order.readyBy!.toLocal())}',
      ));
      bytes.addAll(_bold(false));
    }

    // Fed before the cut so the ticket clears the tear bar - without this the
    // last line sits inside the mechanism and gets torn through.
    bytes.addAll(_feed(3));
    bytes.addAll(_cut());

    return Uint8List.fromList(bytes);
  }

  /// The smallest thing that could possibly print: text and newlines, nothing
  /// else.
  ///
  /// No reset, no alignment, no bold, no size, no feed command and no cut -
  /// every one of those is an escape sequence a given firmware may not
  /// implement, and a printer that meets a command it does not know can clear
  /// its buffer and print nothing at all.
  ///
  /// So this is the control case. If this prints and [testPage] does not, the
  /// problem is one of those commands and not the Bluetooth connection, which
  /// is a different fix and otherwise indistinguishable from the outside: both
  /// look like "it said it printed and nothing came out".
  Uint8List plainTest() {
    final bytes = <int>[];
    for (final line in [
      'HUNGRY BIRDS',
      'plain text test',
      '1234567890',
      'If you can read this, the',
      'connection works.',
    ]) {
      bytes.addAll(_text(line));
      bytes.add(0x0A);
    }
    // Blank lines rather than ESC d, for the same reason: a line feed is the
    // one byte every printer honours, and some of the paper has to clear the
    // tear bar or there is nothing to read.
    bytes.addAll([0x0A, 0x0A, 0x0A, 0x0A, 0x0A]);
    return Uint8List.fromList(bytes);
  }

  /// A short slip for checking the printer works, with no order needed.
  Uint8List testPage({String stallName = 'Hungry Birds'}) {
    final bytes = <int>[];
    bytes.addAll(_init());
    bytes.addAll(_align(1));
    bytes.addAll(_bold(true));
    bytes.addAll(_line(stallName));
    bytes.addAll(_bold(false));
    bytes.addAll(_line('Printer test'));
    bytes.addAll(_align(0));
    bytes.addAll(_line(_rule()));
    // Prints the ruler so the paper width can be checked by eye: if this wraps,
    // the column count is set too high for the paper in the machine.
    bytes.addAll(_line(List.generate(columns, (i) => '${(i + 1) % 10}').join()));
    bytes.addAll(_line('$columns columns'));
    bytes.addAll(_feed(3));
    bytes.addAll(_cut());
    return Uint8List.fromList(bytes);
  }
}

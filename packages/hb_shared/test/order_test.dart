import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';

/// The wire format of an order, which is the one thing both apps and the backend
/// have to agree about exactly.
///
/// Everything here is a decode or a wire string rather than a screen, because
/// every bug this file exists to catch is silent: a status that serialises under
/// the wrong name is rejected by the server as a bad request, and a payload that
/// fails to decode takes the whole list with it rather than the one order.
void main() {
  Map<String, dynamic> payload([Map<String, dynamic> overrides = const {}]) => {
        'id': 'o1',
        'vendor_id': 'v1',
        'customer_id': 'c1',
        'status': 'placed',
        'payment_method': 'cashfree',
        'total_amount': '180.50',
        'note': null,
        'created_at': '2026-01-01T10:00:00',
        'updated_at': '2026-01-01T10:00:00',
        'items': [
          {
            'id': 'li1',
            'menu_item_id': 'm1',
            'name_snapshot': 'Steamed momo',
            'price_snapshot': '90.25',
            'quantity': 2,
          }
        ],
        'customer_name': 'Student',
        'customer_phone': '+919876543210',
        ...overrides,
      };

  group('OrderStatus on the wire', () {
    test('every status has a distinct snake_case wire name', () {
      final wires = [for (final s in OrderStatus.values) s.wire];
      expect(wires.toSet().length, wires.length, reason: 'two statuses share a wire name');
      for (final wire in wires) {
        expect(wire, matches(RegExp(r'^[a-z_]+$')),
            reason: '$wire is not snake_case, so the API will reject it');
      }
    });

    test('wire names round-trip', () {
      // The reason `wire` exists rather than `name`: outForDelivery would
      // otherwise go out as "outForDelivery", be rejected, and come back as
      // unknown - which reads like a server fault rather than a client one.
      for (final status in OrderStatus.values) {
        expect(OrderStatus.fromJson(status.wire), status);
      }
    });

    test('a status this build has never heard of decodes rather than throwing', () {
      expect(OrderStatus.fromJson('being_couriered_by_drone'), OrderStatus.unknown);
    });

    test('an unknown status is treated as live work, not as finished', () {
      // Filing an order the app cannot name under "done" would hide it from the
      // stall. Showing it as something odd is the safe direction to be wrong in.
      expect(OrderStatus.unknown.isActive, isTrue);
      expect(OrderStatus.unknown.isTerminal, isFalse);
    });

    test('active and terminal partition the statuses', () {
      for (final status in OrderStatus.values) {
        expect(status.isActive, isNot(status.isTerminal), reason: '$status is in both or neither');
      }
      expect(OrderStatus.completed.isTerminal, isTrue);
      expect(OrderStatus.rejected.isTerminal, isTrue);
      expect(OrderStatus.cancelled.isTerminal, isTrue);
    });

    test('an unpaid order is still live, so the customer can finish paying', () {
      expect(OrderStatus.awaitingPayment.isActive, isTrue);
    });
  });

  group('Order.fromJson', () {
    test('reads a full payload', () {
      final order = Order.fromJson(payload());
      expect(order.id, 'o1');
      expect(order.status, OrderStatus.placed);
      // Decimals arrive from FastAPI as strings; parsing them as num would drop
      // the paise on some payloads and throw on others.
      expect(order.totalAmount, 180.50);
      expect(order.items.single.priceSnapshot, 90.25);
      expect(order.items.single.quantity, 2);
      expect(order.customerPhone, '+919876543210');
    });

    test('a payload from before delivery existed still decodes', () {
      // fulfilment_type and self_delivery are defaulted rather than required for
      // exactly this: an order serialised by an older server must not throw.
      final order = Order.fromJson(payload());
      expect(order.fulfilmentType, FulfilmentType.dineIn);
      expect(order.isDelivery, isFalse);
      expect(order.selfDelivery, isFalse);
      expect(order.deliveryLocation, isNull);
    });

    test('reads a delivery with a rider on it', () {
      final order = Order.fromJson(payload({
        'fulfilment_type': 'delivery',
        'delivery_location': 'hostel_3',
        'delivery_location_label': 'Hostel 3',
        'rider_id': 'r1',
        'rider_name': 'Rider',
        'rider_phone': '+919812345678',
      }));
      expect(order.isDelivery, isTrue);
      expect(order.deliveryLocationLabel, 'Hostel 3');
      expect(order.hasCourier, isTrue);
    });

    test('a merchant carrying it themselves also counts as having a courier', () {
      final order = Order.fromJson(payload({
        'fulfilment_type': 'delivery',
        'self_delivery': true,
      }));
      expect(order.riderId, isNull);
      expect(order.hasCourier, isTrue);
    });

    test('an unassigned delivery has no courier and no rider number', () {
      final order = Order.fromJson(payload({'fulfilment_type': 'delivery'}));
      expect(order.hasCourier, isFalse);
      // Numbers are exchanged by assignment, so a rider's phone never reaches a
      // customer they are not carrying for.
      expect(order.riderPhone, isNull);
    });

    test('one unfamiliar status does not cost the rest of the order', () {
      // The failure this replaced: a bare firstWhere threw StateError, and the
      // throw was swallowed badly enough in both callers that a stall's whole
      // queue blanked out over a single order.
      final order = Order.fromJson(payload({'status': 'queued_for_robot'}));
      expect(order.status, OrderStatus.unknown);
      expect(order.id, 'o1');
      expect(order.items, hasLength(1));
    });

    test('reads the two numbers an order carries', () {
      final order = Order.fromJson(payload({
        'order_number': '014237-5096',
        'token_number': 7,
      }));
      expect(order.orderNumber, '014237-5096');
      expect(order.tokenNumber, 7);
    });

    test('an order with no token yet decodes rather than throwing', () {
      // Null until it is paid for and reaches the stall's queue. A merchant's
      // list holds unpaid orders too, so this is the common case, not an edge.
      expect(Order.fromJson(payload()).tokenNumber, isNull);
    });

    test('an order from a server that predates order numbers still decodes', () {
      // Same reason fulfilment_type is defaulted: one unfamiliar order must not
      // take the whole response - and therefore the whole queue - with it.
      expect(Order.fromJson(payload()).orderNumber, '');
    });

    test('a delivery code is absent unless the server sent one', () {
      // The rider endpoints return a payload with no delivery_code field at all.
      // A rider who could read it could close an order without reaching anybody.
      expect(Order.fromJson(payload()).deliveryCode, isNull);
      expect(Order.fromJson(payload({'delivery_code': '4821'})).deliveryCode, '4821');
    });
  });

  group('FulfilmentType', () {
    test('wire names round-trip', () {
      expect(FulfilmentType.fromJson('dine_in'), FulfilmentType.dineIn);
      expect(FulfilmentType.fromJson('delivery'), FulfilmentType.delivery);
      expect(FulfilmentType.dineIn.wire, 'dine_in');
    });

    test('a mode this build does not know becomes unknown rather than throwing', () {
      expect(FulfilmentType.fromJson('pigeon'), FulfilmentType.unknown);
      expect(FulfilmentType.unknown.label, 'Other');
    });
  });

  group('FulfilmentSettings', () {
    test('enabledCodes is what the API takes, not what the screen draws', () {
      // The screen needs every location so it can draw the off ones off; the API
      // takes only the enabled codes.
      final settings = FulfilmentSettings.fromJson({
        'dine_in_enabled': true,
        'delivery_enabled': true,
        'locations': [
          {'code': 'hostel_3', 'label': 'Hostel 3', 'enabled': true},
          {'code': 'hostel_7', 'label': 'Hostel 7', 'enabled': false},
          {'code': 'library', 'label': 'Library', 'enabled': true},
        ],
      });
      expect(settings.locations, hasLength(3));
      expect(settings.enabledCodes, ['hostel_3', 'library']);
    });
  });
}

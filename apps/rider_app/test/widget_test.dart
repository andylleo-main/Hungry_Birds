import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:rider_app/state/rider_state.dart';

/// A rider's view of their own work, without a server.
///
/// The gate's three stages are what decide whether somebody sees a login form or
/// their deliveries, and the active filter is what keeps yesterday's finished
/// orders off a screen somebody is working from.
void main() {
  Order order(String id, OrderStatus status) => Order(
        id: id,
        vendorId: 'v1',
        customerId: 'c1',
        status: status,
        paymentMethod: 'cod',
        totalAmount: 120,
        note: null,
        createdAt: DateTime(2026, 1, 1),
        updatedAt: DateTime(2026, 1, 1),
        items: const [],
        customerName: 'Student',
        customerPhone: '+919876543210',
        fulfilmentType: FulfilmentType.delivery,
        deliveryLocation: 'hostel_3',
        deliveryLocationLabel: 'Hostel 3',
        riderId: 'r1',
      );

  test('a rider starts out being worked out, not logged out', () {
    final state = RiderState(ApiClient(baseUrl: 'http://x/api', authStorage: AuthStorage()));
    // Showing a login form before the stored token has been checked would make
    // every cold start look like a sign-out.
    expect(state.stage, RiderStage.loading);
    expect(state.active, isEmpty);
  });

  test('finished orders drop off the working list', () {
    final state = RiderState(ApiClient(baseUrl: 'http://x/api', authStorage: AuthStorage()));
    state.orders = [
      order('a', OrderStatus.ready),
      order('b', OrderStatus.outForDelivery),
      order('c', OrderStatus.completed),
      order('d', OrderStatus.cancelled),
    ];
    expect([for (final o in state.active) o.id], ['a', 'b']);
  });

  test('an out-for-delivery order is still live work', () {
    // Guards the enum change that added it: if outForDelivery were ever left out
    // of isActive, a rider carrying food would watch it vanish from their list.
    expect(OrderStatus.outForDelivery.isActive, isTrue);
    expect(OrderStatus.outForDelivery.wire, 'out_for_delivery');
  });
}

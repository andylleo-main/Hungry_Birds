import 'package:customer_app/state/cart_state.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hb_shared/hb_shared.dart';

MenuItem _item(String id, String name, double price) => MenuItem(
      id: id,
      name: name,
      description: null,
      price: price,
      categoryId: null,
      imageUrl: null,
      isAvailable: true,
    );

VendorDetail _vendor(String id, List<MenuItem> items) => VendorDetail(
      id: id,
      stallName: 'Stall $id',
      description: null,
      coverImageUrl: null,
      isApproved: true,
      isOpen: true,
      deliveryLocations: const [],
      categories: const [],
      uncategorizedItems: items,
    );

void main() {
  test('adding items accumulates quantity and total', () {
    final momo = _item('i1', 'Momo', 60);
    final vendor = _vendor('v1', [momo]);
    final cart = CartState();

    cart.add(momo, vendor);
    cart.add(momo, vendor);

    expect(cart.quantityOf('i1'), 2);
    expect(cart.itemCount, 2);
    expect(cart.total, 120);
  });

  test('removing the last unit empties the cart and drops the vendor', () {
    final momo = _item('i1', 'Momo', 60);
    final vendor = _vendor('v1', [momo]);
    final cart = CartState();

    cart.add(momo, vendor);
    cart.removeOne(momo);

    expect(cart.isEmpty, isTrue);
    expect(cart.vendor, isNull);
  });

  test('adding from a second vendor replaces the cart', () {
    final momo = _item('i1', 'Momo', 60);
    final roll = _item('i2', 'Roll', 80);
    final vendorA = _vendor('v1', [momo]);
    final vendorB = _vendor('v2', [roll]);
    final cart = CartState();

    cart.add(momo, vendorA);
    expect(cart.conflictsWith(vendorB), isTrue);

    cart.add(roll, vendorB);

    expect(cart.vendor!.id, 'v2');
    expect(cart.quantityOf('i1'), 0);
    expect(cart.quantityOf('i2'), 1);
    expect(cart.total, 80);
  });

  test('toOrderItems maps to the API payload shape', () {
    final momo = _item('i1', 'Momo', 60);
    final vendor = _vendor('v1', [momo]);
    final cart = CartState();

    cart.add(momo, vendor);
    cart.add(momo, vendor);

    expect(cart.toOrderItems(), [
      {'menu_item_id': 'i1', 'quantity': 2},
    ]);
  });
}

import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import '../state/merchant_state.dart';
import '../state/orders_state.dart';
import 'analytics_tab.dart';
import 'menu_tab.dart';
import 'new_order_dialog.dart';
import 'orders_tab.dart';
import 'riders_tab.dart';
import 'stall_tab.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final vendorId = context.read<MerchantState>().vendor!.id;

    return ChangeNotifierProvider(
      create: (context) => OrdersState(context.read<ApiClient>())..start(vendorId),
      child: _NewOrderWatcher(
        child: Scaffold(
          body: IndexedStack(
            index: _index,
            children: const [OrdersTab(), MenuTab(), AnalyticsTab(), RidersTab(), StallTab()],
          ),
          bottomNavigationBar: BottomNavigationBar(
            currentIndex: _index,
            onTap: (i) => setState(() => _index = i),
            // Fixed, because a five-item BottomNavigationBar defaults to the
            // shifting style, which hides the labels of everything but the
            // selected tab.
            type: BottomNavigationBarType.fixed,
            selectedFontSize: 11,
            unselectedFontSize: 11,
            items: const [
              BottomNavigationBarItem(
                icon: Icon(Icons.receipt_long_outlined),
                activeIcon: Icon(Icons.receipt_long),
                label: 'Orders',
              ),
              BottomNavigationBarItem(
                icon: Icon(Icons.restaurant_menu_outlined),
                activeIcon: Icon(Icons.restaurant_menu),
                label: 'Menu',
              ),
              BottomNavigationBarItem(
                icon: Icon(Icons.insights_outlined),
                activeIcon: Icon(Icons.insights),
                label: 'Numbers',
              ),
              BottomNavigationBarItem(
                icon: Icon(Icons.pedal_bike_outlined),
                activeIcon: Icon(Icons.pedal_bike),
                label: 'Riders',
              ),
              BottomNavigationBarItem(
                icon: Icon(Icons.storefront_outlined),
                activeIcon: Icon(Icons.storefront),
                label: 'Stall',
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Raises the new-order dialog when one lands.
///
/// Sits here rather than inside OrdersState because showing a dialog needs a
/// BuildContext and a ChangeNotifier listening to a socket has none. Wrapping
/// the whole dashboard means the interruption appears whichever tab the merchant
/// is on - a stall editing its menu still finds out an order arrived.
class _NewOrderWatcher extends StatefulWidget {
  const _NewOrderWatcher({required this.child});

  final Widget child;

  @override
  State<_NewOrderWatcher> createState() => _NewOrderWatcherState();
}

class _NewOrderWatcherState extends State<_NewOrderWatcher> {
  /// Stops a rebuild from stacking a second dialog over the first.
  bool _showing = false;

  @override
  Widget build(BuildContext context) {
    final pending = context.watch<OrdersState>().pendingAlerts;

    if (pending.isNotEmpty && !_showing) {
      _showing = true;
      // After this frame: showing a dialog during build throws, and the
      // notification that brings us here arrives mid-build often enough that
      // this is not a theoretical concern.
      WidgetsBinding.instance.addPostFrameCallback((_) async {
        if (!mounted) return;
        await NewOrderDialog.show(context, pending.first);
        if (mounted) setState(() => _showing = false);
      });
    }

    return widget.child;
  }
}

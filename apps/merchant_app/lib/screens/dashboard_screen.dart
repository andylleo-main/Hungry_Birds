import 'package:flutter/material.dart';
import 'package:hb_shared/hb_shared.dart';
import 'package:provider/provider.dart';

import '../state/merchant_state.dart';
import '../state/orders_state.dart';
import 'analytics_tab.dart';
import 'menu_tab.dart';
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
    );
  }
}

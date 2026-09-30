import 'package:flutter/foundation.dart';
import 'package:hb_shared/hb_shared.dart';

/// Where the merchant sits in the onboarding funnel. The app shows a
/// different root screen for each stage.
enum MerchantStage {
  loading,
  loggedOut,
  needsApplication,
  awaitingApproval,
  ready,
}

class MerchantState extends ChangeNotifier {
  final ApiClient api;

  MerchantState(this.api);

  MerchantStage stage = MerchantStage.loading;
  AppUser? user;
  Vendor? vendor;

  Future<void> bootstrap() async {
    await api.authStorage.load();
    if (!api.authStorage.isLoggedIn) {
      _set(MerchantStage.loggedOut);
      return;
    }
    try {
      user = await api.me();
      await refreshVendor();
    } catch (_) {
      await api.authStorage.clear();
      _set(MerchantStage.loggedOut);
    }
  }

  Future<void> onAuthenticated(AuthResult result) async {
    user = result.user;
    await refreshVendor();
  }

  /// Re-reads the vendor profile and recomputes which stage to show. A vendor
  /// row only exists once they've applied, and only counts as live once an
  /// admin approves it.
  Future<void> refreshVendor() async {
    if (user?.role != UserRole.vendor) {
      vendor = null;
      _set(MerchantStage.needsApplication);
      return;
    }
    try {
      vendor = await api.myVendor();
      _set(vendor!.isApproved ? MerchantStage.ready : MerchantStage.awaitingApproval);
    } on ApiException catch (e) {
      if (e.statusCode == 404) {
        vendor = null;
        _set(MerchantStage.needsApplication);
      } else {
        rethrow;
      }
    }
  }

  Future<void> apply({required String stallName, String? description}) async {
    vendor = await api.applyAsVendor(stallName: stallName, description: description);
    user = await api.me();
    _set(vendor!.isApproved ? MerchantStage.ready : MerchantStage.awaitingApproval);
  }

  /// True while an open/closed change is in flight, so the switch can show
  /// it is working rather than looking dead on slow campus wifi.
  bool savingOpenState = false;

  /// Opens or closes the stall.
  ///
  /// Moves the switch immediately and puts it back if the server refuses.
  /// Waiting for the round trip made the control feel broken, but the bigger
  /// problem was the old version letting a failure escape as an unhandled
  /// exception: the switch snapped back with no explanation, so a vendor could
  /// believe they had closed when they were still taking orders.
  ///
  /// Rethrows so the screen can say what went wrong.
  Future<void> setOpen(bool isOpen) async {
    final previous = vendor;
    if (previous == null) return;

    vendor = previous.copyWith(isOpen: isOpen);
    savingOpenState = true;
    notifyListeners();

    try {
      vendor = await api.updateMyVendor(isOpen: isOpen);
    } catch (_) {
      vendor = previous;
      rethrow;
    } finally {
      savingOpenState = false;
      notifyListeners();
    }
  }

  Future<void> updateProfile({String? stallName, String? description, String? coverImageUrl}) async {
    vendor = await api.updateMyVendor(
      stallName: stallName,
      description: description,
      coverImageUrl: coverImageUrl,
    );
    notifyListeners();
  }

  Future<void> logout() async {
    await api.logout();
    user = null;
    vendor = null;
    _set(MerchantStage.loggedOut);
  }

  void _set(MerchantStage next) {
    stage = next;
    notifyListeners();
  }
}

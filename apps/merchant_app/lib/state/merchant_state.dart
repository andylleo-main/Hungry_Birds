import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:hb_shared/hb_shared.dart';

import '../services/push.dart';

/// Where the merchant sits in the onboarding funnel. The app shows a
/// different root screen for each stage.
enum MerchantStage {
  loading,
  loggedOut,
  /// Signed in by email code, but with no password set yet.
  ///
  /// Sits before needsApplication deliberately: a brand-new stall sets a
  /// password first, so that the next morning they can sign in without waiting
  /// on an inbox. There is no skip - an optional prompt most people dismiss
  /// leaves the feature doing nothing for the merchants it was built for.
  needsPassword,
  needsApplication,
  awaitingApproval,
  ready,
}

class MerchantState extends ChangeNotifier {
  final ApiClient api;

  /// New-order notifications. Owned here because its lifetime is the signed-in
  /// stall's: it starts once there is an approved vendor to attach a token to,
  /// and stops before sign-out while the token still works.
  final PushService push;

  MerchantState(this.api) : push = PushService(api);

  MerchantStage stage = MerchantStage.loading;
  AppUser? user;
  Vendor? vendor;

  /// Whether this account has a password. Null until asked.
  bool? hasPassword;

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

  /// Signs in with an email and password, skipping the code entirely.
  Future<void> loginWithPassword(String email, String password) async {
    final result = await api.vendorLogin(email.trim(), password);
    user = result.user;
    // Reaching here means they have one, so there is nothing to ask and no
    // round trip worth spending to confirm it.
    hasPassword = true;
    await refreshVendor();
  }

  /// Sets or replaces the password, and adopts the session that replaces this one.
  ///
  /// The server revokes every session on a change, including the one that made
  /// the request; ApiClient saves the replacement tokens, so this just has to
  /// move the stage on.
  Future<void> setPassword(String password) async {
    final result = await api.setVendorPassword(password);
    user = result.user;
    hasPassword = true;
    await refreshVendor();
  }

  /// Re-reads the vendor profile and recomputes which stage to show.
  ///
  /// The account is already a vendor by the time it gets here - the role is set
  /// when it is created, on the vendor login route. What may not exist yet is
  /// the stall itself, which is what the 404 below means.
  Future<void> refreshVendor() async {
    if (user?.role != UserRole.vendor) {
      vendor = null;
      _set(MerchantStage.needsApplication);
      return;
    }

    // Asked once per sign-in rather than on every refresh. A stall that has a
    // password cannot lose it, and one that does not is about to be asked for
    // one, so there is no state here worth re-reading on a vendor refresh.
    if (hasPassword == null) {
      try {
        hasPassword = await api.vendorHasPassword();
      } catch (_) {
        // An older server, or a blip. Assume they have one rather than block
        // the stall behind a screen it cannot get past - the password is a
        // convenience, and the queue is the job.
        hasPassword = true;
      }
    }
    if (hasPassword == false) {
      _set(MerchantStage.needsPassword);
      return;
    }
    try {
      vendor = await api.myVendor();
      _set(vendor!.isApproved ? MerchantStage.ready : MerchantStage.awaitingApproval);
      if (vendor!.isApproved) {
        // Deliberately not awaited. Push is a convenience, and asking Firebase
        // for a token can take a moment on a cold start - the order queue
        // should not wait on it. Failures are swallowed inside start().
        unawaited(push.start());
      }
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
    // No need to re-read the user afterwards any more: applying used to be what
    // promoted the account to a vendor, and now it only attaches a stall to an
    // account that already is one.
    vendor = await api.applyAsVendor(stallName: stallName, description: description);
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

  /// Forgets the cached answer, so the next sign-in asks again.
  void forgetPasswordState() => hasPassword = null;

  Future<void> logout() async {
    // Before api.logout(), while the access token still works - unregistering
    // needs an authenticated call, and a phone handed to somebody else must stop
    // buzzing for this stall's orders.
    await push.stop();
    await api.logout();
    user = null;
    vendor = null;
    hasPassword = null;
    _set(MerchantStage.loggedOut);
  }

  void _set(MerchantStage next) {
    stage = next;
    notifyListeners();
  }
}

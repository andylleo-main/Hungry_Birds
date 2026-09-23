/// Client-side mirror of the backend's phone rules, for instant form feedback
/// only. The backend re-validates and normalizes on every write, so it stays
/// the source of truth - this just avoids a round-trip to say "that's not a
/// valid number".
library;

/// Returns an error message for an invalid Indian mobile number, or null if
/// it's acceptable. Mirrors `normalize_phone` in the backend.
String? validateIndianMobile(String? input) {
  final digits = (input ?? '').replaceAll(RegExp(r'\D'), '');

  var local = digits;
  if (local.length == 12 && local.startsWith('91')) {
    local = local.substring(2);
  } else if (local.length == 11 && local.startsWith('0')) {
    local = local.substring(1);
  }

  if (local.isEmpty) return 'Enter your phone number';
  if (local.length != 10 || !RegExp(r'^[6-9]').hasMatch(local)) {
    return 'Enter a valid 10-digit Indian mobile number';
  }
  return null;
}

/// Renders a stored E.164 number for display: +919876543210 -> 98765 43210.
String formatPhoneForDisplay(String phone) {
  final digits = phone.replaceAll(RegExp(r'\D'), '');
  final local = digits.length == 12 && digits.startsWith('91') ? digits.substring(2) : digits;
  if (local.length != 10) return phone;
  return '${local.substring(0, 5)} ${local.substring(5)}';
}

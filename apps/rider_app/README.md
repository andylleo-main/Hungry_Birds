# rider_app

The Hungry Birds **rider** app: the deliveries a stall has given you, who to
call, and two buttons.

Riders sign in with a login id and a password their stall generates for them in
the merchant app — not with an email code, because riders have no email in this
system and no inbox to check mid-shift. If a rider forgets their password the
stall regenerates it, which also signs their old device out.

Android only. Build and install it exactly like the merchant app — see
["Building installable APKs"](../../README.md#building-installable-apks) in the
repository README, substituting `rider_app` for `merchant_app`.

The whole app is deliberately small: one list, and each card shows the
destination first, because that is the one thing a rider reads while walking.

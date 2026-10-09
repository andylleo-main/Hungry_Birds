# Checkout & Cashback Rules Update — Hungry Birds

Tightens the two-step checkout so contact details are collected up front and the payment choice comes first. Every order gets one clear promotion: earn cashback, spend cashback, or use a coupon whose value comes back as cashback.

## Who it's for
- Students ordering on the web app, who need to see exactly what they'll pay and what they'll get back.
- The admin, whose payout figures have to stay correct under the new coupon rules.

## Core features and experience

**Checkout page 1 (Review)**
- The student can't continue until both name and phone number are filled in and valid. The button stays disabled and says what's missing, e.g. "Add your name and phone number".
- Name field placeholder: `ADD YOUR NAME`. Phone field placeholder: `**********` (10 stars).

**Checkout page 2 (Payment)**
- "How you'll pay" moves to the top of the page.
- Below it, one promotion choice per order:
  1. **Earn cashback** (always selected by default): pay full price and get the usual 20% back (60% at the Gourmet stall, up to its cap) when the order is completed.
  2. **Use my cashback**: spend wallet balance now. This order then earns no cashback.
  3. **Apply a coupon**: the student pays full price, and once the order is completed the coupon's value goes into their cashback wallet as credit. The order doesn't earn normal cashback on top, and a coupon can't be combined with spending cashback.
- **Pay on delivery** says plainly, on the page: "No offers or cashback on pay-on-delivery orders". The promotion choices are locked while it's selected. If a coupon or cashback was already chosen, it's removed, with a short note explaining why.
- **Green line under the total due**, for example:
  - "You'll earn ₹40 cashback on this order"
  - "You're saving ₹40 with your cashback"
  - "You'll get ₹50 cashback from coupon FEST50 once this order is completed"
  - For pay on delivery, the green line is replaced by the neutral note above.

**Server-side rules** (the server enforces these, not just the screen)
- Pay-on-delivery orders refuse coupons and cashback spending.
- A coupon no longer lowers what the student pays. Its value becomes a cashback credit on completion, which then works like any other cashback:
  - It goes into the wallet that matches the stall (Campus or Gourmet).
  - It has the usual expiry.
  - It's spendable under the usual limits.
- If the order is rejected or cancelled, no coupon credit is given, and the coupon use is handed back as it is today.
- Coupon conditions (minimum order value, which stalls, who can use it, one per customer) still apply when the coupon is applied.
- Spending cashback still means the order earns nothing. Cashback and coupons still can't be used together.

**Other copy updates**
- Login page email placeholder: `yourrollnumber@bitmesra.ac.in`.
- The Offers & cashback page explains the new coupon rule ("Coupons come back to you as cashback") and the pay-on-delivery exclusion. Coupon credits appear in cashback history as "From coupon CODE".

## User flow
1. Student fills the cart and opens checkout page 1, chooses dine-in or delivery, and enters name and phone. Without both, they can't go further.
2. On page 2, they choose how to pay (online or on delivery).
3. If paying online, they keep "Earn cashback" or switch to "Use my cashback" or a coupon. The green line updates straight away.
4. They pay. When the order is completed, any earned cashback or coupon credit lands in their wallet and shows up on the Offers page.

## UI/UX feel
- Same red-and-white design as the current redesign.
- The promotion choice is a group of three clear option cards. Only one can be picked.
- Green is used only for money coming back or being saved. The pay-on-delivery note uses neutral styling.

## Implementation phases
- **Phase 1 (MVP, built now):** everything above. That covers the page 1 checks and placeholders, page 2 reorder with the earn/use/coupon choice, the pay-on-delivery lock and note, the green line, coupon-as-cashback on the server, pay-on-delivery refusing promotions, the login placeholder and the Offers page wording.
- **Phase 2:** the order-tracking page shows "₹X cashback on its way" until the order is completed, and the profile page uses the same name and phone placeholders.
- **Phase 3:** an admin report of cashback given out (earned vs from coupons) per stall and per week, next to Weekly payouts.

## Assumptions
- A coupon's credit equals the discount it would have given on that cart: percent of the cart (up to the coupon's own maximum) or the flat amount. The normal cashback cap doesn't apply to it.
- Coupon credit lands only when the order is completed, the same moment normal cashback does.
- Orders placed before this change keep their existing coupon discounts. Their figures in Finances and Weekly payouts don't change.
- After this change, new coupon orders show no "Discounts we fund" in Weekly payouts. The cost shows up later, when the student spends the credit as cashback.
- Automatic coupons (no code to type) follow the same rule: they become cashback credit and count as the order's one promotion.
- If a student switches to pay on delivery, any coupon or cashback they'd chosen is removed rather than blocking the switch.
- The merchant and rider apps are not changed.

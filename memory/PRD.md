# Hungry Birds — PRD

## Original problem statement
"can you see my github repo" → then: redesign the whole frontend of the web app, keep the theme red and white; every webpage opens from the top; redesign the admin panel; let the admin view orders from every stall; each stall gets a dedicated finances option in the admin panel (dine-in cash (always 0) + prepaid, delivery cash (COD paid in cash) + prepaid (COD paid by UPI QR counts as prepaid)), just like the merchant app; don't change the rider or merchant apps; rephrase the lines in the web app; improve the offers & cashback page.

## Architecture
- backend/: FastAPI + SQLAlchemy async + Postgres + Redis (Alembic migrations). Deployed on Railway.
- apps/web/: React 19 + Vite + Tailwind 3 customer app with embedded admin panel.
- apps/merchant_app, apps/rider_app: Flutter (untouched).
- Preview-only shims: /app/backend/server.py (uvicorn entry), /app/frontend (Vite wrapper on :3000), /root/preview_seed.py (demo data). Local Postgres + Redis installed in the pod.

## Implemented (2026-06)
- Fixed 13 ruff F821 errors in backend models (TYPE_CHECKING imports).
- New admin endpoints: GET /api/admin/orders (filters vendor_id, status, days, limit; adds stall_name, no delivery_code), GET /api/admin/vendors/{id}/finances (reuses merchant build_vendor_analytics).
- Web redesign: new red/white tokens, Bricolage Grotesque + DM Sans, new header/footer/stall cards/discover hero with marquee, login, orders, stall page, offers page (wallet cards, how-it-works, coupon tickets with copy, history filters).
- Scroll-to-top on every route change + admin tab change.
- Admin panel: sidebar layout with Overview, All orders (filters, search, detail sheet), Finances per stall (money grid prepaid/cash × dine-in/delivery, outstanding, refunded, best sellers, day bars), Stalls (approve/suspend, jump to finances/orders), Price changes, Coupons.
- Copy rephrased across pages.
- Tested: iteration_1 — 100% backend & frontend.

## Backlog
- P1: CSV export of a stall's finances / orders for settlement.
- P1: Pagination on admin orders beyond 500.
- P2: Live (websocket) refresh on admin orders.
- P2: Restyle remaining inner components of checkout/tracking more deeply.

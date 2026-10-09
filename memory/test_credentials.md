# Test credentials (preview environment only)

- Admin (password login, "Are you an admin? Sign in with a password" link on login page)
  - email: admin@bitmesra.ac.in
  - password: HungryAdmin@2026
- Student: student@bitmesra.ac.in, sign in by OTP. Backend runs with ENVIRONMENT=development + OTP_DEBUG_ECHO=true,
  so the 6-digit code is shown on screen ("Dev mode: your code is ...") and in the /api/auth/otp/request response (debug_code).
- PAYMENTS_MODE=mock: online payments are confirmed without charging (MOCKED gateway).

Preview data seeded by /root/preview_seed.py: stalls Down South Cafe, Gourmet Kitchen, Chai Point Hostel 4 (closed), pending stall Momo Junction, 54 orders over the last 6 days.

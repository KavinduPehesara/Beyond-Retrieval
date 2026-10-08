# Google login verification

Implemented Google OpenID Connect, PKCE, nonce and browser-bound OAuth state validation, signature/audience/issuer validation through google-auth, verified email checks, one-use browser-bound login tickets, hashed 24-hour revocable application sessions, account-owned live reviews, and a saved-review dropdown without visible IDs.

Full suite: 465 passed. After final cache-control adjustment and four extra tests: targeted authentication/UI suite 9 passed. Covers mocked Google callback success, CSRF state, wrong nonce, replay, expiry, logout, stable subject identity, unverified email rejection, cross-account read/write/map denial, guest setup message and private review dropdown labels.

Browser checked the live Run a Review page: Sign in popover displays setup pending, review-ID input removed. Screenshot: google-sign-in.png.

Real Google sign-in was not exercised: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are absent. Follow docs/google-sign-in.md, configure .env, restart API, and complete the Google consent flow manually to verify the real provider round trip. Existing anonymous sessions are preserved but not automatically assigned to accounts.

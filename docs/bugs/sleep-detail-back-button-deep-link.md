# Sleep & Recovery detail page: back button lands on `about:blank` via deep link

GitHub issue: [#47](https://github.com/YueyueGuo/Health-tracker/issues/47)

## Symptom

Opening `/sleep` directly (fresh tab, PWA shortcut, shared link, notification
tap) and clicking the back chevron in the sticky header of
`SleepRecoveryDetailsCard` lands the user on `about:blank` instead of falling
back to the dashboard.

The dashboard → detail → back happy path still works.

## Repro

1. Open a brand-new tab and navigate to `http://<host>/sleep`.
2. Click the back chevron in the sticky header of the detail card.
3. Browser shows `about:blank`.

Verified via Playwright deep-link testing during `/verify` of PR #43:
`window.history.length` reports `2` on a true deep-link visit, defeating
the existing guard.

## Root cause

`frontend/src/components/sleep/SleepRecoveryDetailsCard.tsx:141-145`:

```ts
if (typeof window !== "undefined" && window.history.length <= 1) {
  navigate("/");
} else {
  navigate(-1);
}
```

`window.history.length` is the count of entries in the entire session
history, **including the initial `about:blank` entry** that exists for a
freshly opened tab. So on a deep-link visit `window.history.length === 2`,
the `<= 1` guard fails, and `navigate(-1)` walks the user back to that
blank entry. The intended dashboard fallback never fires.

The `<= 1` heuristic is also fragile for other reasons (extensions
inserting entries, PWA install flows), but the blank-tab case is the
one that ships broken to real users.

## Recommended fix

Replace the `history.length` check with a router-aware signal:
capture `useNavigationType()` from `react-router-dom` **on first mount**
and treat `"POP"` as "we entered via a deep link / reload, navigate(-1)
is unsafe — go home instead."

- `"POP"` at mount → user landed here directly (deep link, refresh,
  notification tap). Use `navigate("/", { replace: true })` so the back
  button after pressing it doesn't reverse the redirect.
- `"PUSH"` / `"REPLACE"` at mount → user got here from inside the SPA
  (dashboard → detail). `navigate(-1)` is safe.

Capture the value via `useRef` so subsequent in-component re-renders
don't change the entry classification.

## Owner

`frontend-engineer` — change is confined to a single React component +
its test file. No backend, no schema, no API contract.

## Regression test

In `frontend/src/components/sleep/SleepRecoveryDetailsCard.test.tsx`,
add two new cases that mock `useNavigate`:

1. **Deep-link entry** — render the card under
   `<MemoryRouter initialEntries={["/sleep"]}>`. Click the back chevron.
   Assert the mock was called with `"/"` (with `{ replace: true }`),
   never with `-1`.
2. **In-app entry** — render the card inside `<MemoryRouter initialEntries={["/", "/sleep"]} initialIndex={1}>`
   so the navigation type at the `/sleep` entry mimics a `PUSH`
   navigation. Click the back chevron. Assert the mock was called with
   `-1`.

The first test fails on `main` (the existing `history.length` guard
returns `false` for `MemoryRouter`, so `navigate(-1)` runs) and passes
after the fix.

## Out of scope

The investigator (issue author) flagged that the `history.length <= 1`
heuristic is also used nowhere else in the repo, so no other component
needs the same fix. If similar deep-link back buttons get added later,
extract the navigation-type capture into a small `useEnteredViaDeepLink`
hook — defer until there's a second caller.

## References

- PR #43 (introduced the page + insufficient guard)
- `docs/plans/sleep-recovery-detail-page.md` (Risks section flagged this
  scenario but accepted the simple guard)

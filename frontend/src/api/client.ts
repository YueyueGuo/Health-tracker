// Compatibility barrel for existing imports. New code should import from the
// domain modules directly, e.g. `api/activities` or `api/dashboard`.
export * from "./activities";
export * from "./chat";
export * from "./dashboard";
export * from "./recovery";
export * from "./summary";
export * from "./sync";
export { fetchSleepSessions, fetchSleepTrends } from "./sleep";

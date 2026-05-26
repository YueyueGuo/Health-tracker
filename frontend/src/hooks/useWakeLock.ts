import { useEffect } from "react";

type WakeLockSentinelLike = {
  released: boolean;
  release: () => Promise<void>;
  addEventListener: (type: "release", listener: () => void) => void;
  removeEventListener: (type: "release", listener: () => void) => void;
};

type WakeLockNavigator = Navigator & {
  wakeLock: {
    request: (type: "screen") => Promise<WakeLockSentinelLike>;
  };
};

function hasWakeLock(nav: Navigator): nav is WakeLockNavigator {
  return "wakeLock" in nav;
}

/**
 * Best-effort Screen Wake Lock. While `active` is true, prevents the device
 * screen from dimming/sleeping. Re-acquires the lock when the page returns
 * to visible (browsers auto-release on hide). All failures are swallowed —
 * Wake Lock is HTTPS-only and unavailable on some browsers.
 */
export function useWakeLock(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    if (typeof navigator === "undefined" || !hasWakeLock(navigator)) return;

    const nav = navigator;
    let sentinel: WakeLockSentinelLike | null = null;
    let cancelled = false;

    const acquire = async () => {
      try {
        const s = await nav.wakeLock.request("screen");
        if (cancelled) {
          try {
            await s.release();
          } catch {
            // ignore
          }
          return;
        }
        sentinel = s;
      } catch {
        // ignore
      }
    };

    const release = async () => {
      const s = sentinel;
      sentinel = null;
      if (!s || s.released) return;
      try {
        await s.release();
      } catch {
        // ignore
      }
    };

    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        void acquire();
      } else {
        void release();
      }
    };

    void acquire();
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisibility);
      void release();
    };
  }, [active]);
}

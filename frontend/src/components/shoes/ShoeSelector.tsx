import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { ActivitySource } from "../../api/activities";
import { patchActivityShoe } from "../../api/activities";
import {
  createShoe,
  type Shoe,
  type ShoeCreate,
} from "../../api/shoes";
import { useShoesList, invalidateShoes } from "../../hooks/useShoes";
import { getErrorMessage } from "../../utils/errors";
import ShoeForm from "./ShoeForm";

/** Sentinel <option> value for the "add another pair" action. Chosen so
 *  it can never collide with a real shoe id (which are positive numbers). */
const ADD_OPTION_VALUE = "__add__";

interface Props {
  activityId: number;
  source: ActivitySource | null;
  currentShoeId: number | null;
  /** Called after a successful tag/untag so the parent reloads. */
  onChange: () => void;
}

/**
 * Activity-detail shoe selector. Three render states:
 *
 *  1. Loading.
 *  2. Empty-state ("Add a shoe" button → expands an inline ShoeForm
 *     that chains createShoe + patchActivityShoe in one flow).
 *  3. Steady-state dropdown of active shoes, plus the currently-tagged
 *     retired shoe (read-only) if applicable. Selecting "— None —"
 *     untags.
 */
export default function ShoeSelector({
  activityId,
  source,
  currentShoeId,
  onChange,
}: Props) {
  const queryClient = useQueryClient();
  const { data: shoes, loading, error: loadError } = useShoesList("active");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [partialFailure, setPartialFailure] = useState<string | null>(null);
  // Optimistic state: holds the user's just-picked shoe id so the
  // controlled <select> reflects their choice during the PATCH +
  // refetch latency window. `undefined` means "no pending pick, fall
  // back to the parent prop". Any other value (including `null` for
  // "— None —") wins over `currentShoeId` until the parent catches up.
  const [pendingShoeId, setPendingShoeId] = useState<
    number | null | undefined
  >(undefined);

  const activeShoes: Shoe[] = shoes ?? [];

  const effectiveShoeId =
    pendingShoeId !== undefined ? pendingShoeId : currentShoeId;

  // Once the parent's currentShoeId catches up to the optimistic pick
  // (i.e. the refetch landed), clear the pending state so the prop
  // is the source of truth again. If the server silently rejects the
  // change and the prop diverges, this also lets the real value win.
  useEffect(() => {
    if (pendingShoeId !== undefined && currentShoeId === pendingShoeId) {
      setPendingShoeId(undefined);
    }
  }, [currentShoeId, pendingShoeId]);

  // If the activity is currently tagged to a retired (or otherwise
  // not-in-active-list) shoe, surface it as a disabled-styled option
  // so the user sees the truth without being able to re-select it.
  const tagToRetired =
    effectiveShoeId != null &&
    !activeShoes.some((s) => s.id === effectiveShoeId);

  const handleChange = async (next: number | null) => {
    // Apply the optimistic pick *synchronously* before any await so
    // React's next render uses it as the <select value> rather than
    // snapping back to the stale (lagging) currentShoeId prop.
    setPendingShoeId(next);
    setBusy(true);
    setActionError(null);
    setPartialFailure(null);
    try {
      await patchActivityShoe(activityId, next, source);
      await invalidateShoes(queryClient);
      onChange();
    } catch (e) {
      // Roll back the visual selection so the user sees the failure.
      setPendingShoeId(undefined);
      setActionError(getErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const handleInlineCreate = async (payload: ShoeCreate) => {
    setPartialFailure(null);
    setActionError(null);
    let created: Shoe;
    try {
      created = await createShoe(payload);
    } catch (e) {
      // Rethrow so ShoeForm displays the inline error; nothing was
      // tagged, the form stays open.
      throw e;
    }
    try {
      await patchActivityShoe(activityId, created.id, source);
      await invalidateShoes(queryClient);
      setCreating(false);
      onChange();
    } catch (e) {
      // Shoe exists (the list view will show it) but the tag failed.
      // Surface a clear message and refresh the selector so the user
      // can retry from the dropdown.
      await invalidateShoes(queryClient);
      setCreating(false);
      onChange();
      setPartialFailure(
        `Created ${created.name} but failed to tag it on this run — ` +
          `try the dropdown above. (${getErrorMessage(e)})`,
      );
    }
  };

  return (
    <div className="card" style={{ padding: 20 }}>
      <h3 style={{ marginTop: 0 }}>Shoes</h3>
      <p style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 4 }}>
        Tag the pair you ran in so their mileage updates automatically.
      </p>

      {loading && (
        <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading…</div>
      )}

      {loadError && <div className="error">{loadError}</div>}

      {!loading && !loadError && (
        <>
          {/* Empty state — no active shoes yet. */}
          {activeShoes.length === 0 && !tagToRetired && !creating && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
                You don&apos;t have any active shoes yet.
              </div>
              <button
                type="button"
                className="btn"
                onClick={() => setCreating(true)}
                disabled={busy}
                style={{ alignSelf: "flex-start" }}
              >
                + Add a shoe
              </button>
            </div>
          )}

          {/* Inline create flow (chains create + tag). */}
          {creating && (
            <div style={{ marginTop: 8 }}>
              <ShoeForm
                externalSubmit
                onSubmitPayload={handleInlineCreate}
                submitLabel="Save & tag"
                onCancel={() => setCreating(false)}
              />
            </div>
          )}

          {/* Steady-state dropdown. */}
          {!creating && (activeShoes.length > 0 || tagToRetired) && (
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <select
                value={effectiveShoeId ?? ""}
                disabled={busy}
                onChange={(e) => {
                  const val = e.target.value;
                  // "Add another pair" is an action, not a selectable
                  // shoe — open the inline create flow instead of
                  // tagging. The <select> never holds this value.
                  if (val === ADD_OPTION_VALUE) {
                    setCreating(true);
                    return;
                  }
                  handleChange(val === "" ? null : Number(val));
                }}
                style={{ flex: 1, maxWidth: 360 }}
                aria-label="Tag a shoe"
              >
                <option value="">— None —</option>
                {activeShoes.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
                {tagToRetired && (
                  // Render the retired tag as a disabled-styled current
                  // selection — the user can untag (pick None) or pick
                  // a different active shoe, but can't reselect it.
                  <option value={effectiveShoeId ?? ""} disabled>
                    (retired) #{effectiveShoeId}
                  </option>
                )}
                {/* Always the last option, regardless of how many pairs
                    already exist — lets the user add another pair without
                    leaving the workout. */}
                <option value={ADD_OPTION_VALUE}>+ Add another pair…</option>
              </select>
            </div>
          )}

          {actionError && (
            <div className="error" style={{ marginTop: 8 }}>
              {actionError}
            </div>
          )}
          {partialFailure && (
            <div className="error" style={{ marginTop: 8 }}>
              {partialFailure}
            </div>
          )}
        </>
      )}
    </div>
  );
}

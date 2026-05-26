import { useMemo, useState } from "react";
import {
  createShoe,
  patchShoe,
  type Shoe,
  type ShoeCreate,
  type ShoePatch,
  type ShoeType,
} from "../../api/shoes";
import { useUnits } from "../../hooks/useUnits";
import {
  metersToInput,
  parseDistanceInput,
  unitLabel,
} from "../../lib/shoeFormatting";
import { getErrorMessage } from "../../utils/errors";

const SHOE_TYPES: ShoeType[] = [
  "everyday",
  "workout",
  "race",
  "long_run",
  "trail",
];

const SHOE_TYPE_LABELS: Record<ShoeType, string> = {
  everyday: "Everyday",
  workout: "Workout",
  race: "Race",
  long_run: "Long run",
  trail: "Trail",
};

export interface ShoeFormProps {
  /** Editing an existing shoe? Pass it here to prefill + switch to PATCH. */
  shoe?: Shoe | null;
  /** Submit button label override. Defaults to "Save" / "Save changes". */
  submitLabel?: string;
  /** Show a Cancel button alongside Save. */
  onCancel?: () => void;
  /** Called with the created/updated shoe after a successful request.
   *  Optional when `externalSubmit` is on (the parent handles the
   *  result itself in that mode). */
  onSaved?: (shoe: Shoe) => void | Promise<void>;
  /**
   * If true, skip the network call and just pass the assembled payload
   * back to the parent via `onSubmitPayload`. Used by `ShoeSelector`'s
   * inline-create flow so it can chain `createShoe -> patchActivityShoe`
   * itself.
   */
  externalSubmit?: boolean;
  onSubmitPayload?: (payload: ShoeCreate) => Promise<void>;
  /** Initial autofocus on the name input. Default: true. */
  autoFocus?: boolean;
}

const DEFAULT_TYPE: ShoeType = "everyday";

/**
 * Reusable form body for creating or editing a shoe. Used standalone
 * by `ShoeFormModal` and inline by `ShoeSelector` (empty-state flow).
 *
 * Distances bind to `useUnits` — imperial users type miles, metric
 * users type kilometers. The backend always sees meters.
 */
export default function ShoeForm({
  shoe,
  submitLabel,
  onCancel,
  onSaved,
  externalSubmit,
  onSubmitPayload,
  autoFocus = true,
}: ShoeFormProps) {
  const { units } = useUnits();
  const editing = shoe != null;

  const [name, setName] = useState(shoe?.name ?? "");
  const [brand, setBrand] = useState(shoe?.brand ?? "");
  const [model, setModel] = useState(shoe?.model ?? "");
  const [shoeType, setShoeType] = useState<ShoeType>(
    shoe?.shoe_type ?? DEFAULT_TYPE,
  );
  const [lifespan, setLifespan] = useState(
    metersToInput(shoe?.total_usable_distance_m ?? null, units),
  );
  const [purchasedOn, setPurchasedOn] = useState(shoe?.purchased_on ?? "");
  const [notes, setNotes] = useState(shoe?.notes ?? "");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmedName = name.trim();
  const parsedLifespan = useMemo(
    () => parseDistanceInput(lifespan, units),
    [lifespan, units],
  );
  const lifespanInvalid = parsedLifespan === undefined && lifespan.trim() !== "";
  const canSubmit = trimmedName.length > 0 && !lifespanInvalid && !busy;

  const buildPayload = (): ShoeCreate => ({
    name: trimmedName,
    brand: brand.trim() || null,
    model: model.trim() || null,
    shoe_type: shoeType,
    // parseDistanceInput returns null for empty (clear target) and a
    // number for valid input. `undefined` (invalid) is gated above.
    total_usable_distance_m: parsedLifespan ?? null,
    purchased_on: purchasedOn || null,
    notes: notes.trim() || null,
  });

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const payload = buildPayload();
      if (externalSubmit) {
        // Parent owns the network calls (e.g. selector's inline create
        // chains POST -> PATCH activity in one flow).
        await onSubmitPayload?.(payload);
        return;
      }
      let result: Shoe;
      if (editing && shoe) {
        // PATCH: only fields the user touched? In practice the form
        // already prefills from the existing shoe so sending the full
        // payload is safe (PATCH with full body is idempotent).
        const patch: ShoePatch = {
          name: payload.name,
          brand: payload.brand,
          model: payload.model,
          shoe_type: payload.shoe_type,
          total_usable_distance_m: payload.total_usable_distance_m,
          purchased_on: payload.purchased_on,
          notes: payload.notes,
        };
        result = await patchShoe(shoe.id, patch);
      } else {
        result = await createShoe(payload);
      }
      await onSaved?.(result);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const unit = unitLabel(units);

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <label style={fieldLabel}>
        Name
        <input
          autoFocus={autoFocus}
          type="text"
          placeholder="e.g. Vaporfly 3 — blue"
          value={name}
          maxLength={120}
          onChange={(e) => setName(e.target.value)}
          style={inputStyle}
        />
      </label>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <label style={fieldLabel}>
          Brand
          <input
            type="text"
            placeholder="Nike"
            value={brand}
            maxLength={64}
            onChange={(e) => setBrand(e.target.value)}
            style={inputStyle}
          />
        </label>
        <label style={fieldLabel}>
          Model
          <input
            type="text"
            placeholder="Vaporfly 3"
            value={model}
            maxLength={120}
            onChange={(e) => setModel(e.target.value)}
            style={inputStyle}
          />
        </label>
      </div>

      <label style={fieldLabel}>
        Type
        <select
          value={shoeType}
          onChange={(e) => setShoeType(e.target.value as ShoeType)}
          style={inputStyle}
        >
          {SHOE_TYPES.map((t) => (
            <option key={t} value={t}>
              {SHOE_TYPE_LABELS[t]}
            </option>
          ))}
        </select>
      </label>

      <label style={fieldLabel}>
        Lifespan target ({unit})
        <input
          type="number"
          inputMode="decimal"
          min="0"
          step="0.1"
          placeholder={
            units === "imperial" ? "typical: 300–500 mi" : "typical: 500–800 km"
          }
          value={lifespan}
          onChange={(e) => setLifespan(e.target.value)}
          style={inputStyle}
          aria-invalid={lifespanInvalid || undefined}
        />
        {lifespanInvalid && (
          <span style={{ color: "var(--red)", fontSize: 12 }}>
            Enter a positive number, or leave blank for no target.
          </span>
        )}
      </label>

      <label style={fieldLabel}>
        Purchased on
        <input
          type="date"
          value={purchasedOn}
          onChange={(e) => setPurchasedOn(e.target.value)}
          style={inputStyle}
        />
      </label>

      <label style={fieldLabel}>
        Notes
        <textarea
          rows={2}
          placeholder="Optional"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          style={{ ...inputStyle, fontFamily: "inherit" }}
        />
      </label>

      {error && <div className="error">{error}</div>}

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        {onCancel && (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </button>
        )}
        <button
          type="button"
          className="btn"
          onClick={submit}
          disabled={!canSubmit}
        >
          {busy
            ? "Saving…"
            : submitLabel ?? (editing ? "Save changes" : "Save")}
        </button>
      </div>
    </div>
  );
}

const fieldLabel: React.CSSProperties = {
  display: "grid",
  gap: 4,
  fontSize: 12,
  color: "var(--text-muted)",
};

const inputStyle: React.CSSProperties = {
  background: "var(--bg-card)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: "8px 12px",
  color: "var(--text)",
  fontSize: 14,
  outline: "none",
  width: "100%",
  boxSizing: "border-box",
};

# Strength HR Segmentation — Research Brief

## 1. Peak-anchored vs. valley-to-valley framing

**Recommendation: peak-anchored, with valley-clipping as a guard.** Anchor each detected segment at the HR peak, then expand a working-HR window `[peak − 22s, peak + 8s]`, clipped to the neighbouring valleys so we never overlap into the next set's rise or the previous set's recovery dip.

Evidence: Sport-physiology consensus is that HR rises monotonically during a set of 5–30 s, peaks at or just after the last rep, then falls during rest ([PT Direct — Heart's response to exercise](https://www.ptdirect.com/training-design/anatomy-and-physiology/acute-cardio-heart-responses-to-exercise)). The peak is the most robust landmark; valleys between sets vary wildly with rest length (90 s vs 3 min) and are confounded by mid-set water breaks. Peak-anchored windows give you the *working* HR you want to report; valley-to-valley framing also sweeps in 60–120 s of recovery and pulls the average down ([Cleveland Clinic — HRR fast phase](https://my.clevelandclinic.org/health/articles/23490-heart-rate-recovery): 30–50 bpm drop in 30 s for fit subjects). The valley landmarks are still useful as **clip boundaries** so a peak's window doesn't bleed into its neighbour.

The existing `_slice_hr_for_set` already implements a peak-trailing window of 45 s, which matches this recommendation directionally.

## 2. scipy availability + recommendation

**Recommendation: pure-Python peak detector. Do NOT add scipy.** Streams are ≤ ~3600 samples (1 Hz × 1 h) and the algorithm runs at request time only — Python is fast enough. Adding scipy roughly triples the Railway slug size (scipy + numpy wheels ≈ 60–80 MB) for a single function we can write in ~80 LOC.

Evidence: `pyproject.toml` lists no `scipy` or `numpy` and there are no transitive routes — no lockfile, no scientific deps in the tree. Sample sketch the backend engineer can implement directly:

```
1. smooth = rolling_mean(hr, w=15)            # O(n) with deque
2. cands = [i for i in 1..n-1 if smooth[i-1] < smooth[i] >= smooth[i+1]]
3. for each cand i:
     left  = max(smooth[j] minima walking left  from i until j hits boundary or smooth[j] > smooth[i])
     right = max(smooth[j] minima walking right ...)
     prominence[i] = smooth[i] - max(left_min, right_min)
4. keep candidates where prominence >= prom_floor
5. greedy non-max suppression: sort by prominence desc; drop any cand
    within min_distance of an already-kept higher-prominence peak
6. trim to top-N by prominence if len(kept) > target_count
```

The algorithm matches `scipy.signal.find_peaks(distance=..., prominence=...)` semantics ([find_peaks docs](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html)) on this size of input within ~5 ms in pure CPython.

## 3. Honest vs. forced segment count

**Recommendation: keep honest reporting; do NOT add a "force to N" fallback in v1.** Equal time-slicing when detection fails would produce confidently-wrong per-set HR (a peak might fall on a slice boundary, splitting one set into two halves). Worse for the owner than the "—" the spec already mandates.

Evidence: The spec (lines 116–119, 142–148) and plan (Step 2) both already mandate honest reporting plus the tooltip. There is no algorithm in the literature that reliably matches a target set count from HR alone — most published peak detectors operate without a target N. The only honest "fallback" worth shipping is the existing `_slice_hr_for_set` path keyed on `performed_at`, which the plan already retains for the case where every set has a timestamp AND segmentation returns `flat`/`error`. Reserve "force N" for v2 manual override (drag-segment-boundaries), which the spec explicitly defers.

If `detected_count == 0` and there is a curve but no peaks survived prominence, surface `status="flat"` and render summary-only; do not synthesise segments.

## 4. Apple Health `heartRateData` in practice

**Recommendation: build segmentation against Apple Health workouts too, but expect summary-only most of the time.** Apple's `heartRateData` is parsed end-to-end (`backend/services/apple_workout_detail.py:96`, `backend/services/hr_zones.py:229`, `backend/routers/activities.py:567`) and exposed through `_maybe_apple_streams`, but its presence depends entirely on the user's HAE shortcut configuration.

Evidence (from this repo):
- `backend/services/hr_zones.py:234–276` notes HAE emits two shapes — a scalar `{qty, units}` (useless for segmentation) or a series `[{date, qty, units, source}, ...]`. Only the series shape is useful.
- `backend/services/apple_workout_detail.py:50` says zones synthesis returns `None` "when no usable series", and `streams_cached = bool(samples)` (line 116) flips to `False` for the scalar / missing case.
- The Apple Health Auto Export ("HAE") shortcut only ships `heartRateData` arrays when the user enables the "Aggregate workout data" toggle (parser comment in `backend/services/apple_health_parser.py:103, 166`).

Verdict for v1: run the segmenter on Apple workouts when `_maybe_apple_streams` returns a non-empty `heartrate` array of length > 1; otherwise persist the link with `segmentation.status="no_curve"` and the UI degrades to summary-only HR (already covered by the spec edge case at lines 140–141 and `acceptance criteria` 105–107). Don't gate the whole Apple link UX on stream presence — the avg/max HR alone is still useful.

## 5. Default segmentation parameters

Hard-code these on day 1; add a `# TUNE` comment next to each so the follow-up tuning pass is obvious.

| Param | Value | Justification |
|---|---|---|
| `SMOOTH_WINDOW_SEC` | **15** | Compound sets last 10–30 s and HRR fast phase removes ~30 bpm in 30 s ([Cleveland Clinic](https://my.clevelandclinic.org/health/articles/23490-heart-rate-recovery)). A 15 s rolling mean kills sensor jitter and Polar/Apple wrist-strap dropouts while leaving the set-to-rest swing intact. Larger windows (30 s+) smear adjacent sets together when rest is short. |
| `MIN_PEAK_DISTANCE_SEC` | **`max(20, total_sec // (target_N * 3))`** | Working sets are ≥ 5 s and rest is ≥ 30–60 s in practice, so back-to-back peaks closer than 20 s are almost certainly noise. The `total/(3N)` term keeps the distance tight enough on a 30-set giant-set session that real peaks aren't merged. |
| `PROMINENCE_FLOOR_BPM` | **`max(8, 0.4 * (smoothed_max − smoothed_p20))`** | The draft `0.4 *(max − p20)` is good but can collapse to ~3 bpm on a low-intensity session and start picking up noise. Adding an absolute floor of 8 bpm guards against that — set-to-rest HR swings smaller than 8 bpm aren't separable from the sensor's intrinsic noise (Polar H10 ±2 bpm; Apple wrist sensor ±5 bpm). Published peak HR rises for slow-cadence resistance sets are 12–17 bpm above baseline, well above this floor ([Acute HR responses paper](https://www.clinmedjournals.org/articles/ijsem/international-journal-of-sports-and-exercise-medicine-ijsem-5-143.php?jid=ijsem)). |
| `FLAT_RANGE_BPM` | **15** | Matches the prominence reasoning: when the whole smoothed series spans < 15 bpm there is no per-set signal to extract. Confirm during tuning. Possible second-pass refinement: also flag flat if `iqr(smooth) < 6 bpm`. |
| `PEAK_WINDOW_SEC` | **`[peak − 22, peak + 8]`** | Captures the working plateau (last ~15–20 s of the set into the immediate ~5–8 s after rack/lockout where HR is still topped out before the recovery drop kicks in). Compound sets of 5–10 reps run 15–30 s; the asymmetry reflects that HR continues to drift up for ~5–8 s post-set before falling ([PT Direct](https://www.ptdirect.com/training-design/anatomy-and-physiology/acute-cardio-heart-responses-to-exercise)). Clip the window to the midpoints between this peak and its neighbours so we don't bleed into adjacent sets. |
| `DECIMATE_TARGET_POINTS` | **300** (unchanged) | Reuse `CURVE_TARGET_POINTS` from `backend/services/strength_hr.py:36`. |

Edge cases the backend engineer should encode:
- **Drop zero/None samples before smoothing** (HAE and Strava both emit 0 for dropouts; the existing `_decimate` already filters).
- **`smoothed_p20`** = the 20th percentile of the smoothed series (cheap: sort a copy). Using p20 instead of `min` makes the prominence floor robust to a single sensor-drop sample.
- **target_N = 0** (session has no logged sets) → short-circuit, return `status="ok"` with `segments=[]`.

---

## Citations

- [PT Direct — Acute cardiovascular responses to exercise](https://www.ptdirect.com/training-design/anatomy-and-physiology/acute-cardio-heart-responses-to-exercise) — set duration / peak / rest timing.
- [Acute Heart Rate Responses to Resistance Exercise at Different Cadences](https://www.clinmedjournals.org/articles/ijsem/international-journal-of-sports-and-exercise-medicine-ijsem-5-143.php?jid=ijsem) — peak HR magnitudes during sets.
- [Cleveland Clinic — Heart Rate Recovery](https://my.clevelandclinic.org/health/articles/23490-heart-rate-recovery) — 30 s fast-phase HRR magnitude.
- [Heart Rate Determined Rest Intervals In Hypertrophy-Type Resistance Training (ResearchGate)](https://www.researchgate.net/publication/307726380_Heart_Rate_Determined_Rest_Intervals_In_Hypertrophy-Type_Resistance_Training) — set-rest HR profile.
- [scipy.signal.find_peaks docs](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html) — semantics being mimicked by the pure-Python implementation.
- [AskPython — Peak Detection in Signals with scipy.signal.find_peaks](https://www.askpython.com/python-modules/scipy/scipy-signal/scipy-signal-find-peaks) — prominence + distance parameter behaviour.

---

## Relevant repo file paths

- `backend/services/strength_hr.py` — existing 45-s peak-trailing window logic to be replaced.
- `backend/routers/activities.py` lines 327–379 (Strava lazy fetch) and 533–613 (`_maybe_apple_streams`).
- `backend/services/apple_workout_detail.py` — Apple HR series → `streams_cached` flag.
- `backend/services/hr_zones.py` lines 229–278 — `derive_hr_samples_from_raw_payload` documents the two HAE shapes.
- `backend/services/apple_health_parser.py` lines 100–170 — comments on the HAE aggregate toggle.
- `pyproject.toml` — confirmed no `scipy`/`numpy`.
- `tests/test_services/test_strength_hr.py` — current test surface; will need rewrite per plan Step 6.

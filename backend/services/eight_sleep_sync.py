"""Eight Sleep sync logic, isolated from the main SyncEngine.

Kept separate so the Eight Sleep pipeline can evolve without touching the
Strava/Whoop sync code paths. ``SyncEngine.sync_eight_sleep`` delegates here.

Data model
----------
Eight Sleep's consumer API returns two complementary payloads per night:

* A **trends** row (``GET /v1/users/{id}/trends``) with aggregated nightly
  metrics (scores, duration, average HR/HRV/resp, bed temp).
* One or more **intervals** (``GET /v1/users/{id}/intervals``) with the
  per-minute stages timeline, timeseries (HR, HRV, respiratory rate, toss
  & turn), and additional metadata.

We merge these on the night's date so a single ``SleepSession`` row holds
everything we care about, with the union of both raw payloads preserved in
``raw_data``.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.clients.eight_sleep import EightSleepClient
from backend.config import settings
from backend.models import SleepSession, SyncLog

logger = logging.getLogger(__name__)


async def sync_eight_sleep(
    db: AsyncSession,
    client: EightSleepClient,
    *,
    days: int = 30,
    full_history: bool = False,
) -> int:
    """Pull Eight Sleep data into ``sleep_sessions``.

    Args:
        db: open async DB session (caller commits only implicitly — this
            function commits its own transactions).
        client: an initialized ``EightSleepClient``. Caller owns its lifetime.
        days: window to pull when ``full_history=False``.
        full_history: when True, walk back in 90-day chunks until the API
            returns an empty window. Used by the backfill script.

    Returns the number of newly inserted or updated ``SleepSession`` rows.
    """
    if not _eight_sleep_configured():
        return 0

    log = SyncLog(
        source="eight_sleep",
        sync_type="full" if full_history else "incremental",
        status="running",
    )
    db.add(log)
    await db.flush()

    try:
        if full_history:
            count = await _sync_full_history(db, client)
        else:
            end = date.today()
            start = end - timedelta(days=days)
            count = await _sync_window(db, client, start, end)

        log.status = "success"
        log.records_synced = count
        log.completed_at = datetime.now(timezone.utc)
        await db.commit()
        return count

    except Exception as e:
        log.status = "error"
        log.error_message = str(e)[:1000]
        log.completed_at = datetime.now(timezone.utc)
        await db.commit()
        raise


# ── Window sync ─────────────────────────────────────────────────────


async def _sync_window(
    db: AsyncSession,
    client: EightSleepClient,
    start: date,
    end: date,
) -> int:
    """Pull trends + intervals for [start, end] and upsert."""
    trends = await client.get_trends(start, end)
    intervals = await client.get_intervals(start, end)

    intervals_by_date = _index_intervals_by_date(intervals)
    count = 0

    for day in trends:
        day_str = day.get("day") or day.get("date")
        if not day_str:
            continue
        try:
            sleep_date = date.fromisoformat(day_str[:10])
        except ValueError:
            logger.debug("skipping unparseable Eight Sleep day: %r", day_str)
            continue

        interval = intervals_by_date.get(sleep_date)

        fields = _extract_fields(day, interval)
        raw = {"trend": day, "interval": interval} if interval else {"trend": day}

        existing = (await db.execute(
            select(SleepSession).where(
                SleepSession.source == "eight_sleep",
                SleepSession.date == sleep_date,
            )
        )).scalar_one_or_none()

        if existing:
            # Refresh mutable fields — Eight Sleep occasionally back-fills
            # scores and timeseries for a night long after it ends.
            changed = False
            for k, v in fields.items():
                if v is not None and getattr(existing, k) != v:
                    setattr(existing, k, v)
                    changed = True
            existing.raw_data = raw
            if changed:
                count += 1
        else:
            db.add(SleepSession(
                source="eight_sleep",
                date=sleep_date,
                raw_data=raw,
                **fields,
            ))
            count += 1

    await db.commit()
    return count


async def _sync_full_history(
    db: AsyncSession,
    client: EightSleepClient,
) -> int:
    """Walk backwards 90 days at a time until the API returns no data."""
    chunk = timedelta(days=90)
    end = date.today()
    start = end - chunk
    total = 0
    empty_chunks = 0

    while True:
        logger.info("Eight Sleep backfill: fetching %s → %s", start, end)
        rows = await _sync_window(db, client, start, end)
        total += rows

        if rows == 0:
            empty_chunks += 1
            # Two consecutive empty windows → we've walked past the first
            # night this user ever slept on the Pod. Stop.
            if empty_chunks >= 2:
                break
        else:
            empty_chunks = 0

        end = start - timedelta(days=1)
        start = end - chunk

    return total


# ── Field extraction ────────────────────────────────────────────────


def _extract_fields(trend: dict, interval: dict | None) -> dict[str, Any]:
    """Map Eight Sleep's trend + interval payloads to model columns.

    Eight Sleep's trend row shape (empirically):
        sleepDuration          int — total asleep time in seconds
        presenceDuration       int — time in bed in seconds
        deepDuration / remDuration / lightDuration
                               int — per-stage durations in seconds (top-level)
        sleepStart / sleepEnd  ISO strings
        sleepQualityScore      int 0-100
        score                  int 0-100 (overall)
        sleepRoutineScore      int 0-100 (sleep consistency)
        tnt                    int — toss & turn count
        mainSessionId          str — session identifier

    Per-night timeseries (HR, HRV, respiratory, bed temp) live on the
    interval and are formatted as ``[[iso_ts, value], ...]`` tuples.
    """
    total_sec = trend.get("sleepDuration")
    if not isinstance(total_sec, (int, float)):
        # Very old nights sometimes have sleepDuration as a dict; fall back.
        if isinstance(total_sec, dict):
            total_sec = total_sec.get("total")
        if total_sec is None:
            total_sec = _stage_total(interval)

    presence_sec = trend.get("presenceDuration")
    awake_sec = None
    if isinstance(presence_sec, (int, float)) and isinstance(total_sec, (int, float)):
        awake_sec = max(int(presence_sec) - int(total_sec), 0)

    # Prefer trend's top-level per-stage durations (always present on recent
    # nights); fall back to summing the interval's stages array.
    interval_stage_sec = _stage_breakdown(interval)

    def _pick(trend_key: str, stage: str) -> int | None:
        v = trend.get(trend_key)
        if isinstance(v, (int, float)):
            return int(v)
        return interval_stage_sec.get(stage)

    deep_sec = _pick("deepDuration", "deep")
    rem_sec = _pick("remDuration", "rem")
    light_sec = _pick("lightDuration", "light")
    awake_sec = awake_sec if awake_sec is not None else interval_stage_sec.get("awake")

    # Interval-level timeseries. Values are [[iso_ts, value], ...] tuples.
    ts = (interval or {}).get("timeseries") or {}
    avg_hr = _series_mean(ts.get("heartRate"))
    # Eight Sleep exposes two HRV series:
    #   * ``rmssd``  — the conventional HRV metric (30-100 ms typical)
    #   * ``hrv``    — Eight's proprietary index, values often 100-500+
    # Prefer RMSSD so downstream analytics get physiologically standard numbers.
    hrv = _series_mean(ts.get("rmssd")) or _series_mean(ts.get("hrv"))
    resp = _series_mean(ts.get("respiratoryRate")) or _series_mean(
        ts.get("nemeanRespiratoryRateNightly")
    )
    bed_temp = _series_mean(ts.get("tempBedC"))

    # tnt comes as a scalar on the trend row; fall back to counting the
    # interval timeseries entries if the trend didn't include it.
    tnt_count = trend.get("tnt")
    if tnt_count is None:
        tnt_series = ts.get("tnt") or []
        tnt_count = len(tnt_series) if tnt_series else None
    elif isinstance(tnt_count, (int, float)):
        tnt_count = int(tnt_count)

    # Resolve the night's timezone — prefer the interval's own label, fall
    # back to the user's configured EIGHT_SLEEP_TIMEZONE. Times are returned
    # by Eight Sleep in UTC (…Z) and we convert to local wall-clock so the
    # stored `bed_time` / `wake_time` match what the user sees in the app.
    tz = _resolve_tz((interval or {}).get("timezone"))

    bed_time = _to_local(
        _parse_dt(trend.get("sleepStart"))
        or _parse_dt((interval or {}).get("sleepStart") or (interval or {}).get("ts")),
        tz,
    )
    wake_time = _to_local(
        _parse_dt(trend.get("sleepEnd"))
        or _parse_dt((interval or {}).get("sleepEnd")),
        tz,
    ) or _bed_plus_total(bed_time, total_sec)

    # Wake / out-of-bed detail — only derivable when the interval is present.
    # This also yields the authoritative sleep latency (pre-sleep awake
    # chunks from the stages array), which cleanly excludes mid-night
    # wakes (those roll up into WASO instead).
    wake_stats = _wake_stats(interval)
    latency = wake_stats.get("latency_sec")

    # Fallback for archive nights without interval stages: derive latency
    # from trend-level timestamps (presenceStart → sleepStart). This is
    # coarser and can be contaminated by re-anchored sessions, but it's
    # all we have.
    if latency is None:
        presence_start = _parse_dt(trend.get("presenceStart"))
        sleep_start_utc = _parse_dt(trend.get("sleepStart"))
        if presence_start and sleep_start_utc:
            latency = max(int((sleep_start_utc - presence_start).total_seconds()), 0)

    return {
        "external_id": str(trend.get("mainSessionId") or (interval or {}).get("id") or "") or None,
        "bed_time": bed_time,
        "wake_time": wake_time,
        "total_duration": _sec_to_min(total_sec),
        "deep_sleep": _sec_to_min(deep_sec),
        "rem_sleep": _sec_to_min(rem_sec),
        "light_sleep": _sec_to_min(light_sec),
        "awake_time": _sec_to_min(awake_sec),
        # sleepQualityScore is the primary "how well did you sleep" number.
        "sleep_score": _score(trend.get("sleepQualityScore") or trend.get("score")),
        # sleepFitnessScore doesn't ship on this API; preserve the overall
        # `score` field here for parity (it's Eight's composite metric).
        "sleep_fitness_score": _score(trend.get("score")),
        "avg_hr": avg_hr,
        "hrv": hrv,
        "respiratory_rate": resp,
        "bed_temp": bed_temp,
        "tnt_count": tnt_count if isinstance(tnt_count, int) else None,
        "latency": latency,
        # Wake/out-of-bed stats (NULL on archive nights without intervals).
        "wake_count": wake_stats.get("wake_count"),
        "waso_duration": wake_stats.get("waso_duration"),
        "out_of_bed_count": wake_stats.get("out_of_bed_count"),
        "out_of_bed_duration": wake_stats.get("out_of_bed_duration"),
        "wake_events": wake_stats.get("wake_events"),
    }


def _stage_total(interval: dict | None) -> int | None:
    """Sum the stages array in an interval (fallback when trend lacks it)."""
    if not interval:
        return None
    stages = interval.get("stages") or []
    total = 0
    for s in stages:
        dur = s.get("duration") or s.get("durationSec")
        if isinstance(dur, (int, float)):
            total += int(dur)
    return total or None


# Eight Sleep labels stages with a grab-bag of names across API versions;
# normalize everything to {deep, rem, light, awake}. Anything else we see
# (e.g. "out") is dropped.
_STAGE_ALIASES = {
    "deep": "deep",
    "rem": "rem",
    "light": "light",
    "awake": "awake",
    "wake": "awake",
    "sleep": "light",  # undifferentiated "sleep" chunks lumped as light
}


def _wake_stats(interval: dict | None) -> dict[str, Any]:
    """Derive mid-night wake-up + out-of-bed metrics from an interval.

    Interpretation of Eight Sleep's stages array:
      * the FIRST ``awake`` chunk (before any non-awake stage) = sleep latency,
        NOT counted as a wake-up;
      * each subsequent ``awake`` chunk = one awakening (contributes to WASO);
      * ``out`` chunks at any position = getting up (bathroom, etc.).

    Eight Sleep also pre-computes a ``stageSummary`` dict on the interval;
    when present we prefer its authoritative ``wasoDuration`` over our own
    sum, but everything else is derived from the stages array so we can
    still produce per-event durations.

    Returns a dict with keys ``wake_count``, ``waso_duration`` (minutes),
    ``out_of_bed_count``, ``out_of_bed_duration`` (minutes), and
    ``wake_events`` (list of ``{type, duration_sec, offset_sec}`` dicts
    describing each awakening/out-of-bed event in chronological order).
    Returns an empty dict when no stages data is available.
    """
    if not interval or not interval.get("stages"):
        return {}

    stages = interval["stages"]
    wake_events: list[dict] = []
    waso_sec = 0
    out_sec = 0
    wake_count = 0
    out_count = 0
    latency_sec = 0          # sum of awake/out chunks BEFORE first sleep stage

    seen_sleep = False       # flipped True after first deep/rem/light chunk
    cum_offset_sec = 0       # running offset from the start of the interval

    for s in stages:
        stage = (s.get("stage") or "").lower()
        dur = s.get("duration") or s.get("durationSec") or 0
        if not isinstance(dur, (int, float)):
            dur = 0
        dur = int(dur)

        if stage in ("deep", "rem", "light", "sleep"):
            seen_sleep = True
        elif stage in ("awake", "wake"):
            if seen_sleep:
                wake_count += 1
                waso_sec += dur
                wake_events.append({
                    "type": "awake",
                    "duration_sec": dur,
                    "offset_sec": cum_offset_sec,
                })
            else:
                # Pre-sleep awake chunk — this is sleep latency, not WASO.
                latency_sec += dur
        elif stage == "out":
            if seen_sleep:
                out_count += 1
                out_sec += dur
                wake_events.append({
                    "type": "out",
                    "duration_sec": dur,
                    "offset_sec": cum_offset_sec,
                })
            else:
                # Out-of-bed before falling asleep (e.g. bathroom trip
                # after first getting in bed). Still counts as latency.
                latency_sec += dur

        cum_offset_sec += dur

    # Prefer Eight Sleep's pre-computed WASO if available (slightly different
    # boundary rules for awake-vs-out; their number is the "official" one).
    summary = interval.get("stageSummary") or {}
    if isinstance(summary.get("wasoDuration"), (int, float)):
        waso_sec = int(summary["wasoDuration"])
    if isinstance(summary.get("outDuration"), (int, float)):
        out_sec = int(summary["outDuration"])
    # stageSummary carries the authoritative pre-sleep latency value.
    # Prefer it (covers edge cases our manual loop might miss).
    for key in ("awakeBeforeSleepDuration", "latency", "sleepLatency"):
        v = summary.get(key)
        if isinstance(v, (int, float)):
            latency_sec = int(v)
            break

    return {
        "wake_count": wake_count,
        "waso_duration": _sec_to_min(waso_sec),
        "out_of_bed_count": out_count,
        "out_of_bed_duration": _sec_to_min(out_sec),
        "wake_events": wake_events or None,
        # Latency is the single authoritative value in SECONDS derived
        # from the stages array (pre-sleep awake only, excludes WASO).
        # 0 is a real observation (first stage was sleep) — don't coerce
        # to None. The "no stages data" case is handled by the empty-dict
        # early return above.
        "latency_sec": int(latency_sec),
    }


def _stage_breakdown(interval: dict | None) -> dict[str, int]:
    """Sum per-stage duration (seconds) from an interval's stages array."""
    out: dict[str, int] = {}
    if not interval:
        return out
    for s in interval.get("stages") or []:
        raw_stage = (s.get("stage") or "").lower()
        stage = _STAGE_ALIASES.get(raw_stage)
        if not stage:
            continue
        dur = s.get("duration") or s.get("durationSec")
        if isinstance(dur, (int, float)):
            out[stage] = out.get(stage, 0) + int(dur)
    return out


def _index_intervals_by_date(intervals: list[dict]) -> dict[date, dict]:
    """Pick the longest interval per night (multiple nap intervals possible).

    Eight Sleep's trend rows key nights by the calendar date the user woke
    up on. Intervals carry ``ts`` = bedtime. We normalize by shifting evening
    bedtimes (hour >= 18) forward one day so ``night_date`` matches the
    trend's ``day`` field.
    """
    out: dict[date, dict] = {}
    for iv in intervals:
        start_ts = _parse_dt(iv.get("ts"))
        if not start_ts:
            continue
        if start_ts.hour >= 18:
            night_date = start_ts.date() + timedelta(days=1)
        else:
            night_date = start_ts.date()

        existing = out.get(night_date)
        if existing is None or _total(iv) > _total(existing):
            out[night_date] = iv
    return out


def _total(iv: dict) -> int:
    stages = iv.get("stages") or []
    return sum(int(s.get("duration") or 0) for s in stages)


def _score(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        for key in ("total", "score", "value"):
            v = val.get(key)
            if isinstance(v, (int, float)):
                return float(v)
    return None


def _mean(series: list[float] | None) -> float | None:
    if not series:
        return None
    vals = [v for v in series if isinstance(v, (int, float))]
    return sum(vals) / len(vals) if vals else None


def _series_mean(series: list | None) -> float | None:
    """Mean of an Eight Sleep timeseries.

    Handles both shapes the API has used over the years:
      * raw ``[v1, v2, ...]`` (legacy)
      * ``[[iso_ts, v1], [iso_ts, v2], ...]`` (current)
    """
    if not series:
        return None
    vals: list[float] = []
    for entry in series:
        if isinstance(entry, (int, float)):
            vals.append(float(entry))
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            v = entry[1]
            if isinstance(v, (int, float)):
                vals.append(float(v))
    return sum(vals) / len(vals) if vals else None


def _sec_to_min(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(round(float(val) / 60.0))
    except (TypeError, ValueError):
        return None


def _parse_dt(val: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp into a tz-aware UTC datetime."""
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    # Normalise any naive value to UTC so downstream arithmetic is unambiguous.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _resolve_tz(interval_tz: str | None) -> ZoneInfo:
    """Return a ZoneInfo to use for local-time conversion."""
    for name in (interval_tz, settings.eight_sleep.timezone, "UTC"):
        if not name:
            continue
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            logger.warning("Unknown timezone %r, trying next fallback", name)
    return ZoneInfo("UTC")


def _to_local(dt: datetime | None, tz: ZoneInfo) -> datetime | None:
    """Convert a tz-aware UTC datetime to naive local wall-clock time.

    We store the result without tzinfo because the SQLAlchemy ``DateTime``
    column is naive; the effective timezone is either the interval's
    ``timezone`` field or ``EIGHT_SLEEP_TIMEZONE`` from settings.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).replace(tzinfo=None)


def _bed_plus_total(bed_time: datetime | None, total_sec: int | None) -> datetime | None:
    if not bed_time or not total_sec:
        return None
    return bed_time + timedelta(seconds=int(total_sec))


def _eight_sleep_configured() -> bool:
    from backend.config import settings
    return bool(
        settings.eight_sleep.refresh_token
        or (settings.eight_sleep.email and settings.eight_sleep.password)
    )

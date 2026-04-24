"""Drift check: backend Pydantic snapshot models vs frontend TS interfaces.

The public insight API still returns plain dictionaries, so the frontend
mirrors the backend snapshot contracts as hand-written TypeScript interfaces
in ``frontend/src/api/insights.ts``. The most common drift is a new field
added on one side and forgotten on the other. This test parses both files
and asserts name parity, which is lightweight enough to skip a full
TS-codegen pipeline.

If a new snapshot model is added, either:
- add a matching TS interface with identical field names, or
- extend ``INLINED_OR_INTERNAL`` below with a one-line reason.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from backend.services import insight_schemas, snapshot_models
from backend.services.snapshot_models import SnapshotModel

REPO_ROOT = Path(__file__).resolve().parents[2]
INSIGHTS_TS = REPO_ROOT / "frontend" / "src" / "api" / "insights.ts"

# Backend models that intentionally do not have a 1:1 TS interface.
INLINED_OR_INTERNAL = {
    # Inlined into ``TrainingLoadSnapshot.daily_loads`` on the TS side.
    "DailyLoadPoint",
    # Internal backend-only cache key shape; never sent to the frontend.
    "DailyRecommendationCacheSignal",
}


def _collect_backend_models() -> dict[str, type[BaseModel]]:
    models: dict[str, type[BaseModel]] = {}
    for cls in SnapshotModel.__subclasses__():
        if cls.__name__ in INLINED_OR_INTERNAL:
            continue
        models[cls.__name__] = cls
    # LLM response schemas live in a sibling module but mirror the same contract.
    for name in ("DailyRecommendation", "NotableSegment", "WorkoutInsight"):
        models[name] = getattr(insight_schemas, name)
    return models


_INTERFACE_RE = re.compile(
    r"^export interface (?P<name>\w+)\s*\{\s*$(?P<body>.*?)^\}\s*$",
    re.MULTILINE | re.DOTALL,
)
# Match leading-whitespace field declarations like ``  foo?: Bar;`` and
# ``  foo: Bar | null;``. Skips blank lines and ``//`` comments.
_FIELD_RE = re.compile(r"^\s{2}(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\??\s*:")


def _parse_frontend_interfaces() -> dict[str, set[str]]:
    text = INSIGHTS_TS.read_text()
    interfaces: dict[str, set[str]] = {}
    for match in _INTERFACE_RE.finditer(text):
        fields: set[str] = set()
        for line in match.group("body").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            field_match = _FIELD_RE.match(line)
            if field_match:
                fields.add(field_match.group("name"))
        interfaces[match.group("name")] = fields
    return interfaces


def test_snapshot_ts_interfaces_mirror_backend_field_names():
    """Each backend snapshot model has a same-named TS interface with the same fields."""
    backend_models = _collect_backend_models()
    frontend_interfaces = _parse_frontend_interfaces()

    missing_interfaces = sorted(set(backend_models) - set(frontend_interfaces))
    assert not missing_interfaces, (
        "Backend snapshot model(s) have no matching TS interface in "
        f"frontend/src/api/insights.ts: {missing_interfaces}. Either add the "
        "interface or extend INLINED_OR_INTERNAL with a reason."
    )

    field_mismatches: dict[str, dict[str, set[str]]] = {}
    for name, model in backend_models.items():
        backend_fields = set(model.model_fields.keys())
        frontend_fields = frontend_interfaces[name]
        if backend_fields != frontend_fields:
            field_mismatches[name] = {
                "only_backend": backend_fields - frontend_fields,
                "only_frontend": frontend_fields - backend_fields,
            }

    assert not field_mismatches, (
        "Snapshot field drift between backend Pydantic models and TS interfaces:\n"
        + "\n".join(
            f"  {name}: backend-only={sorted(diff['only_backend'])}, "
            f"frontend-only={sorted(diff['only_frontend'])}"
            for name, diff in field_mismatches.items()
        )
    )


def test_snapshot_models_module_exposes_all_expected_contracts():
    """Sanity check: the models we expect to drift-test are all importable."""
    expected = {
        "TrainingLoadSnapshot",
        "SleepSnapshot",
        "RecoverySnapshot",
        "LatestWorkoutSnapshot",
        "FullSnapshot",
    }
    assert expected.issubset(name for name in dir(snapshot_models))

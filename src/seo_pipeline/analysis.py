import hashlib

from .config import Scoring
from .models import Candidate, Delta, Metric, Movement, Row, Snapshot


def delta(
    current: float | None, previous: float | None
) -> tuple[float | None, float | None]:
    if current is None or previous is None:
        return None, None
    change = current - previous
    return round(change, 6), round(change / previous * 100, 2) if previous else None


def movements(
    current: list[Row] | None,
    previous: list[Row] | None,
    current_complete: bool = False,
    previous_complete: bool = False,
) -> list[Movement]:
    now = {r.key: r for r in current or []}
    old = {r.key: r for r in previous or []}
    result = []
    for key in sorted(now.keys() | old.keys()):
        c, p = now.get(key), old.get(key)
        improvement = (
            round(p.position - c.position, 3)
            if c and p and c.position is not None and p.position is not None
            else None
        )
        if c is None:
            status = "LOST" if current is not None and current_complete else "UNKNOWN"
        elif p is None:
            status = "NEW" if previous is not None and previous_complete else "UNKNOWN"
        else:
            status = (
                "UNKNOWN"
                if improvement is None
                else "IMPROVED"
                if improvement > 0
                else "DECLINED"
                if improvement < 0
                else "UNCHANGED"
            )
        result.append(
            Movement(
                key=key,
                source=(c or p).source,
                current=c,
                previous=p,
                status=status,
                position_improvement=improvement,
                clicks_change=delta(c.clicks, p.clicks)[0] if c and p else None,
            )
        )
    return result


def buckets(rows: list[Row] | None) -> dict[str, int] | None:
    if rows is None:
        return None
    ranks = [r.position for r in rows if r.position is not None]
    return {
        name: sum(low <= p <= high for p in ranks)
        for name, low, high in [
            ("Top 3", 1, 3),
            ("Top 10", 1, 10),
            ("11-20", 11, 20),
            ("21-50", 21, 50),
            ("51-100", 51, 100),
        ]
    }


def candidates(
    rows: list[Movement], scoring: Scoring, page: bool = False
) -> list[Candidate]:
    output = []
    for movement in rows:
        row = movement.current or movement.previous
        kinds: list[tuple[str, str]] = []
        if page:
            if movement.clicks_change:
                kinds.append(
                    (
                        "PAGE_GAIN" if movement.clicks_change > 0 else "PAGE_LOSS",
                        "First-party page clicks changed between the two periods.",
                    )
                )
        else:
            if (
                movement.current
                and row.position is not None
                and 11 <= row.position <= 20
            ):
                kinds.append(
                    (
                        "STRIKING_DISTANCE",
                        "Observed position is between 11 and 20; review intent, coverage, and internal links.",
                    )
                )
            if (
                movement.current
                and scoring.low_ctr is not None
                and row.impressions is not None
                and row.impressions >= scoring.min_impressions
                and row.position is not None
                and row.position <= scoring.max_ctr_position
                and row.ctr is not None
                and row.ctr < scoring.low_ctr
            ):
                kinds.append(
                    (
                        "LOW_CTR",
                        f"CTR is below the configured operator threshold ({scoring.low_ctr:.2%}), with at least {scoring.min_impressions} impressions and position at or above the configured visibility cutoff. This is a heuristic, not a universal benchmark.",
                    )
                )
            if movement.status in {"NEW", "LOST", "IMPROVED", "DECLINED"}:
                kinds.append(
                    (
                        movement.status,
                        "Change is supported by comparable observations; absence is classified only when the opposite collection is complete.",
                    )
                )
        for kind, reason in kinds:
            parts = {
                "proximity": 25
                if row.position is not None and 11 <= row.position <= 20
                else 0,
                "demand": 20 if (row.search_volume or 0) >= scoring.min_volume else 0,
                "impressions": 20
                if (row.impressions or 0) >= scoring.min_impressions
                else 0,
                "clicks": 10 if (row.clicks or 0) >= 50 else 0,
                "movement": min(15, int(abs(movement.position_improvement or 0) * 3)),
                "ranking_url": 10 if row.ranking_url else 0,
                "risk_or_ctr": 15 if kind in {"LOW_CTR", "LOST", "PAGE_LOSS"} else 0,
            }
            score = min(100, sum(parts.values()))
            priority = (
                "HIGH"
                if score >= scoring.high
                else "MEDIUM"
                if score >= scoring.medium
                else "LOW"
            )
            identity = hashlib.sha256(
                f"{row.source}:{kind}:{row.key}".encode()
            ).hexdigest()[:16]
            output.append(
                Candidate(
                    id=identity,
                    priority=priority,
                    opportunity_type=kind,
                    score=score,
                    score_components=parts,
                    evidence=movement,
                    reason=reason,
                    recommended_investigation=[
                        "Review search intent and page coverage",
                        "Review title and search-result presentation",
                        "Review internal links and competing results",
                    ],
                )
            )
    return sorted(output, key=lambda c: (-c.score, c.id))


def analyze(
    snapshot: Snapshot, previous: Snapshot | None, scoring: Scoring
) -> Snapshot:
    c = snapshot.collection
    p = previous.collection if previous else None
    for name in sorted(c.metrics.keys() | (p.metrics.keys() if p else set())):
        cm = c.metrics.get(name)
        pm = p.metrics.get(name) if p else None
        provenance = cm or Metric(
            value=None,
            source=pm.source,
            measurement_type=pm.measurement_type,
            period_start=snapshot.reporting_period.start,
            period_end=snapshot.reporting_period.end,
        )
        cv, pv = cm.value if cm else None, pm.value if pm else None
        if (
            cm
            and pm
            and (cm.source != pm.source or cm.temporal_basis != pm.temporal_basis)
        ):
            pv = None
        change, pct = delta(cv, pv)
        snapshot.metrics[name] = Delta(
            current=cv,
            previous=pv,
            absolute_change=change,
            percent_change=pct,
            percentage_point_change=round(change * 100, 3)
            if name == "ctr" and change is not None
            else None,
            position_improvement=-change
            if name == "average_position" and change is not None
            else None,
            provenance=provenance,
            previous_provenance=pm,
        )
    for attr in ("keywords", "queries", "pages"):
        setattr(
            snapshot,
            attr,
            movements(
                getattr(c, attr),
                getattr(p, attr) if p else None,
                getattr(c, attr + "_complete"),
                getattr(p, attr + "_complete") if p else False,
            ),
        )
    snapshot.keyword_distribution = buckets(c.keywords)
    snapshot.keyword_comparison_available = bool(
        p is not None
        and c.keywords is not None
        and p.keywords is not None
        and c.keywords_complete
        and p.keywords_complete
        and all(row.status != "UNKNOWN" for row in snapshot.keywords)
    )
    snapshot.trends = {
        status.lower(): [r.key for r in snapshot.keywords if r.status == status]
        for status in ("NEW", "LOST", "IMPROVED", "DECLINED", "UNCHANGED", "UNKNOWN")
    }
    snapshot.candidates = sorted(
        candidates(snapshot.keywords + snapshot.queries, scoring)
        + candidates(snapshot.pages, scoring, page=True),
        key=lambda x: (-x.score, x.id),
    )
    signals = [
        snapshot.metrics[k].absolute_change
        for k in ("clicks", "impressions")
        if k in snapshot.metrics and snapshot.metrics[k].absolute_change is not None
    ]
    snapshot.direction = (
        "INSUFFICIENT_DATA"
        if not signals
        else "STABLE"
        if all(v == 0 for v in signals)
        else "MIXED"
        if any(v > 0 for v in signals) and any(v < 0 for v in signals)
        else "POSITIVE"
        if any(v > 0 for v in signals)
        else "NEGATIVE"
    )
    return snapshot

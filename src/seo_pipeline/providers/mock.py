import json
from importlib.resources import files

from ..config import Site
from ..models import Collection, Metric, Row
from ..periods import Period


class MockProvider:
    def collect(self, site: Site, period: Period) -> Collection:
        # Fixed fixtures are deliberately re-dated for credential-free demonstrations.
        month = "2026-07" if period.start.month % 2 else "2026-06"
        data = json.loads(
            files("seo_pipeline")
            .joinpath(f"fixtures/{month}.json")
            .read_text(encoding="utf-8")
        )
        metrics = {
            name: Metric(
                value=value,
                source="mock",
                measurement_type="synthetic",
                period_start=period.start,
                period_end=period.end,
            )
            for name, value in data["metrics"].items()
        }

        def rows(key: str) -> list[Row]:
            return [
                Row(
                    source="mock",
                    **{
                        k: v.replace("example.com", site.domain)
                        if isinstance(v, str)
                        else v
                        for k, v in r.items()
                    },
                )
                for r in data[key]
            ]

        return Collection(
            provider="mock",
            metrics=metrics,
            keywords=rows("keywords"),
            queries=rows("queries"),
            pages=rows("pages"),
            keywords_complete=True,
            queries_complete=True,
            pages_complete=True,
            warnings=[
                f"Synthetic demonstration data from {month}; re-dated to the requested period. Not actual site performance."
            ],
        )

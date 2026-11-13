"""Let the planner reuse the sport plugin's own analyses instead of rebuilding them from raw rows.

A run repeats ``plugin.analyze`` for the SAME subject, windows and season type with different
metrics, situational splits or analysis domain. The plugin's qualifying rules, opponent
adjustment, league benchmarks and representative plays therefore apply unchanged.
"""
from __future__ import annotations

from typing import Any

from sports_analyst.models import AnalysisRequest

MAX_RUNS = 3
MAX_METRICS = 6
MAX_SPLITS = 4


class SportRuns:
    def __init__(self, app, request: AnalysisRequest, identifier: str, loaded: dict[str, Any] | None = None):
        """``loaded`` may hold the datasets already loaded for ``request`` (keys: datasets, manifests,
        supplemental, supplemental_manifests) so a same-domain run does not reload them."""
        self.app, self.request, self.identifier = app, request, identifier
        self.connector, self.plugin = app._sport(request.sport)
        self._loaded = {request.analysis_domain: loaded} if loaded else {}
        self._options = None
        self.runs: list[dict[str, Any]] = []

    @property
    def options(self):
        if self._options is None:
            self._options = self.app.analysis_options(self.request.sport, self.request.scope.competition)
        return self._options

    def _subject_type(self) -> str:
        return self.request.subject.type if self.request.subject else "team"

    def _domains(self) -> list[dict[str, str]]:
        kind = self._subject_type()
        return [item for item in self.options.analysis_domains if item.get("subject_type", "team") in {kind, "both"}]

    def _metrics(self, domain: str) -> list[dict[str, str]]:
        kind = self._subject_type()
        return [{"value": m.value, "label": m.label, "description": m.description}
                for m in self.options.metrics if m.analysis_domain == domain and kind in m.subject_types]

    def describe(self) -> dict[str, Any]:
        domains = self._domains()
        return {
            "current": {"analysis_domain": self.request.analysis_domain, "metrics": self.request.metrics,
                        "splits": self.request.splits},
            "analysis_domains": [{"value": d["value"], "label": d.get("label"), "description": d.get("description"),
                                  "metrics": self._metrics(d["value"])} for d in domains],
            "splits": [{"value": s.value, "label": s.label, "description": s.description} for s in self.options.split_dimensions],
            "analyses_included_in_each_run": [{"tool": t.name, "description": t.description} for t in self.plugin.tools()],
            "runs_remaining": MAX_RUNS - len(self.runs),
            "note": ("A run repeats the sport's own analysis for the same subject, windows and season type. "
                     "It applies the sport's qualifying rules, benchmarks, opponent adjustment and play selection, "
                     "which raw-row aggregation does not."),
        }

    def _data(self, request: AnalysisRequest) -> dict[str, Any]:
        cached = self._loaded.get(request.analysis_domain)
        if cached is None:
            from sports_analyst.application.investigation_data import load_investigation_data

            _partition, manifests, datasets, supplemental_manifests, supplemental = load_investigation_data(
                self.app, request, self.identifier, self.connector, self.plugin)
            cached = {"datasets": datasets, "manifests": manifests, "supplemental": supplemental,
                      "supplemental_manifests": supplemental_manifests}
            self._loaded[request.analysis_domain] = cached
        return cached

    def _checked_settings(self, analysis_domain: str, metrics: list[str], splits: list[str]) -> dict[str, Any]:
        domain = (analysis_domain or self.request.analysis_domain).strip().lower()
        allowed_domains = {d["value"] for d in self._domains()}
        if domain not in allowed_domains:
            raise ValueError(f"Unsupported analysis_domain {domain!r} for this subject. Allowed: {sorted(allowed_domains)}")
        allowed_metrics = {m["value"] for m in self._metrics(domain)}
        metrics = list(dict.fromkeys(m.strip().lower() for m in metrics if m.strip()))
        if len(metrics) > MAX_METRICS or not set(metrics) <= allowed_metrics:
            raise ValueError(f"Choose at most {MAX_METRICS} metrics for {domain}. "
                             f"Unknown: {sorted(set(metrics) - allowed_metrics)}; allowed: {sorted(allowed_metrics)}")
        allowed_splits = {s.value for s in self.options.split_dimensions}
        splits = list(dict.fromkeys(s.strip().lower() for s in splits if s.strip()))
        if len(splits) > MAX_SPLITS or not set(splits) <= allowed_splits:
            raise ValueError(f"Choose at most {MAX_SPLITS} splits. Unknown: {sorted(set(splits) - allowed_splits)}; "
                             f"allowed: {sorted(allowed_splits)}")
        return {"analysis_domain": domain, "metrics": metrics, "splits": splits}

    def scope_change(self, baseline_season: int = 0, comparison_season: int = 0, analysis_domain: str = "",
                     metrics: list[str] | None = None, splits: list[str] | None = None, season_type: str = "") -> AnalysisRequest:
        """Validate a follow-up's new scope for the same subject; only installed seasons are accepted."""
        current = self.request.scope
        if current.comparison_design == "head_to_head":
            raise ValueError("Head-to-head reports cannot change scope in a follow-up")
        scope = current.model_dump(mode="json")
        if baseline_season or comparison_season:
            start, end = baseline_season or current.baseline.season, comparison_season or current.comparison.season
            if start > end:
                raise ValueError("baseline_season must not be later than comparison_season")
            if start == end:
                raise ValueError("Choose two different seasons, or keep the report's windows")
            scope.update(baseline={"season": start}, comparison={"season": end},
                         comparison_design="full_seasons" if current.comparison_design == "full_seasons" else "week_ranges")
        if season_type:
            if season_type.upper() not in {"REG", "POST", "ALL"}:
                raise ValueError("season_type must be REG, POST or ALL")
            scope["season_type"] = season_type.upper()
        keep_settings = not analysis_domain and metrics is None and splits is None
        settings = ({"analysis_domain": self.request.analysis_domain, "metrics": self.request.metrics,
                     "splits": self.request.splits} if keep_settings else
                    self._checked_settings(analysis_domain, metrics or [], splits or []))
        try:
            request = AnalysisRequest.model_validate({**self.request.model_dump(mode="json"), **settings, "scope": scope})
        except ValueError as error:
            raise ValueError(f"Invalid scope: {str(error)[:300]}") from None
        installed = set(self.options.available_seasons)
        missing = sorted(set(request.scope.included_seasons) - installed) if installed else []
        if missing:
            raise ValueError(f"Seasons {missing} are not installed. Tell the user to start a new report from setup "
                             f"to prepare them; installed seasons: {sorted(installed)}")
        if (request.scope == current and request.analysis_domain == self.request.analysis_domain
                and request.metrics == self.request.metrics and request.splits == self.request.splits):
            raise ValueError("The proposed scope is the report's own; answer from its evidence instead")
        return request

    def run(self, analysis_domain: str, metrics: list[str], splits: list[str]):
        if len(self.runs) >= MAX_RUNS:
            raise ValueError(f"Sport-analysis budget of {MAX_RUNS} runs exhausted")
        key = self._checked_settings(analysis_domain, metrics, splits)
        if key in [item["arguments"] for item in self.runs]:
            raise ValueError("This sport analysis was already run; inspect its evidence instead")
        if key == {"analysis_domain": self.request.analysis_domain, "metrics": self.request.metrics, "splits": self.request.splits}:
            raise ValueError("These are the report's own settings; its evidence is already available")
        request = AnalysisRequest.model_validate({**self.request.model_dump(), **key})
        data = self._data(request)
        self.runs.append({"arguments": key})
        return self.plugin.analyze(request, data["datasets"], data["manifests"], data["supplemental"],
                                   data["supplemental_manifests"])

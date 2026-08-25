<script lang="ts">
    import {onMount} from 'svelte';
    import {api} from './api';
    import Chart from './Chart.svelte';
    import Icon from './Icon.svelte';
    import PlayTablet from './PlayTablet.svelte';
    import type {AnalysisOptions, Capabilities, Claim, DatasetManifest, Evidence, Investigation, MetricOption, TeamOption} from './types';

    let capabilities: Capabilities | null = null;
    let analysisOptions: AnalysisOptions | null = null;
    let datasets: DatasetManifest[] = [];
    let history: Investigation[] = [];
    let active: Investigation | null = null;
    let conversationThread: Investigation[] = [];
    let selectedEvidenceItems: Evidence[] = [];
    let selectedClaimId: string | null = null;
    let selectedPlay: Evidence | null = null;
    let evidenceLoading = false;
    let evidenceError = '';
    let evidenceRequestVersion = 0;
    const domainExampleQuestions = {
        passing: "Why did this team's passing efficiency change?",
        rushing: "How did this team's rushing performance change?",
        offense: "How did this team's overall offensive efficiency change?"
    } as const;
    const exampleQuestions = [
        domainExampleQuestions.passing,
        "Did this team become more consistent, or was the change concentrated in a few periods?",
        "Which games had the greatest influence on the difference between these periods?",
        "How did this team move relative to the rest of the league?",
        "Was the change driven more by completion quality or explosive passes?",
        "Does opponent-adjusted EPA tell the same story as the raw results?",
        "Where does the clearest sustained change in performance begin?",
        "Which receivers gained or lost the most target share between these periods?",
        "Which quarterback-receiver connections changed the most?",
        "Which representative plays best support—and challenge—the overall finding?",
        domainExampleQuestions.rushing,
        domainExampleQuestions.offense
    ];
    let question = exampleQuestions[0];
    let team = '';
    let teamInput = '';
    let teamFilter = '';
    let teamComboboxOpen = false;
    let activeTeamIndex = 0;
    let baseline = 2024;
    let comparison = 2025;
    let baselineStartWeek = 1;
    let baselineEndWeek = 18;
    let comparisonStartWeek = 1;
    let comparisonEndWeek = 18;
    let splitWeek = 10;
    let comparisonMode = 'full_seasons';
    let analysisDomain: 'passing' | 'rushing' | 'offense' = 'passing';
    let seasonType: 'REG' | 'POST' | 'ALL' = 'REG';
    let selectedMetrics: string[] = [];
    let selectedSplits: string[] = [];
    let syncSeasons: number[] = [];
    let syncDatasets: string[] = ['play_by_play'];
    let dataManagerOpen = true;
    let initializedSelections = false;
    let stage = '';
    let progress = 0;
    let error = '';
    let busy = false;
    let followup = '';
    let followupBusy = false;
    let pendingFollowup = '';

    $: requiredSeasons = comparisonMode === 'before_after'
        ? [baseline]
        : comparisonMode === 'full_seasons' && baseline < comparison
            ? Array.from({length: comparison - baseline + 1}, (_, index) => baseline + index)
            : [baseline, comparison];
    $: resolvedTeam = resolveTeam(teamInput);
    $: filteredTeams = (analysisOptions?.teams ?? []).filter((option) => {
        const query = teamFilter.trim().toUpperCase();
        return !query || option.value.includes(query) || option.label.toUpperCase().includes(query);
    });
    $: windowsDiffer = comparisonMode === 'before_after'
        || (comparisonMode === 'full_seasons' ? baseline < comparison : baseline !== comparison
            || baselineStartWeek !== comparisonStartWeek
            || baselineEndWeek !== comparisonEndWeek);
    $: missingRequiredSeasons = requiredSeasons.filter((season) => !analysisOptions?.available_seasons.includes(season));
    $: hasRequiredData = requiredSeasons.every((season) => analysisOptions?.available_seasons.includes(season));
    $: canRun = Boolean(
        resolvedTeam && question.trim().length >= 3 && windowsDiffer && hasRequiredData && selectedAvailableMetricCount > 0
    );
    $: indexedSeasonCount = new Set(datasets.filter((dataset) => dataset.dataset === 'play_by_play').map((dataset) => dataset.season)).size;
    $: domainMetrics = (analysisOptions?.metrics ?? []).filter((metric) => metric.analysis_domain === analysisDomain);
    $: metricCategories = [...new Set(domainMetrics.map((metric) => metric.category))];
    $: availableMetrics = domainMetrics.filter(metricAvailable);
    $: selectedAvailableMetricCount = availableMetrics.filter((metric) => selectedMetrics.includes(metric.value)).length;
    $: allAvailableMetricsSelected = availableMetrics.length > 0 && selectedAvailableMetricCount === availableMetrics.length;
    $: eligibleSyncDatasets = syncSeasons.length
        ? (analysisOptions?.syncable_datasets ?? []).filter((dataset) => packageEligible(dataset, syncSeasons))
        : [];
    $: allEligibleSyncDatasetsSelected = eligibleSyncDatasets.length > 0
        && eligibleSyncDatasets.every((dataset) => syncDatasets.includes(dataset));
    $: selectedClaim = active?.claims.find((claim) => claim.claim_id === selectedClaimId) ?? null;
    $: rootHistory = history.filter((item) => !item.run.parent_investigation_id);

    onMount(refresh);

    async function refresh() {
        try {
            [capabilities, analysisOptions, datasets, history] = await Promise.all([
                api.capabilities(), api.analysisOptions(), api.datasets(), api.investigations()
            ]);
            initializeSelections();
            const roots = history.filter((item) => !item.run.parent_investigation_id);
            if (active) active = history.find((item) => item.run.investigation_id === active?.run.investigation_id) ?? active;
            if (!active && roots.length) active = roots[0];
            if (active) conversationThread = threadFor(active);
        } catch (problem) {
            error = String(problem);
        }
    }

    function initializeSelections() {
        if (!analysisOptions) return;
        const seasons = [...analysisOptions.available_seasons].sort((left, right) => right - left);
        if (seasons.length) {
            if (!seasons.includes(comparison)) comparison = seasons[0];
            if (!seasons.includes(baseline)) baseline = seasons[1] ?? seasons[0];
        }
        if (!initializedSelections) {
            selectedMetrics = [...analysisOptions.default_metrics];
            const localSeasons = [...analysisOptions.available_seasons].sort((left, right) => right - left);
            syncSeasons = localSeasons.length
                ? localSeasons.slice(0, 2)
                : analysisOptions.syncable_seasons.slice(0, 2);
            selectLocallyAvailablePackages();
            initializedSelections = true;
        }
    }

    function teamDisplay(value: string, label: string) {
        return `${label} (${value})`;
    }

    function openTeamCombobox(event: FocusEvent) {
        teamFilter = '';
        teamComboboxOpen = true;
        activeTeamIndex = Math.max(0, (analysisOptions?.teams ?? []).findIndex((option) => option.value === team));
        (event.currentTarget as HTMLInputElement).select();
    }

    function updateTeamFilter() {
        teamFilter = teamInput;
        teamComboboxOpen = true;
        activeTeamIndex = 0;
    }

    function selectTeam(option: TeamOption) {
        team = option.value;
        teamInput = teamDisplay(option.value, option.label);
        teamFilter = '';
        teamComboboxOpen = false;
    }

    function moveTeamHighlight(index: number) {
        if (!filteredTeams.length) return;
        activeTeamIndex = (index + filteredTeams.length) % filteredTeams.length;
        requestAnimationFrame(() => document.getElementById(`team-option-${filteredTeams[activeTeamIndex]?.value}`)?.scrollIntoView({block: 'nearest'}));
    }

    function handleTeamKeydown(event: KeyboardEvent) {
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            if (!teamComboboxOpen) teamComboboxOpen = true;
            else moveTeamHighlight(activeTeamIndex + 1);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            if (!teamComboboxOpen) teamComboboxOpen = true;
            else moveTeamHighlight(activeTeamIndex - 1);
        } else if (event.key === 'Enter' && teamComboboxOpen && filteredTeams[activeTeamIndex]) {
            event.preventDefault();
            selectTeam(filteredTeams[activeTeamIndex]);
        } else if (event.key === 'Escape') {
            event.preventDefault();
            teamComboboxOpen = false;
        }
    }

    function resolveTeam(value: string) {
        const token = value.trim().toUpperCase();
        const match = analysisOptions?.teams.find((option) =>
            option.value === token || option.label.toUpperCase() === token || teamDisplay(option.value, option.label).toUpperCase() === token
        );
        team = match?.value ?? '';
        return team;
    }

    function metricAvailable(metric: MetricOption) {
        return requiredSeasons.every((season) => metric.available_seasons.includes(season));
    }

    function toggleMetric(metric: string) {
        selectedMetrics = selectedMetrics.includes(metric)
            ? selectedMetrics.filter((value) => value !== metric)
            : [...selectedMetrics, metric];
    }

    function splitAvailable(availableSeasons: number[]) {
        return requiredSeasons.every((season) => availableSeasons.includes(season));
    }

    function toggleSplit(split: string) {
        selectedSplits = selectedSplits.includes(split)
            ? selectedSplits.filter((value) => value !== split)
            : [...selectedSplits, split];
    }

    function useRecommendedMetrics() {
        const recommended = new Set(analysisOptions?.default_metrics_by_domain?.[analysisDomain] ?? analysisOptions?.default_metrics ?? []);
        selectedMetrics = availableMetrics.filter((metric) => recommended.has(metric.value)).map((metric) => metric.value);
    }

    function selectAnalysisDomain(domain: 'passing' | 'rushing' | 'offense') {
        if (analysisDomain === domain) return;
        analysisDomain = domain;
        const recommended = new Set(analysisOptions?.default_metrics_by_domain?.[domain] ?? []);
        selectedMetrics = (analysisOptions?.metrics ?? [])
            .filter((metric) => metric.analysis_domain === domain && metricAvailable(metric) && recommended.has(metric.value))
            .map((metric) => metric.value);
        if ((Object.values(domainExampleQuestions) as readonly string[]).includes(question)) {
            question = domainExampleQuestions[domain];
        }
    }

    function selectAllMetrics() {
        selectedMetrics = availableMetrics.map((metric) => metric.value);
    }

    function showAnotherExample() {
        const alternatives = exampleQuestions.filter((example) => example !== question);
        question = alternatives[Math.floor(Math.random() * alternatives.length)] ?? exampleQuestions[0];
    }

    function toggleSyncDataset(dataset: string) {
        syncDatasets = syncDatasets.includes(dataset)
            ? syncDatasets.filter((value) => value !== dataset)
            : [...syncDatasets, dataset];
    }

    function toggleAllSyncDatasets() {
        syncDatasets = allEligibleSyncDatasetsSelected ? [] : [...eligibleSyncDatasets];
    }

    function selectLocallyAvailablePackages() {
        if (!syncSeasons.length) {
            syncDatasets = [];
            return;
        }
        const locallyAvailable = (analysisOptions?.syncable_datasets ?? []).filter((dataset) =>
            isReferenceDataset(dataset)
                ? datasets.some((item) => item.dataset === dataset)
                : syncSeasons.some((season) => syncedPackages(season).has(dataset))
        );
        syncDatasets = locallyAvailable.length ? locallyAvailable : ['play_by_play'];
    }

    function toggleSyncSeason(season: number) {
        syncSeasons = syncSeasons.includes(season)
            ? syncSeasons.filter((value) => value !== season)
            : [...syncSeasons, season].sort((left, right) => right - left);
        selectLocallyAvailablePackages();
    }

    function datasetLabel(dataset: string) {
        const labels: Record<string, string> = {
            play_by_play: 'Play By Play',
            player_stats: 'Player Stats',
            rosters: 'Rosters',
            injuries: 'Injuries',
            schedules: 'Schedules',
            snap_counts: 'Snap Counts',
            nextgen_passing: 'Nextgen Passing',
            participation: 'Play Participation',
            weekly_rosters: 'Weekly Rosters',
            depth_charts: 'Depth Charts',
            nextgen_receiving: 'Nextgen Receiving',
            nextgen_rushing: 'Nextgen Rushing',
            ftn_charting: 'FTN Charting',
            pfr_passing: 'PFR Advanced Passing',
            pfr_rushing: 'PFR Advanced Rushing',
            pfr_receiving: 'PFR Advanced Receiving',
            pfr_defense: 'PFR Advanced Defense',
            players: 'Player Directory',
            teams: 'Team Directory'
        };
        return labels[dataset] ?? dataset.replaceAll('_', ' ');
    }

    function chartGuidance(specification: Record<string, unknown>) {
        const encoding = specification.encoding as Record<string, unknown> | undefined;
        const x = encoding?.x as Record<string, unknown> | undefined;
        const color = encoding?.color as Record<string, unknown> | undefined;
        if (x?.field === 'metric' && color?.field === 'season') {
            return 'Grouped bars include every season in the selected range.';
        }
        return x?.field === 'season'
            ? 'One continuous trend across seasons; labeled endpoints mark the baseline and comparison seasons.'
            : '';
    }

    function syncedPackages(season: number) {
        return new Set(datasets.filter((dataset) => dataset.season === season).map((dataset) => dataset.dataset));
    }

    function isReferenceDataset(dataset: string) {
        return dataset === 'players' || dataset === 'teams';
    }

    function datasetMinimumSeason(dataset: string) {
        const value = Number(analysisOptions?.dataset_min_seasons?.[dataset]);
        return Number.isFinite(value) && value > 0 ? value : null;
    }

    function eligibleSelectedSeasons(dataset: string, selectedSeasons = syncSeasons) {
        const minimum = datasetMinimumSeason(dataset);
        return selectedSeasons.map(Number).filter((season) => Number.isFinite(season) && (!minimum || season >= minimum));
    }

    function seasonPackageStatus(season: number) {
        const packages = syncedPackages(season);
        const total = analysisOptions?.syncable_datasets.filter((dataset) => {
            const minimum = datasetMinimumSeason(dataset);
            return !isReferenceDataset(dataset) && (!minimum || season >= minimum);
        }).length ?? 0;
        if (!packages.size) return 'Not local';
        if (packages.size === 1 && packages.has('play_by_play')) return 'PBP only';
        return `${packages.size}/${total || packages.size} local`;
    }

    function packageCoverage(dataset: string, selectedSeasons = syncSeasons) {
        if (isReferenceDataset(dataset)) {
            return datasets.some((item) => item.dataset === dataset) ? 'shared local' : 'shared reference';
        }
        if (!selectedSeasons.length) return 'Select seasons';
        const eligibleSeasons = eligibleSelectedSeasons(dataset, selectedSeasons);
        const local = eligibleSeasons.filter((season) => syncedPackages(season).has(dataset)).length;
        const minimum = datasetMinimumSeason(dataset);
        if (!eligibleSeasons.length) return `not offered · ${minimum}+`;
        return `${local}/${eligibleSeasons.length} local${minimum ? ` · ${minimum}+` : ''}`;
    }

    function packageEligible(dataset: string, selectedSeasons = syncSeasons) {
        if (isReferenceDataset(dataset)) return true;
        return eligibleSelectedSeasons(dataset, selectedSeasons).length > 0;
    }

    function packagePartiallyAvailable(dataset: string, selectedSeasons = syncSeasons) {
        if (isReferenceDataset(dataset)) return false;
        const eligibleSeasons = eligibleSelectedSeasons(dataset, selectedSeasons);
        const local = eligibleSeasons.filter((season) => syncedPackages(season).has(dataset)).length;
        return local > 0 && local < eligibleSeasons.length;
    }

    function showPartialSelection(node: HTMLInputElement, partial: boolean) {
        node.indeterminate = partial;
        return {
            update(nextPartial: boolean) {
                node.indeterminate = nextPartial;
            }
        };
    }

    function wait(milliseconds: number) {
        return new Promise((resolve) => setTimeout(resolve, milliseconds));
    }

    async function pollInvestigation(investigationId: string) {
        stage = 'Live progress interrupted · checking the saved investigation';
        progress = Math.max(progress, 0.95);
        for (let attempt = 0; attempt < 30; attempt += 1) {
            try {
                active = await api.investigation(investigationId);
                await refresh();
                return true;
            } catch {
                if (attempt < 29) await wait(2_000);
            }
        }
        return false;
    }

    function stream(url: string, complete: () => Promise<void>, recover?: () => Promise<boolean>, onSettled?: () => void) {
        const source = new EventSource(url);
        let settled = false;
        let recovering = false;

        async function recoverOrFail(message: string) {
            if (settled || recovering) return;
            recovering = true;
            source.close();
            if (recover && await recover()) {
                settled = true;
                busy = false;
                onSettled?.();
                return;
            }
            settled = true;
            error = message;
            busy = false;
            onSettled?.();
        }

        source.onmessage = async (message) => {
            const event = JSON.parse(message.data);
            stage = event.message;
            progress = event.progress;
            if (event.stage === 'complete') {
                settled = true;
                source.close();
                try {
                    await complete();
                } catch (problem) {
                    error = String(problem);
                }
                busy = false;
                onSettled?.();
            }
            if (event.stage === 'failed') {
                settled = true;
                source.close();
                error = event.message;
                busy = false;
                onSettled?.();
            }
            if (event.stage === 'timeout') {
                await recoverOrFail('The investigation is still unavailable after the progress stream timed out. Refresh to check again.');
            }
        };
        source.onerror = () => {
            void recoverOrFail('The progress stream disconnected and the investigation could not be recovered. Refresh to check again.');
        };
    }

    async function runAnalysis() {
        if (!canRun || !resolvedTeam) return;
        error = '';
        busy = true;
        active = null;
        clearEvidenceSelection();
        progress = 0.03;
        stage = 'Starting investigation';
        try {
            let baselineWindow: { season: number; weeks: [number, number] } = {season: baseline, weeks: [1, 22]};
            let comparisonWindow: { season: number; weeks: [number, number] } = {season: comparison, weeks: [1, 22]};
            if (comparisonMode === 'week_ranges') {
                baselineWindow = {season: baseline, weeks: [baselineStartWeek, baselineEndWeek]};
                comparisonWindow = {season: comparison, weeks: [comparisonStartWeek, comparisonEndWeek]};
            } else if (comparisonMode === 'before_after') {
                baselineWindow = {season: baseline, weeks: [1, splitWeek - 1]};
                comparisonWindow = {season: baseline, weeks: [splitWeek, 22]};
            }
            const metrics = selectedMetrics.filter((value) => {
                const option = analysisOptions?.metrics.find((metric) => metric.value === value);
                return option ? metricAvailable(option) : false;
            });
            const splits = selectedSplits.filter((value) => {
                const option = analysisOptions?.split_dimensions.find((split) => split.value === value);
                return option ? splitAvailable(option.available_seasons) : false;
            });
            const {investigation_id} = await api.investigate({
                question: question.trim(),
                analysis_domain: analysisDomain,
                scope: {
                    team: resolvedTeam,
                    baseline: baselineWindow,
                    comparison: comparisonWindow,
                    season_type: seasonType,
                    comparison_design: comparisonMode as 'full_seasons' | 'week_ranges' | 'before_after'
                },
                metrics,
                splits
            });
            stream(
                `/api/investigations/${investigation_id}/events`,
                async () => {
                    active = await api.investigation(investigation_id);
                    await refresh();
                },
                () => pollInvestigation(investigation_id)
            );
        } catch (problem) {
            error = String(problem);
            busy = false;
        }
    }

    async function syncData() {
        if (!syncSeasons.length || !syncDatasets.length) return;
        error = '';
        busy = true;
        stage = 'Preparing data sync';
        try {
            const {job_id} = await api.sync(syncSeasons, syncDatasets);
            stream(`/api/dataset-jobs/${job_id}/events`, async () => {
                await refresh();
            });
        } catch (problem) {
            error = String(problem);
            busy = false;
        }
    }

    function clearEvidenceSelection() {
        evidenceRequestVersion += 1;
        selectedClaimId = null;
        selectedEvidenceItems = [];
        evidenceLoading = false;
        evidenceError = '';
        selectedPlay = null;
    }

    function openPlay(play: Evidence) {
        selectedPlay = play;
        void inspect(play.evidence_id);
    }

    function rootIdFor(investigation: Investigation) {
        let current = investigation;
        const visited = new Set<string>();
        while (current.run.parent_investigation_id && !visited.has(current.run.investigation_id)) {
            visited.add(current.run.investigation_id);
            const parent = history.find((item) => item.run.investigation_id === current.run.parent_investigation_id);
            if (!parent) return current.run.parent_investigation_id;
            current = parent;
        }
        return current.run.investigation_id;
    }

    function threadFor(investigation: Investigation) {
        const rootId = rootIdFor(investigation);
        return history
            .filter((item) => rootIdFor(item) === rootId)
            .sort((left, right) => new Date(left.run.created_at).getTime() - new Date(right.run.created_at).getTime());
    }

    function openInvestigation(investigation: Investigation | null) {
        active = investigation;
        conversationThread = investigation ? threadFor(investigation) : [];
        clearEvidenceSelection();
    }

    function startNewAnalysis() {
        openInvestigation(null);
        useRecommendedMetrics();
    }

    async function inspect(identifier: string) {
        if (!active) return;
        const requestVersion = ++evidenceRequestVersion;
        selectedClaimId = null;
        selectedEvidenceItems = [];
        evidenceLoading = true;
        evidenceError = '';
        try {
            const evidence = await api.evidence(active.run.investigation_id, identifier) as Evidence;
            if (requestVersion !== evidenceRequestVersion) return;
            selectedEvidenceItems = [evidence];
        } catch (problem) {
            if (requestVersion === evidenceRequestVersion) evidenceError = String(problem);
        } finally {
            if (requestVersion === evidenceRequestVersion) evidenceLoading = false;
        }
    }

    async function inspectFinding(claim: Claim) {
        if (!active) return;
        const requestVersion = ++evidenceRequestVersion;
        selectedClaimId = claim.claim_id;
        selectedEvidenceItems = [];
        evidenceLoading = true;
        evidenceError = '';
        try {
            const evidence = await Promise.all(
                claim.evidence_ids.map((identifier) => api.evidence(active!.run.investigation_id, identifier) as Promise<Evidence>)
            );
            if (requestVersion !== evidenceRequestVersion) return;
            selectedEvidenceItems = evidence;
        } catch (problem) {
            if (requestVersion === evidenceRequestVersion) evidenceError = String(problem);
        } finally {
            if (requestVersion === evidenceRequestVersion) evidenceLoading = false;
        }
    }

    async function sendFollowup() {
        if (!active || !followup.trim() || followupBusy) return;
        const question = followup.trim();
        const root = conversationThread[0] ?? active;
        followupBusy = true;
        pendingFollowup = question;
        followup = '';
        clearEvidenceSelection();
        try {
            const {investigation_id} = await api.followUp(root.run.investigation_id, question);
            stream(
                `/api/investigations/${investigation_id}/events`,
                async () => {
                    active = await api.investigation(investigation_id);
                    await refresh();
                    conversationThread = threadFor(active);
                },
                async () => {
                    const recovered = await pollInvestigation(investigation_id);
                    if (recovered && active) conversationThread = threadFor(active);
                    return recovered;
                },
                () => {
                    followupBusy = false;
                    pendingFollowup = '';
                }
            );
        } catch (problem) {
            error = String(problem);
            followupBusy = false;
            pendingFollowup = '';
        }
    }

    async function deleteInvestigation(item: Investigation) {
        const identifier = item.run.investigation_id;
        if (!window.confirm(`Delete the saved ${item.run.scope.team} analysis? This cannot be undone.`)) return;
        try {
            const deletedRoot = rootIdFor(item);
            await api.deleteInvestigation(identifier);
            history = history.filter((saved) => rootIdFor(saved) !== deletedRoot);
            if (active && rootIdFor(active) === deletedRoot) {
                const remainingRoots = history.filter((saved) => !saved.run.parent_investigation_id);
                active = remainingRoots[0] ?? null;
                conversationThread = active ? threadFor(active) : [];
                clearEvidenceSelection();
            }
        } catch (problem) {
            error = String(problem);
        }
    }
</script>

<svelte:head><title>Open Sports Analyst</title></svelte:head>

<div class="app-shell">
    <aside class="rail">
        <div class="brand"><img class="mark" src="/favicon.svg" alt="" aria-hidden="true"/>
            <div><strong>Open Sports</strong><span>Analyst</span></div>
        </div>
        <nav aria-label="Primary">
            <button class="new-investigation" class:active={!active} on:click={startNewAnalysis}>
                <span class="new-icon"><Icon name="clipboard-plus" size={20}/></span> New Analysis
            </button>
            <div class="nav-label">
                <Icon name="history" size={15}/>
                Recent Film Room
            </div>
            {#each rootHistory.slice(0, 8) as item}
                <div class="recent-report">
                    <button class="recent-report-link" class:active={active ? rootIdFor(active) === item.run.investigation_id : false}
                            on:click={() => openInvestigation(item)}>
                        <span>{item.run.scope.team}</span>
                        <div>{item.run.question}
                            <small>{item.run.scope.comparison_design === 'full_seasons' ? `Full Seasons ${item.run.scope.baseline.season}–${item.run.scope.comparison.season}` : `${item.run.scope.baseline.season} W${item.run.scope.baseline.weeks[0]}–${item.run.scope.baseline.weeks[1]} → ${item.run.scope.comparison.season} W${item.run.scope.comparison.weeks[0]}–${item.run.scope.comparison.weeks[1]}`}</small>
                            {#if threadFor(item).length > 1}<small class="thread-count">{threadFor(item).length - 1}
                                follow-up{threadFor(item).length === 2 ? '' : 's'}</small>{/if}
                        </div>
                    </button>
                    <button class="delete-report" type="button" aria-label={`Delete investigation thread: ${item.run.question}`} title="Delete investigation thread"
                            on:click={() => deleteInvestigation(item)}>
                        <Icon name="trash" size={16}/>
                    </button>
                </div>
            {/each}
        </nav>
        <div class="runtime">
            <span class="runtime-icon" class:ready={capabilities?.model_configured}><Icon name="brain" size={18}/></span>
            <div>
                <strong>{capabilities?.configured_provider || 'Loading'}</strong><span>{capabilities?.model_configured ? 'Model READY' : 'Deterministic Mode'}</span>
            </div>
        </div>
    </aside>

    <main>
        <header class="topbar">
            <div><span class="eyebrow">NFL · EVIDENCE WORKBENCH</span>
                <h1>{active ? `${active.run.scope.team} investigation` : 'Analyze and Discuss Football Play-by-Play Data!'}</h1></div>
            <div class="status-chip">
                <Icon name="database" size={16}/>{indexedSeasonCount} seasons · {datasets.length} data packages
            </div>
        </header>

        {#if error}
            <div class="error" role="alert">{error}</div>
        {/if}

        {#if !active && !busy}
            <section class="ask-panel">
                <div class="intro-grid">
                    <div class="ask-copy"><span class="eyebrow">START WITH THE EVIDENCE</span>
                        <h2>Turn play-by-play into an argument you can inspect.</h2>
                        <p>Choose the exact team, windows, and metrics. The analyst handles the football reasoning while every measurement stays tied to valid local
                            data.</p>
                    </div>
                    <details class="data-manager" bind:open={dataManagerOpen}>
                        <summary>
                            <span><strong>Manage Local nflverse Data</strong><small>Choose the seasons and packages to load for your investigations.</small></span><b>{datasets.length}
                            local files <i>
                                <Icon name="chevron-down" size={16}/>
                            </i></b></summary>
                        <div class="onboarding">
                            <div class="sync-guidance"><strong>Local Data Library</strong><span>Play-by-play is required. Package checkboxes choose what to sync next; coverage is calculated for the selected seasons, and “not offered” means those seasons predate that package.</span>
                            </div>
                            <div class="sync-fields">
                                <fieldset class="season-picker">
                                    <legend>Seasons</legend>
                                    <div class="season-options" role="group" aria-label="Seasons to sync">
                                        {#each analysisOptions?.syncable_seasons ?? [] as season}
                                            <label class:selected={syncSeasons.includes(season)}>
                                                <input type="checkbox" aria-label={`${season} season`} checked={syncSeasons.includes(season)}
                                                       on:change={() => toggleSyncSeason(season)}/>
                                                <strong>{season}</strong>
                                                <small>{seasonPackageStatus(season)}</small>
                                            </label>
                                        {/each}
                                    </div>
                                </fieldset>
                                <fieldset class="dataset-picker">
                                    <legend><span>Packages</span><button class="package-toggle" type="button" disabled={!eligibleSyncDatasets.length}
                                                                          on:click={toggleAllSyncDatasets}>
                                        {allEligibleSyncDatasetsSelected ? 'Deselect all' : 'Select all'}
                                    </button></legend>
                                    <div class="dataset-options">
                                        {#each analysisOptions?.syncable_datasets ?? [] as dataset}<label><input type="checkbox"
                                                                                                                 checked={syncDatasets.includes(dataset)}
                                                                                                                 disabled={!packageEligible(dataset, syncSeasons)}
                                                                                                                 use:showPartialSelection={packagePartiallyAvailable(dataset, syncSeasons)}
                                                                                                                 on:change={() => toggleSyncDataset(dataset)}/><span>{datasetLabel(dataset)}
                                            <small>{packageCoverage(dataset, syncSeasons)}</small></span></label>{/each}
                                    </div>
                                </fieldset>
                            </div>
                            <button disabled={!syncSeasons.length || !syncDatasets.length} on:click={syncData}>Sync Selected Data
                                <Icon name="database-import" size={18}/>
                            </button>
                        </div>
                    </details>
                </div>
                <section class="scope-card" aria-labelledby="scope-heading">
                    <div class="scope-heading">
                        <div><span class="eyebrow">01 · SCOPE</span>
                            <h3 id="scope-heading">Define Comparison</h3></div>
                        <span>{analysisOptions?.available_seasons.length ?? 0} seasons available</span></div>
                    <div class="scope-controls">
                        <div class="team-control">
                            <label for="nfl-team">Team</label>
                            <div class="team-combobox">
                                <input id="nfl-team" role="combobox" bind:value={teamInput} aria-label="NFL team" aria-expanded={teamComboboxOpen}
                                       aria-controls="nfl-team-options"
                                       aria-autocomplete="list"
                                       aria-activedescendant={teamComboboxOpen && filteredTeams[activeTeamIndex] ? `team-option-${filteredTeams[activeTeamIndex].value}` : undefined}
                                       aria-invalid={Boolean(teamInput && !resolvedTeam)} autocomplete="off" placeholder="Search Teams…" on:focus={openTeamCombobox}
                                       on:input={updateTeamFilter} on:keydown={handleTeamKeydown} on:blur={() => teamComboboxOpen = false}/>
                                <button class="combobox-toggle" type="button" aria-label="Show NFL teams" tabindex="-1"
                                        on:mousedown|preventDefault={() => teamComboboxOpen = !teamComboboxOpen}>
                                    <Icon name="chevron-down" size={17}/>
                                </button>
                                {#if teamComboboxOpen}
                                    <div class="team-options" id="nfl-team-options" role="listbox" aria-label="NFL teams">
                                        {#each filteredTeams as option, index}
                                            <button id={`team-option-${option.value}`} type="button" role="option" aria-selected={team === option.value}
                                                    class:active={index === activeTeamIndex} on:mousedown|preventDefault={() => selectTeam(option)}
                                                    on:mouseenter={() => activeTeamIndex = index}>
                                                <span>{option.label}</span><b>{option.value}</b>
                                            </button>
                                        {:else}
                                            <div class="no-team-results">No teams match “{teamFilter}”</div>
                                        {/each}
                                    </div>
                                {/if}
                            </div>
                            {#if teamInput && !resolvedTeam}<small class="validation">Choose a team from the list.</small>{/if}
                        </div>
                        <label>Comparison design
                            <select bind:value={comparisonMode}>
                                {#each analysisOptions?.comparison_windows ?? [] as option}
                                    <option value={option.value}
                                            disabled={option.value === 'full_seasons' && (analysisOptions?.available_seasons.length ?? 0) < 2}>{option.label}</option>
                                {/each}
                            </select>
                        </label>
                        <label>Season type
                            <select bind:value={seasonType}>
                                <option value="REG">Regular season</option>
                                <option value="POST">Postseason</option>
                                <option value="ALL">All games</option>
                            </select>
                        </label>
                    </div>

                    {#if analysisOptions?.available_seasons.length}
                        {#if comparisonMode === 'before_after'}
                            <div class="window-grid before-after">
                                <label>Season<select bind:value={baseline}>
                                    {#each [...analysisOptions.available_seasons].sort((a, b) => b - a) as season}
                                        <option value={season}>{season}</option>
                                    {/each}
                                </select></label>
                                <label>First week after split<select bind:value={splitWeek}>
                                    {#each analysisOptions.week_values.filter((week) => week > 1) as week}
                                        <option value={week}>Week {week}</option>
                                    {/each}
                                </select></label>
                                <div class="window-summary"><span>Baseline</span><strong>{baseline} · Weeks 1–{splitWeek - 1}</strong></div>
                                <div class="window-summary"><span>Comparison</span><strong>{baseline} · Weeks {splitWeek}–22</strong></div>
                            </div>
                        {:else}
                            <div class="window-grid">
                                <fieldset>
                                    <legend>{comparisonMode === 'full_seasons' ? 'Range start' : 'Baseline window'}</legend>
                                    <label>{comparisonMode === 'full_seasons' ? 'From season' : 'Season'}<select bind:value={baseline}>
                                        {#each [...analysisOptions.available_seasons].sort((a, b) => b - a) as season}
                                            <option value={season}>{season}</option>
                                        {/each}
                                    </select></label>
                                    {#if comparisonMode === 'week_ranges'}
                                        <div class="week-pair"><label>Start<select bind:value={baselineStartWeek}>
                                            {#each analysisOptions.week_values as week}
                                                <option value={week} disabled={week > baselineEndWeek}>W{week}</option>
                                            {/each}
                                        </select></label><label>End<select bind:value={baselineEndWeek}>
                                            {#each analysisOptions.week_values as week}
                                                <option value={week} disabled={week < baselineStartWeek}>W{week}</option>
                                            {/each}
                                        </select></label></div>
                                    {/if}
                                </fieldset>
                                <span class="arrow"><Icon name="arrow-right" size={19}/></span>
                                <fieldset>
                                    <legend>{comparisonMode === 'full_seasons' ? 'Range end' : 'Comparison window'}</legend>
                                    <label>{comparisonMode === 'full_seasons' ? 'Through season' : 'Season'}<select bind:value={comparison}>
                                        {#each [...analysisOptions.available_seasons].sort((a, b) => b - a) as season}
                                            <option value={season}>{season}</option>
                                        {/each}
                                    </select></label>
                                    {#if comparisonMode === 'week_ranges'}
                                        <div class="week-pair"><label>Start<select bind:value={comparisonStartWeek}>
                                            {#each analysisOptions.week_values as week}
                                                <option value={week} disabled={week > comparisonEndWeek}>W{week}</option>
                                            {/each}
                                        </select></label><label>End<select bind:value={comparisonEndWeek}>
                                            {#each analysisOptions.week_values as week}
                                                <option value={week} disabled={week < comparisonStartWeek}>W{week}</option>
                                            {/each}
                                        </select></label></div>
                                    {/if}
                                </fieldset>
                            </div>
                            {#if comparisonMode === 'full_seasons' && windowsDiffer}
                                <p class="range-summary">{`Includes every season from ${baseline} through ${comparison}: ${requiredSeasons.join(', ')}.`}</p>
                            {/if}
                            {#if !windowsDiffer}
                                <p class="validation">{comparisonMode === 'full_seasons' ? 'Choose an ending season later than the starting season.' : 'Choose two different seasons or week ranges.'}</p>
                            {/if}
                            {#if windowsDiffer && missingRequiredSeasons.length}
                                <p class="validation">Sync the missing season{missingRequiredSeasons.length === 1 ? '' : 's'}before running this
                                    range: {missingRequiredSeasons.join(', ')}.</p>
                            {/if}
                        {/if}
                    {:else}
                        <p class="empty-state">Sync at least one nflverse season to configure an investigation.</p>
                    {/if}
                </section>

                <section class="metric-card" aria-labelledby="metric-heading">
                    <div class="scope-heading">
                        <div><span class="eyebrow">02 · METRICS</span>
                            <h3 id="metric-heading">Choose what to measure</h3></div>
                        <div class="metric-actions">
                            <button class="text-button" type="button" on:click={selectAllMetrics} disabled={allAvailableMetricsSelected || !availableMetrics.length}>
                                <Icon name="clipboard-plus" size={16}/>
                                {allAvailableMetricsSelected ? 'All Available Selected' : 'Select All Metrics'}
                            </button>
                            <button class="text-button" type="button" on:click={useRecommendedMetrics}>
                                <Icon name="sparkles" size={16}/>
                                Use Recommended Metrics
                            </button>
                        </div>
                    </div>
                    <div class="domain-selector" role="group" aria-label="Analysis domain">
                        {#each analysisOptions?.analysis_domains ?? [] as domain}
                            <button type="button" class:active={analysisDomain === domain.value} aria-pressed={analysisDomain === domain.value}
                                    on:click={() => selectAnalysisDomain(domain.value)}>
                                <strong>{domain.label}</strong><span>{domain.description}</span>
                            </button>
                        {/each}
                    </div>
                    <p class="section-help"><strong>Recommended metrics are selected by default.</strong> Checked metrics are included and unchecked metrics are
                        excluded. Use Recommended Metrics replaces the current selection with the recommended set.</p>
                    <div class="metric-groups">
                        {#each metricCategories as category}
                            <section class="metric-group" role="group" aria-label={category}>
                                <h4 class="metric-group-title">{category}</h4>
                                {#each domainMetrics.filter((metric) => metric.category === category) as metric}
                                    <label class:unavailable={!metricAvailable(metric)} title={metric.description}>
                                        <input type="checkbox" checked={selectedMetrics.includes(metric.value)} disabled={!metricAvailable(metric)}
                                               on:change={() => toggleMetric(metric.value)}/>
                                        <span><strong>{metric.label}</strong><small>{metric.description}</small></span>
                                    </label>
                                {/each}
                            </section>
                        {/each}
                    </div>
                    <button class="text-button clear-metrics" type="button" on:click={() => selectedMetrics = []}>
                        <Icon name="wand" size={16}/>
                        Clear All Metrics
                    </button>
                    {#if analysisOptions && selectedAvailableMetricCount === 0}
                        <p class="selection-warning">Select AT LEAST ONE available metric to start an investigation!</p>
                    {/if}
                    <div class="split-selector">
                        <div><h4>Diagnostic Cuts</h4>
                            <p>Checked cuts are included as situational breakdowns. Once you select cuts, unchecked cuts are skipped. Leave all clear to use the
                                recommended diagnostic cuts automatically.</p></div>
                        <div class="split-options">
                            {#each analysisOptions?.split_dimensions ?? [] as split}
                                <label class:unavailable={!splitAvailable(split.available_seasons)} title={split.description}>
                                    <input type="checkbox" checked={selectedSplits.includes(split.value)} disabled={!splitAvailable(split.available_seasons)}
                                           on:change={() => toggleSplit(split.value)}/>
                                    <span>{split.label}</span>
                                </label>
                            {/each}
                        </div>
                    </div>
                </section>

                <div class="question-field">
                    <div class="question-heading">
                        <label for="investigation-question">Your Question:</label>
                        <button type="button" on:click={showAnotherExample} aria-label="Show another example question">
                            <Icon name="refresh" size={16}/>
                            Another Example
                        </button>
                    </div>
                    <textarea id="investigation-question" bind:value={question} rows="3"></textarea>
                </div>
                <button class="primary" disabled={!canRun} on:click={runAnalysis}>
                    START INVESTIGATION
                    <Icon name="player-play" size={19}/>
                </button>
            </section>
            <section class="promise-grid">
                <article><span>01</span>
                    <h3>Measured First</h3>
                    <p>EPA, success, explosives, pressure outcomes, and situational splits run through tested tools.</p></article>
                <article><span>02</span>
                    <h3>Interpretation Marked</h3>
                    <p>Football judgment stays distinct from measured claims without losing its analytical edge.</p></article>
                <article><span>03</span>
                    <h3>Every Trail Preserved</h3>
                    <p>Inputs, versions, queries, evidence IDs, caveats, and report artifacts travel together.</p></article>
            </section>
        {:else if busy}
            <section class="working" aria-live="polite" aria-busy="true">
                <div class="field-lines" aria-hidden="true"></div>
                <div class="working-layout">
                    <div class="working-copy">
                        <span class="eyebrow">ANALYSIS IN PROGRESS...</span>
                        <h2>{stage}</h2>
                        <div class="progress" role="progressbar" aria-label="Investigation progress" aria-valuemin="0" aria-valuemax="100"
                             aria-valuenow={Math.round(progress * 100)}><i style={`width:${Math.max(4, progress * 100)}%`}></i></div>
                        <p>The evidence trail is being recorded as each tool completes.</p>
                    </div>
                    <div class="play-visual" aria-hidden="true">
                        <div class="play-caption"><span>LIVE ANALYSIS DRIVE</span><b>{Math.round(progress * 100)}%</b></div>
                        <svg class="catch-scene" viewBox="0 0 360 170" preserveAspectRatio="xMidYMid meet">
                            <path class="field-shadow" d="M19 151H341"/>
                            <path id="analysis-catch-arc" class="catch-arc" d="M70 103 Q180 5 290 103"/>

                            <g class="player-figure player-left">
                                <circle class="player-head" cx="42" cy="73" r="10"/>
                                <path class="player-body" d="M31 88Q42 82 53 88L56 121Q42 129 28 121Z"/>
                                <path class="player-limb" d="M33 93L20 110M51 93L60 101L70 103M35 121L28 151M49 121L57 151"/>
                                <circle class="player-hand" cx="70" cy="103" r="3"/>
                            </g>
                            <g class="player-figure player-right" transform="translate(360 0) scale(-1 1)">
                                <circle class="player-head" cx="42" cy="73" r="10"/>
                                <path class="player-body" d="M31 88Q42 82 53 88L56 121Q42 129 28 121Z"/>
                                <path class="player-limb" d="M33 93L20 110M51 93L60 101L70 103M35 121L28 151M49 121L57 151"/>
                                <circle class="player-hand" cx="70" cy="103" r="3"/>
                            </g>
                            <circle class="catch-signal catch-signal-left" cx="70" cy="103" r="9"/>
                            <circle class="catch-signal catch-signal-right" cx="290" cy="103" r="9"/>

                            <g class="moving-football">
                                <animateMotion dur="3.2s" repeatCount="indefinite" rotate="auto" calcMode="linear"
                                               keyPoints="0;1;1;0;0" keyTimes="0;.4;.5;.9;1">
                                    <mpath href="#analysis-catch-arc"/>
                                </animateMotion>
                                <g transform="translate(-10 -6)">
                                    <ellipse class="football-body" cx="10" cy="6" rx="10" ry="6"/>
                                    <path class="football-laces" d="M6 6h8M8 4.2v3.6M10 4.2v3.6M12 4.2v3.6"/>
                                </g>
                            </g>
                        </svg>
                        <div class="analysis-live"><i></i><span>Analysis still running...</span></div>
                    </div>
                </div>
            </section>
        {:else if active}
            <section class="conversation" aria-label="Investigation conversation">
                <div class="conversation-header">
                    <div><span class="eyebrow">INVESTIGATION THREAD</span>
                        <h2>{active.run.scope.team} Film Room</h2>
                        <p>The initial analysis and every follow-up are saved together. Select any analyst response to inspect its report and evidence.</p>
                    </div>
                    <span class="conversation-count">{Math.max(0, conversationThread.length - 1)} follow-up{conversationThread.length === 2 ? '' : 's'}</span>
                </div>
                <div class="conversation-messages" aria-live="polite">
                    {#each conversationThread as turn, index}
                        <article class="chat-row user-row">
                            <span class="chat-avatar user-avatar">You</span>
                            <div class="chat-bubble user-bubble"><small>{index === 0 ? 'Initial question' : `Follow-up ${index}`}</small>
                                <p>{turn.run.question}</p></div>
                        </article>
                        <div class="chat-row analyst-row">
                            <span class="chat-avatar analyst-avatar"><Icon name="sports-analyst" size={24}/></span>
                            <button class="chat-bubble analyst-bubble" class:selected={active.run.investigation_id === turn.run.investigation_id}
                                    type="button" on:click={() => openInvestigation(turn)}>
                                <small>Open Sports Analyst · {turn.fallback_used ? 'Deterministic' : turn.model_id}</small>
                                <p>{turn.summary}</p>
                                <span>{active.run.investigation_id === turn.run.investigation_id ? 'Viewing this analysis' : 'View analysis and evidence'}
                                    <Icon name="arrow-right" size={15}/></span>
                            </button>
                        </div>
                    {/each}
                    {#if pendingFollowup}
                        <article class="chat-row user-row pending-message">
                            <span class="chat-avatar user-avatar">You</span>
                            <div class="chat-bubble user-bubble"><small>New follow-up</small>
                                <p>{pendingFollowup}</p></div>
                        </article>
                        <article class="chat-row analyst-row pending-message">
                            <span class="chat-avatar analyst-avatar"><Icon name="sports-analyst" size={24}/></span>
                            <div class="chat-bubble analyst-bubble typing"><small>Open Sports Analyst</small>
                                <span class="typing-dots" aria-label="Analyzing follow-up"><i></i><i></i><i></i></span>
                                <p>{stage || 'Planning the next evidence-backed analysis…'}</p></div>
                        </article>
                    {/if}
                </div>
                <div class="chat-composer">
                    <textarea bind:value={followup} rows="2" disabled={followupBusy}
                              aria-label="Ask a follow-up question"
                              placeholder="Ask a follow-up about this investigation…"
                              on:keydown={(event) => {
                                  if (event.key === 'Enter' && !event.shiftKey) {
                                      event.preventDefault();
                                      sendFollowup();
                                  }
                              }}></textarea>
                    <button type="button" disabled={followupBusy || !followup.trim()} on:click={sendFollowup}>
                        {followupBusy ? 'Analyzing' : 'Send'}
                        <Icon name="send" size={18}/>
                    </button>
                    <small>Enter to send · Shift+Enter for a new line</small>
                </div>
            </section>
            <section class="report-hero">
                <div class="report-summary">
                    <span class="eyebrow">FINAL READ · {active.fallback_used ? 'DETERMINISTIC' : active.model_id}</span>
                    <h2>Investigation Summary</h2>
                    <p>{active.summary}</p>
                    <div class="report-meta" aria-label="Investigation scope">
                        <span>{active.run.scope.team}</span>
                        <span>{active.run.analysis_domain === 'rushing' ? 'Rushing' : active.run.analysis_domain === 'offense' ? 'Overall offense' : 'Passing'}</span>
                        <span>{active.run.scope.comparison_design === 'full_seasons' ? `${active.run.scope.baseline.season}–${active.run.scope.comparison.season} inclusive` : `${active.run.scope.baseline.season} W${active.run.scope.baseline.weeks[0]}–${active.run.scope.baseline.weeks[1]} → ${active.run.scope.comparison.season} W${active.run.scope.comparison.weeks[0]}–${active.run.scope.comparison.weeks[1]}`}</span>
                        <span>{active.claims.length} evidence-bound findings</span>
                    </div>
                </div>
                <a class="export" href={`/api/investigations/${active.run.investigation_id}/export?format=html`}>Export Report
                    <Icon name="file-download" size={17}/>
                </a>
            </section>
            <div class="report-grid">
                <section class="findings">
                    <div class="section-title"><span>CORE FINDINGS</span><small>{active.claims.length} evidence-bound claims</small></div>
                    {#each active.claims as claim, index}
                        <button
                            class="finding"
                            class:selected={selectedClaimId === claim.claim_id}
                            type="button"
                            aria-pressed={selectedClaimId === claim.claim_id}
                            aria-label={`Inspect evidence for finding ${index + 1}`}
                            on:click={() => inspectFinding(claim)}
                        >
                            <span class="finding-number">{String(index + 1).padStart(2, '0')}</span>
                            <span class="finding-content"><span class="claim-meta"><span
                                class:interpretation={claim.claim_type === 'interpretation'}>{claim.claim_type}</span><i>{claim.confidence}
                                confidence</i></span><span
                                class="finding-statement">{claim.statement}</span><span class="citations">{#each claim.evidence_ids as id}<span>{id.slice(0, 18)}
                                …</span>{/each}</span></span>
                            <span class="finding-inspect"><Icon name="search" size={17}/></span>
                        </button>
                    {/each}
                </section>
                <aside class="evidence-panel">
                    <div class="section-title"><span>EVIDENCE INSPECTOR</span></div>
                    {#if evidenceLoading}
                        <div class="evidence-loading"><span></span>
                            <p>Loading cited evidence…</p></div>
                    {:else if evidenceError}
                        <p class="evidence-error">{evidenceError}</p>
                    {:else if selectedEvidenceItems.length}
                        <div class="evidence-collection-heading">
                            <strong>{selectedEvidenceItems.length} evidence {selectedEvidenceItems.length === 1 ? 'record' : 'records'}</strong>
                            {#if selectedClaim}<span>Selected finding</span>{/if}
                        </div>
                        <div class="evidence-list">
                            {#each selectedEvidenceItems as evidence, index}
                                <article class="evidence-record">
                                    <div class="evidence-record-heading"><span>{String(index + 1).padStart(2, '0')}</span>
                                        <div>
                                            <span class="evidence-id">{evidence.evidence_id}</span>
                                            <h3>{evidence.label || `Play ${evidence.play_id}`}</h3>
                                        </div>
                                    </div>
                                    {#if evidence.baseline_value != null && evidence.comparison_value != null}
                                        <div class="delta">
                                            <div><span>Baseline</span><strong>{evidence.baseline_value.toFixed(3)}</strong></div>
                                            <b>
                                                <Icon name="arrow-right" size={18}/>
                                            </b>
                                            <div><span>Comparison</span><strong>{evidence.comparison_value.toFixed(3)}</strong></div>
                                        </div>
                                    {/if}
                                    {#if evidence.description}<p>{evidence.description}</p>{/if}
                                    <dl>
                                        <dt>Metric</dt>
                                        <dd>{evidence.metric || 'source play'}</dd>
                                        <dt>Sample</dt>
                                        <dd>{evidence.sample_size || '1 play'}</dd>
                                        <dt>Change / EPA</dt>
                                        <dd>{evidence.value ?? evidence.epa}</dd>
                                    </dl>
                                    {#each evidence.caveats || [] as caveat}<p class="caveat">{caveat}</p>{/each}
                                </article>
                            {/each}
                        </div>
                    {:else}
                        <div class="empty-evidence"><b>
                            <Icon name="click" size={28}/>
                        </b>
                            <p>Select a finding card to inspect its values, sample, and caveats.</p></div>
                    {/if}
                </aside>
            </div>
            <section class="charts">
                <div class="section-title"><span>THE SHAPE OF THE CHANGE</span></div>
                <div class="chart-grid">
                    {#each active.charts as chart}
                        <article><h3>{chart.title}</h3>
                            {#if chartGuidance(chart.specification)}<p class="chart-note">{chartGuidance(chart.specification)}</p>{/if}
                            <Chart specification={chart.specification} team={active.run.scope.team}/>
                        </article>
                    {/each}
                </div>
            </section>
            <section class="plays">
                <div class="section-title"><span>REPRESENTATIVE PLAYS</span><small>Support & Counterexamples</small></div>
                <div class="play-list">
                    {#each active.play_evidence as play}
                        <button class:selected={selectedPlay?.evidence_id === play.evidence_id} aria-expanded={selectedPlay?.evidence_id === play.evidence_id}
                                on:click={() => openPlay(play)}><span class="play-tag"
                                                                      class:supporting={play.supporting}>{play.supporting ? 'support' : 'counter'}</span><strong>{play.game_id}
                            · #{play.play_id}</strong>
                            <p>{play.description}</p><b class="play-epa">{play.epa?.toFixed(2)} EPA</b></button>
                    {/each}
                </div>
                {#if selectedPlay}
                    <PlayTablet play={selectedPlay} onclose={() => selectedPlay = null}/>
                {/if}
            </section>
        {/if}
    </main>
</div>

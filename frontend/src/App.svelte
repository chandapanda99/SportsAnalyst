<script lang="ts">
    import {onMount} from 'svelte';
    import {api} from './api';
    import Chart from './Chart.svelte';
    import BasketballLoadingAnimation from './BasketballLoadingAnimation.svelte';
    import BasketballPlayTablet from './BasketballPlayTablet.svelte';
    import Icon from './Icon.svelte';
    import PlayTablet from './PlayTablet.svelte';
    import type {
        AnalysisOptions,
        Capabilities,
        Claim,
        DatasetManifest,
        Evidence,
        Investigation,
        InvestigationSummary,
        MetricOption,
        PlayerOption,
        SportOption,
        TeamOption
    } from './types';

    let capabilities: Capabilities | null = null;
    let sports: SportOption[] = [];
    let activeSport = 'nfl';
    let analysisOptions: AnalysisOptions | null = null;
    let datasets: DatasetManifest[] = [];
    let history: InvestigationSummary[] = [];
    let active: Investigation | null = null;
    let conversationThread: Investigation[] = [];
    let selectedEvidenceItems: Evidence[] = [];
    let selectedClaimId: string | null = null;
    let selectedPlay: Evidence | null = null;
    let evidenceLoading = false;
    let evidenceError = '';
    let evidenceRequestVersion = 0;
    const domainExampleQuestions: Record<string, string> = {
        passing: "Why did this team's passing efficiency change?",
        rushing: "How did this team's rushing performance change?",
        offense: "How did this team's overall offensive efficiency change?",
        quarterback: "How did this quarterback's efficiency and passing outcomes change?",
        receiving: "How did this receiver's volume and efficiency change?",
        running: "How did this ball carrier's rushing volume and efficiency change?",
        defense: "How did this team's defensive efficiency change?",
        scoring: "How did this player's scoring change?",
        shooting: "How did the shot profile and shooting efficiency change?",
        playmaking: "How did playmaking and ball distribution change?",
        rebounding: "How did rebounding performance change?",
        turnovers: "What changed in ball security and turnover outcomes?",
        usage: "How did this player's role and usage change?",
        impact: "How did this player's impact change?",
        lineups: "Which lineup changes best explain the difference?"
    };
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
    let baselineSegment = 'regular_season';
    let comparisonSegment = 'post_all_star';
    let comparisonMode = 'full_seasons';
    let analysisDomain = 'passing';
    let subjectType: 'team' | 'player' = 'team';
    let players: PlayerOption[] = [];
    let selectedPlayerId = '';
    let playerInput = '';
    let playerFilter = '';
    let playerComboboxOpen = false;
    let activePlayerIndex = 0;
    let playerSearchTimer: ReturnType<typeof setTimeout> | undefined;
    let playerSearchVersion = 0;
    let playerTeamId = '';
    let scopeSeasons: number[] = [];
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
    type DraftState = {
        question: string; team: string; teamInput: string; baseline: number; comparison: number;
        comparisonMode: string; analysisDomain: string; subjectType: 'team' | 'player'; selectedPlayerId: string; playerInput: string;
        playerTeamId: string; baselineSegment: string; comparisonSegment: string; selectedMetrics: string[];
        selectedSplits: string[]; syncSeasons: number[]; syncDatasets: string[];
    };
    const sportDrafts: Record<string, DraftState> = {};

    $: requiredSeasons = comparisonMode === 'before_after' || comparisonMode === 'before_after_milestone'
        ? [baseline]
        : comparisonMode === 'full_seasons' && baseline < comparison
            ? Array.from({length: comparison - baseline + 1}, (_, index) => baseline + index)
            : [baseline, comparison];
    $: resolvedTeam = resolveTeam(teamInput);
    $: selectedPlayer = players.find((player) => player.player_id === selectedPlayerId) ?? null;
    $: scopeSeasons = (() => {
        const local = [...(analysisOptions?.available_seasons ?? [])].sort((left, right) => right - left);
        if (subjectType !== 'player' || !selectedPlayer) return local;
        const played = new Set(playerSeasonsForDomain(selectedPlayer).map(Number));
        return local.filter((season) => played.has(season));
    })();
    $: resolvedSubject = subjectType === 'player' ? selectedPlayerId : resolvedTeam;
    $: filteredTeams = (analysisOptions?.teams ?? []).filter((option) => {
        const query = teamFilter.trim().toUpperCase();
        return !query || option.value.includes(query) || option.label.toUpperCase().includes(query);
    });
    $: filteredPlayers = players.filter((player) => {
        const query = playerFilter.trim().toLowerCase();
        return !query || player.name.toLowerCase().includes(query) || player.player_id.toLowerCase().includes(query)
            || player.teams.some((value) => value.toLowerCase().includes(query));
    });
    $: visibleDomains = (analysisOptions?.analysis_domains ?? []).filter((domain) => domainAvailableForSubject(domain, subjectType));
    $: windowsDiffer = comparisonMode === 'before_after' || comparisonMode === 'before_after_milestone'
        || (comparisonMode === 'full_seasons' ? baseline < comparison : activeSport === 'nba'
            ? baseline !== comparison || baselineSegment !== comparisonSegment
            : baseline !== comparison
            || baselineStartWeek !== comparisonStartWeek
            || baselineEndWeek !== comparisonEndWeek);
    $: missingRequiredSeasons = requiredSeasons.filter((season) => !analysisOptions?.available_seasons.includes(season));
    $: hasRequiredData = requiredSeasons.every((season) => analysisOptions?.available_seasons.includes(season));
    $: missingPlayerSeasons = subjectType === 'player' && selectedPlayer
        ? requiredSeasons.filter((season) => !scopeSeasons.includes(season))
        : [];
    $: hasSubjectData = missingPlayerSeasons.length === 0;
    $: canRun = Boolean(
        resolvedSubject && question.trim().length >= 3 && windowsDiffer && hasRequiredData && hasSubjectData
        && selectedAvailableMetricCount > 0
    );
    $: indexedSeasonCount = new Set(datasets.filter((dataset) => dataset.dataset === 'play_by_play').map((dataset) => dataset.season)).size;
    $: domainMetrics = (analysisOptions?.metrics ?? []).filter((metric) =>
        metric.analysis_domain === analysisDomain && (!metric.subject_types?.length || metric.subject_types.includes(subjectType))
    );
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
    $: rootHistory = history.filter((item) => !item.run.parent_investigation_id && (item.run.sport ?? 'nfl') === activeSport);

    onMount(refresh);

    async function refresh() {
        try {
            const [nextCapabilities, nextSports, nextOptions, nextDatasets, nextHistory, nextPlayers] = await Promise.all([
                api.capabilities(), api.sports(), api.analysisOptions(activeSport), api.datasets(), api.investigations(), api.players(activeSport)
            ]);
            capabilities = nextCapabilities;
            sports = nextSports.length ? nextSports : [
                {value: 'nfl', label: 'NFL', available: true, live_available: false},
                {
                    value: 'nba',
                    label: 'NBA',
                    available: true,
                    live_available: false,
                    live_message: 'Live NBA enrichments are unavailable; bulk-data analysis remains enabled.'
                }
            ];
            analysisOptions = nextOptions;
            datasets = nextDatasets.filter((dataset) => (dataset.sport ?? 'nfl') === activeSport);
            history = nextHistory;
            players = nextOptions.subject_types?.some((item) => item.value === 'player') ? nextPlayers : [];
            initializeSelections();
            const roots = history.filter((item) => !item.run.parent_investigation_id);
            const identifier = active?.run.investigation_id ?? roots[0]?.run.investigation_id;
            if (identifier) {
                active = await api.investigation(identifier);
                conversationThread = await api.investigationThread(identifier);
            }
        } catch (problem) {
            error = String(problem);
        }
    }

    async function switchSport(sport: string) {
        if (sport === activeSport || busy) return;
        sportDrafts[activeSport] = {
            question, team, teamInput, baseline, comparison, comparisonMode, analysisDomain, subjectType,
            selectedPlayerId, playerInput, playerTeamId, baselineSegment, comparisonSegment,
            selectedMetrics: [...selectedMetrics], selectedSplits: [...selectedSplits],
            syncSeasons: [...syncSeasons], syncDatasets: [...syncDatasets]
        };
        activeSport = sport;
        active = null;
        conversationThread = [];
        clearEvidenceSelection();
        initializedSelections = false;
        team = '';
        teamInput = '';
        selectedPlayerId = '';
        playerInput = '';
        playerTeamId = '';
        subjectType = 'team';
        analysisDomain = sport === 'nba' ? 'offense' : 'passing';
        comparisonMode = sport === 'nba' ? 'season_segments' : 'full_seasons';
        baselineSegment = 'regular_season';
        comparisonSegment = 'post_all_star';
        question = domainExampleQuestions[analysisDomain];
        await refresh();
        const draft = sportDrafts[sport];
        if (draft) {
            ({
                question, team, teamInput, baseline, comparison, comparisonMode, analysisDomain, subjectType,
                selectedPlayerId, playerInput, playerTeamId, baselineSegment, comparisonSegment
            } = draft);
            selectedMetrics = [...draft.selectedMetrics];
            selectedSplits = [...draft.selectedSplits];
            syncSeasons = [...draft.syncSeasons];
            syncDatasets = [...draft.syncDatasets];
        }
        active = null;
        conversationThread = [];
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
        const validDomains = analysisOptions.analysis_domains.filter((domain) => domainAvailableForSubject(domain));
        if (!validDomains.some((domain) => domain.value === analysisDomain)) {
            analysisDomain = validDomains[0]?.value ?? analysisOptions.analysis_domains[0]?.value ?? analysisDomain;
            useRecommendedMetrics();
        }
    }

    function domainAvailableForSubject(domain: { value?: string; subject_type?: string }, type = subjectType) {
        if (domain.subject_type) {
            return domain.subject_type === 'both' || domain.subject_type === type;
        }
        // Keep older saved/stale option payloads from exposing team domains to
        // player investigations when they predate explicit subject metadata.
        const inferredPlayerDomains = activeSport === 'nfl'
            ? new Set(['quarterback', 'receiving', 'running'])
            : new Set(['scoring', 'usage', 'impact']);
        const inferredTeamDomains = activeSport === 'nfl'
            ? new Set(['passing', 'rushing', 'offense'])
            : new Set(['offense', 'defense', 'lineups']);
        if (inferredPlayerDomains.has(domain.value ?? '')) return type === 'player';
        if (inferredTeamDomains.has(domain.value ?? '')) return type === 'team';
        return true;
    }

    function selectSubjectType(type: 'team' | 'player') {
        subjectType = type;
        if (type === 'team') {
            selectedPlayerId = '';
            playerInput = '';
            playerTeamId = '';
        }
        selectedSplits = [];
        const nextDomain = (analysisOptions?.analysis_domains ?? []).find((domain) => domainAvailableForSubject(domain, type))?.value;
        if (nextDomain) selectAnalysisDomain(nextDomain, true);
        else selectedMetrics = [];
    }

    function playerDisplay(player: PlayerOption) {
        return `${player.name}${player.teams.length ? ` · ${player.teams.join('/')}` : ''}`;
    }

    function openPlayerCombobox(event: FocusEvent) {
        playerFilter = '';
        playerComboboxOpen = true;
        activePlayerIndex = Math.max(0, players.findIndex((player) => player.player_id === selectedPlayerId));
        (event.currentTarget as HTMLInputElement).select();
    }

    function updatePlayerFilter() {
        playerFilter = playerInput;
        selectedPlayerId = '';
        playerTeamId = '';
        playerComboboxOpen = true;
        activePlayerIndex = 0;
        const version = ++playerSearchVersion;
        const query = playerFilter;
        if (playerSearchTimer) clearTimeout(playerSearchTimer);
        playerSearchTimer = setTimeout(async () => {
            try {
                const matches = await api.players(activeSport, query);
                if (version === playerSearchVersion) players = matches;
            } catch (problem) {
                if (version === playerSearchVersion) error = String(problem);
            }
        }, 150);
    }

    function selectPlayer(player: PlayerOption) {
        playerSearchVersion += 1;
        if (playerSearchTimer) clearTimeout(playerSearchTimer);
        selectedPlayerId = player.player_id;
        playerInput = playerDisplay(player);
        playerFilter = '';
        playerTeamId = player.teams.length === 1 ? player.teams[0] : '';
        normalizePlayerSeasonSelection(player);
        playerComboboxOpen = false;
    }

    function normalizePlayerSeasonSelection(player: PlayerOption) {
        const local = new Set(analysisOptions?.available_seasons ?? []);
        const seasons = playerSeasonsForDomain(player).map(Number).filter((season) => local.has(season)).sort((left, right) => right - left);
        if (!seasons.length) return;
        if (!seasons.includes(comparison)) comparison = seasons[0];
        if (!seasons.includes(baseline)) baseline = seasons[1] ?? seasons[0];
        if (comparisonMode === 'full_seasons' && seasons.length > 1 && baseline >= comparison) {
            baseline = seasons[1];
            comparison = seasons[0];
        }
    }

    function playerSeasonsForDomain(player: PlayerOption) {
        if (activeSport === 'nfl' && player.seasons_by_domain) {
            return player.seasons_by_domain[analysisDomain] ?? [];
        }
        return player.seasons;
    }

    function movePlayerHighlight(index: number) {
        if (!filteredPlayers.length) return;
        activePlayerIndex = (index + filteredPlayers.length) % filteredPlayers.length;
        requestAnimationFrame(() => document.getElementById(`player-option-${filteredPlayers[activePlayerIndex]?.player_id}`)?.scrollIntoView({block: 'nearest'}));
    }

    function handlePlayerKeydown(event: KeyboardEvent) {
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            if (!playerComboboxOpen) playerComboboxOpen = true;
            else movePlayerHighlight(activePlayerIndex + 1);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            if (!playerComboboxOpen) playerComboboxOpen = true;
            else movePlayerHighlight(activePlayerIndex - 1);
        } else if (event.key === 'Enter' && playerComboboxOpen && filteredPlayers[activePlayerIndex]) {
            event.preventDefault();
            selectPlayer(filteredPlayers[activePlayerIndex]);
        } else if (event.key === 'Escape') {
            event.preventDefault();
            playerComboboxOpen = false;
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

    function selectAnalysisDomain(domain: string, force = false) {
        if (analysisDomain === domain && !force) return;
        analysisDomain = domain;
        const recommended = new Set(analysisOptions?.default_metrics_by_domain?.[domain] ?? []);
        selectedMetrics = (analysisOptions?.metrics ?? [])
            .filter((metric) => metric.analysis_domain === domain
                && (!metric.subject_types?.length || metric.subject_types.includes(subjectType))
                && metricAvailable(metric) && recommended.has(metric.value))
            .map((metric) => metric.value);
        if (Object.values(domainExampleQuestions).includes(question)) {
            question = domainExampleQuestions[domain] ?? question;
        }
        if (selectedPlayer) normalizePlayerSeasonSelection(selectedPlayer);
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
        syncDatasets = locallyAvailable.length
            ? locallyAvailable
            : activeSport === 'nba'
                ? ['play_by_play', 'schedules', 'team_boxscores', 'player_boxscores']
                : ['play_by_play'];
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
            teams: 'Team Directory',
            team_boxscores: 'Team Box Scores',
            player_boxscores: 'Player Box Scores',
            shots: 'Shots',
            game_rosters: 'Game Rosters',
            officials: 'Officials',
            standings: 'Standings',
            player_season_stats: 'Player Season Stats',
            team_season_stats: 'Team Season Stats',
            draft: 'Draft Results',
            stats_schedules: 'NBA Stats Schedules',
            stats_coaches: 'NBA Stats Coaches',
            stats_game_rosters: 'NBA Stats Game Rosters',
            lineups: 'Five-player Lineups',
            stats_officials: 'NBA Stats Officials',
            stats_play_by_play: 'NBA Stats Play By Play',
            stats_player_boxscores: 'NBA Stats Player Box Scores',
            stats_player_game_logs: 'NBA Stats Player Game Logs',
            stats_player_season_stats: 'NBA Stats Player Season Stats',
            stats_rosters: 'NBA Stats Rosters',
            stats_shots: 'NBA Stats Shots',
            stats_standings: 'NBA Stats Standings',
            stats_team_boxscores: 'NBA Stats Team Box Scores',
            stats_team_season_stats: 'NBA Stats Team Season Stats',
            player_crosswalk: 'Player Crosswalk',
            schedule_crosswalk: 'Schedule Crosswalk',
            team_crosswalk: 'Team Crosswalk',
            player_core: 'Player Identity Core',
            player_impact: 'Player Impact'
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
        return new Set(datasets.filter((dataset) => (dataset.sport ?? 'nfl') === activeSport && dataset.season === season).map((dataset) => dataset.dataset));
    }

    function isReferenceDataset(dataset: string) {
        return dataset === 'players' || dataset === 'teams';
    }

    function datasetMinimumSeason(dataset: string) {
        const value = Number(analysisOptions?.dataset_min_seasons?.[dataset]);
        return Number.isFinite(value) && value > 0 ? value : null;
    }

    function datasetAvailableSeasons(dataset: string) {
        const seasons = analysisOptions?.dataset_available_seasons?.[dataset];
        return Array.isArray(seasons) ? seasons.map(Number).filter(Number.isFinite) : null;
    }

    function eligibleSelectedSeasons(dataset: string, selectedSeasons = syncSeasons) {
        const published = datasetAvailableSeasons(dataset);
        if (published) {
            const offered = new Set(published);
            return selectedSeasons.map(Number).filter((season) => Number.isFinite(season) && offered.has(season));
        }
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
        const published = datasetAvailableSeasons(dataset);
        if (published) {
            if (!eligibleSeasons.length) return 'not offered for selected seasons';
            const first = Math.min(...published);
            const last = Math.max(...published);
            return `${local}/${eligibleSeasons.length} local · ${seasonLabel(first)} to ${seasonLabel(last)}`;
        }
        const minimumLabel = minimum ? `${seasonLabel(minimum)}+` : '';
        if (!eligibleSeasons.length) return `not offered · ${minimumLabel}`;
        return `${local}/${eligibleSeasons.length} local${minimum ? ` · ${minimumLabel}` : ''}`;
    }

    function packageEligible(dataset: string, selectedSeasons = syncSeasons) {
        if (isReferenceDataset(dataset)) return true;
        return eligibleSelectedSeasons(dataset, selectedSeasons).length > 0;
    }

    function seasonLabel(season: number) {
        return activeSport === 'nba' ? `${season - 1}–${String(season).slice(-2)}` : String(season);
    }

    function availableSegments(season: number) {
        const allowed = analysisOptions?.segment_availability?.[String(season)];
        const segments = analysisOptions?.season_segments ?? [];
        if (allowed?.length) return segments.filter((segment) => allowed.includes(segment.value));
        return segments.filter((segment) => ['full_season', 'regular_season', 'playoffs'].includes(segment.value));
    }

    function investigationSubject(item: Investigation | InvestigationSummary) {
        return item.run.subject?.id ?? item.run.scope.team;
    }

    function investigationWindow(item: Investigation | InvestigationSummary) {
        const baselineWindow = item.run.scope.baseline;
        const comparisonWindow = item.run.scope.comparison;
        if (baselineWindow.segment || comparisonWindow.segment) {
            return `${seasonLabel(baselineWindow.season)} ${baselineWindow.segment?.replaceAll('_', ' ') ?? ''} → ${seasonLabel(comparisonWindow.season)} ${comparisonWindow.segment?.replaceAll('_', ' ') ?? ''}`;
        }
        return item.run.scope.comparison_design === 'full_seasons'
            ? `Full Seasons ${baselineWindow.season}–${comparisonWindow.season}`
            : `${baselineWindow.season} W${baselineWindow.weeks[0]}–${baselineWindow.weeks[1]} → ${comparisonWindow.season} W${comparisonWindow.weeks[0]}–${comparisonWindow.weeks[1]}`;
    }

    function displayDomain(domain?: string) {
        return (analysisOptions?.analysis_domains ?? []).find((option) => option.value === domain)?.label
            ?? domain?.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase())
            ?? 'Analysis';
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
            const status = await api.investigationStatus(investigationId);
            stage = status.message;
            progress = Math.max(progress, status.progress);
            if (status.stage === 'failed') throw new Error(status.message);
            if (status.stage === 'complete') {
                active = await api.investigation(investigationId);
                await refresh();
                return true;
            }
            if (attempt < 29) await wait(2_000);
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
            try {
                if (recover && await recover()) {
                    settled = true;
                    busy = false;
                    onSettled?.();
                    return;
                }
                error = message;
            } catch (problem) {
                error = problem instanceof Error ? problem.message : String(problem);
            }
            settled = true;
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
        if (!canRun || !resolvedSubject) return;
        error = '';
        busy = true;
        active = null;
        clearEvidenceSelection();
        progress = 0.03;
        stage = 'Starting investigation';
        try {
            let baselineWindow: { season: number; weeks: [number, number]; segment?: string } = {season: baseline, weeks: [1, 22]};
            let comparisonWindow: { season: number; weeks: [number, number]; segment?: string } = {season: comparison, weeks: [1, 22]};
            if (comparisonMode === 'week_ranges') {
                baselineWindow = {season: baseline, weeks: [baselineStartWeek, baselineEndWeek]};
                comparisonWindow = {season: comparison, weeks: [comparisonStartWeek, comparisonEndWeek]};
            } else if (comparisonMode === 'before_after') {
                baselineWindow = {season: baseline, weeks: [1, splitWeek - 1]};
                comparisonWindow = {season: baseline, weeks: [splitWeek, 22]};
            } else if (comparisonMode === 'season_segments') {
                baselineWindow = {season: baseline, weeks: [1, 22], segment: baselineSegment};
                comparisonWindow = {season: comparison, weeks: [1, 22], segment: comparisonSegment};
            } else if (comparisonMode === 'before_after_milestone') {
                baselineWindow = {season: baseline, weeks: [1, 22], segment: 'pre_all_star'};
                comparisonWindow = {season: baseline, weeks: [1, 22], segment: 'post_all_star'};
            } else if (activeSport === 'nba') {
                baselineWindow = {season: baseline, weeks: [1, 22], segment: 'full_season'};
                comparisonWindow = {season: comparison, weeks: [1, 22], segment: 'full_season'};
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
                sport: activeSport,
                subject: {
                    type: subjectType,
                    id: resolvedSubject,
                    ...(subjectType === 'player' && playerTeamId ? {team_id: playerTeamId} : {})
                },
                question: question.trim(),
                analysis_domain: analysisDomain,
                scope: {
                    team: subjectType === 'team' ? resolvedTeam : playerTeamId || (activeSport === 'nba' ? 'NBA' : 'NFL'),
                    baseline: baselineWindow,
                    comparison: comparisonWindow,
                    season_type: seasonType,
                    comparison_design: comparisonMode
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
        const offeredDatasets = new Set(analysisOptions?.syncable_datasets ?? []);
        const requestedDatasets = syncDatasets.filter((dataset) => offeredDatasets.has(dataset) && packageEligible(dataset, syncSeasons));
        const requestedSeasons = syncSeasons.map(Number).filter((season) => Number.isInteger(season));
        if (!requestedSeasons.length || !requestedDatasets.length) return;
        error = '';
        busy = true;
        stage = 'Preparing data sync';
        try {
            const {job_id} = await api.sync(activeSport, requestedSeasons, requestedDatasets);
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

    function rootIdFor(investigation: Investigation | InvestigationSummary) {
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

    function threadFor(investigation: Investigation | InvestigationSummary) {
        const rootId = rootIdFor(investigation);
        return history
            .filter((item) => rootIdFor(item) === rootId)
            .sort((left, right) => new Date(left.run.created_at).getTime() - new Date(right.run.created_at).getTime());
    }

    async function openInvestigation(investigation: Investigation | InvestigationSummary | null) {
        clearEvidenceSelection();
        if (!investigation) {
            active = null;
            conversationThread = [];
            return;
        }
        try {
            active = 'claims' in investigation
                ? investigation
                : await api.investigation(investigation.run.investigation_id);
            conversationThread = await api.investigationThread(active.run.investigation_id);
        } catch (problem) {
            error = String(problem);
        }
    }

    function startNewAnalysis() {
        void openInvestigation(null);
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
            const evidence = await api.evidenceBatch(active.run.investigation_id, claim.evidence_ids);
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
                },
                async () => {
                    const recovered = await pollInvestigation(investigation_id);
                    if (recovered && active) conversationThread = await api.investigationThread(active.run.investigation_id);
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

    async function deleteInvestigation(item: Investigation | InvestigationSummary) {
        const identifier = item.run.investigation_id;
        if (!window.confirm(`Delete the saved ${investigationSubject(item)} analysis? This cannot be undone.`)) return;
        try {
            const deletedRoot = rootIdFor(item);
            await api.deleteInvestigation(identifier);
            history = history.filter((saved) => rootIdFor(saved) !== deletedRoot);
            if (active && rootIdFor(active) === deletedRoot) {
                const remainingRoots = history.filter((saved) => !saved.run.parent_investigation_id);
                await openInvestigation(remainingRoots[0] ?? null);
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
                        <span>{investigationSubject(item)}</span>
                        <div>{item.run.question}
                            <small>{investigationWindow(item)}</small>
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
        <nav class="sport-tabs" aria-label="Sports">
            {#each sports as sport}
                <button type="button" class:active={activeSport === sport.value} aria-pressed={activeSport === sport.value}
                        disabled={!sport.available || busy} on:click={() => switchSport(sport.value)}>
                    <strong>{sport.label}</strong>
                    {#if sport.value === 'nba'}<small>{sport.live_available ? 'Live enrichments ready' : 'Bulk data mode'}</small>{/if}
                </button>
            {/each}
        </nav>
        <header class="topbar">
            <div><span class="eyebrow">{activeSport.toUpperCase()} · EVIDENCE WORKBENCH</span>
                <h1>{active ? `${investigationSubject(active)} investigation` : `Analyze and Discuss ${activeSport === 'nba' ? 'Basketball' : 'Football'} Play-by-Play Data!`}</h1>
            </div>
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
                        <p>Choose the exact {activeSport === 'nba' ? 'team or player' : 'team'}, windows, and metrics. The analyst handles
                            the {activeSport === 'nba' ? 'basketball' : 'football'} reasoning while every measurement stays tied to valid local
                            data.</p>
                    </div>
                    <details class="data-manager" class:nba-data-manager={activeSport === 'nba'} bind:open={dataManagerOpen}>
                        <summary>
                            <span><strong>Manage Local {activeSport === 'nba' ? 'SportsDataverse NBA' : 'nflverse'} Data</strong><small>Choose the seasons and packages to load for your investigations.</small></span><b>{datasets.length}
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
                                                <strong>{seasonLabel(season)}</strong>
                                                <small>{seasonPackageStatus(season)}</small>
                                            </label>
                                        {/each}
                                    </div>
                                </fieldset>
                                <fieldset class="dataset-picker">
                                    <legend><span>Packages</span>
                                        <button class="package-toggle" type="button" disabled={!eligibleSyncDatasets.length} on:click={toggleAllSyncDatasets}>
                                            {allEligibleSyncDatasetsSelected ? 'Deselect all' : 'Select all'}
                                        </button>
                                    </legend>
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
                        <span>{scopeSeasons.length} {subjectType === 'player' && selectedPlayer ? 'player seasons available' : 'seasons available'}</span></div>
                    <div class="scope-controls">
                        {#if (analysisOptions?.subject_types?.length ?? 0) > 1}
                            <div class="subject-toggle" role="group" aria-label="Analysis subject">
                                <span>Analyze</span>
                                <button type="button" class:active={subjectType === 'team'} on:click={() => selectSubjectType('team')}>Team</button>
                                <button type="button" class:active={subjectType === 'player'} on:click={() => selectSubjectType('player')}>Player</button>
                            </div>
                        {/if}
                        {#if subjectType === 'player'}
                            <div class="team-control">
                                <label for="sport-player">Player</label>
                                <div class="team-combobox">
                                    <input id="sport-player" role="combobox" bind:value={playerInput} aria-label="Player"
                                           aria-expanded={playerComboboxOpen}
                                           aria-controls="sport-player-options"
                                           aria-autocomplete="list"
                                           aria-activedescendant={playerComboboxOpen && filteredPlayers[activePlayerIndex] ? `player-option-${filteredPlayers[activePlayerIndex].player_id}` : undefined}
                                           aria-invalid={Boolean(playerInput && !selectedPlayerId)} autocomplete="off" placeholder="Search Players…"
                                           on:focus={openPlayerCombobox}
                                           on:input={updatePlayerFilter} on:keydown={handlePlayerKeydown} on:blur={() => playerComboboxOpen = false}/>
                                    <button class="combobox-toggle" type="button" aria-label={`Show ${activeSport.toUpperCase()} players`} tabindex="-1"
                                            on:mousedown|preventDefault={() => playerComboboxOpen = !playerComboboxOpen}>
                                        <Icon name="chevron-down" size={17}/>
                                    </button>
                                    {#if playerComboboxOpen}
                                        <div class="team-options" id="sport-player-options" role="listbox" aria-label={`${activeSport.toUpperCase()} players`}>
                                            {#each filteredPlayers as player, index}
                                                <button id={`player-option-${player.player_id}`} type="button" role="option" aria-selected={selectedPlayerId === player.player_id}
                                                        class:active={index === activePlayerIndex} on:mousedown|preventDefault={() => selectPlayer(player)}
                                                        on:mouseenter={() => activePlayerIndex = index}>
                                                    <span>{player.name}{player.positions.length ? ` · ${player.positions.join('/')}` : ''}</span>
                                                    <b>{player.teams.join('/')}</b>
                                                </button>
                                            {:else}
                                                <div class="no-team-results">No players match “{playerFilter}”</div>
                                            {/each}
                                        </div>
                                    {/if}
                                </div>
                                {#if playerInput && !selectedPlayerId}<small class="validation">Choose a player from the list.</small>{/if}
                            </div>
                            {#if selectedPlayer?.teams.length}
                                <label>Team stint <select bind:value={playerTeamId}>
                                    <option value="">All teams in window</option>
                                    {#each selectedPlayer.teams as playerTeam}
                                        <option value={playerTeam}>{playerTeam}</option>
                                    {/each}
                                </select></label>
                            {/if}
                        {:else}
                            <div class="team-control">
                                <label for="sport-team">Team</label>
                                <div class="team-combobox">
                                    <input id="sport-team" role="combobox" bind:value={teamInput} aria-label={`${activeSport.toUpperCase()} team`}
                                           aria-expanded={teamComboboxOpen}
                                           aria-controls="sport-team-options"
                                           aria-autocomplete="list"
                                           aria-activedescendant={teamComboboxOpen && filteredTeams[activeTeamIndex] ? `team-option-${filteredTeams[activeTeamIndex].value}` : undefined}
                                           aria-invalid={Boolean(teamInput && !resolvedTeam)} autocomplete="off" placeholder="Search Teams…"
                                           on:focus={openTeamCombobox}
                                           on:input={updateTeamFilter} on:keydown={handleTeamKeydown} on:blur={() => teamComboboxOpen = false}/>
                                    <button class="combobox-toggle" type="button" aria-label={`Show ${activeSport.toUpperCase()} teams`} tabindex="-1"
                                            on:mousedown|preventDefault={() => teamComboboxOpen = !teamComboboxOpen}>
                                        <Icon name="chevron-down" size={17}/>
                                    </button>
                                    {#if teamComboboxOpen}
                                        <div class="team-options" id="sport-team-options" role="listbox" aria-label={`${activeSport.toUpperCase()} teams`}>
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
                        {/if}
                        <label>Comparison design
                            <select bind:value={comparisonMode}>
                                {#each analysisOptions?.comparison_windows ?? [] as option}
                                    <option value={option.value}
                                            disabled={option.value === 'full_seasons' && scopeSeasons.length < 2}>{option.label}</option>
                                {/each}
                            </select>
                        </label>
                        {#if activeSport === 'nfl'}<label>Season type
                            <select bind:value={seasonType}>
                                <option value="REG">Regular season</option>
                                <option value="POST">Postseason</option>
                                <option value="ALL">All games</option>
                            </select>
                        </label>{/if}
                    </div>

                    {#if scopeSeasons.length}
                        {#if activeSport === 'nba'}
                            <div class="window-grid">
                                <fieldset>
                                    <legend>{comparisonMode === 'full_seasons' ? 'Range start' : 'Baseline segment'}</legend>
                                    <label>Season<select bind:value={baseline} on:change={() => {
                                        if (comparisonMode === 'before_after_milestone') comparison = baseline;
                                        if (!availableSegments(baseline).some(segment => segment.value === baselineSegment)) baselineSegment = availableSegments(baseline)[0]?.value ?? 'regular_season';
                                    }}>
                                        {#each scopeSeasons as season}
                                            <option value={season}>{seasonLabel(season)}</option>
                                        {/each}
                                    </select></label>
                                    {#if comparisonMode === 'season_segments'}
                                        <label>Segment<select bind:value={baselineSegment}>
                                            {#each availableSegments(baseline) as segment}
                                                <option value={segment.value}>{segment.label}</option>
                                            {/each}
                                        </select></label>
                                    {:else if comparisonMode === 'before_after_milestone'}
                                        <div class="window-summary"><span>Before milestone</span><strong>Pre-All-Star</strong></div>
                                    {/if}
                                </fieldset>
                                <span class="arrow"><Icon name="arrow-right" size={19}/></span>
                                <fieldset>
                                    <legend>{comparisonMode === 'full_seasons' ? 'Range end' : 'Comparison segment'}</legend>
                                    <label>Season<select bind:value={comparison} disabled={comparisonMode === 'before_after_milestone'}>
                                        {#each scopeSeasons as season}
                                            <option value={season}>{seasonLabel(season)}</option>
                                        {/each}
                                    </select></label>
                                    {#if comparisonMode === 'season_segments'}
                                        <label>Segment<select bind:value={comparisonSegment}>
                                            {#each availableSegments(comparison) as segment}
                                                <option value={segment.value}>{segment.label}</option>
                                            {/each}
                                        </select></label>
                                    {:else if comparisonMode === 'before_after_milestone'}
                                        <div class="window-summary"><span>After milestone</span><strong>Post-All-Star</strong></div>
                                    {/if}
                                </fieldset>
                            </div>
                            {#if comparisonMode === 'full_seasons' && windowsDiffer}
                                <p class="range-summary">Includes every NBA season from {seasonLabel(baseline)} through {seasonLabel(comparison)}.</p>
                            {/if}
                        {:else if comparisonMode === 'before_after'}
                            <div class="window-grid before-after">
                                <label>Season<select bind:value={baseline}>
                                    {#each scopeSeasons as season}
                                        <option value={season}>{seasonLabel(season)}</option>
                                    {/each}
                                </select></label>
                                <label>First week after split<select bind:value={splitWeek}>
                                    {#each (analysisOptions?.week_values ?? []).filter((week) => week > 1) as week}
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
                                        {#each scopeSeasons as season}
                                            <option value={season}>{seasonLabel(season)}</option>
                                        {/each}
                                    </select></label>
                                    {#if comparisonMode === 'week_ranges'}
                                        <div class="week-pair"><label>Start<select bind:value={baselineStartWeek}>
                                            {#each analysisOptions?.week_values ?? [] as week}
                                                <option value={week} disabled={week > baselineEndWeek}>W{week}</option>
                                            {/each}
                                        </select></label><label>End<select bind:value={baselineEndWeek}>
                                            {#each analysisOptions?.week_values ?? [] as week}
                                                <option value={week} disabled={week < baselineStartWeek}>W{week}</option>
                                            {/each}
                                        </select></label></div>
                                    {/if}
                                </fieldset>
                                <span class="arrow"><Icon name="arrow-right" size={19}/></span>
                                <fieldset>
                                    <legend>{comparisonMode === 'full_seasons' ? 'Range end' : 'Comparison window'}</legend>
                                    <label>{comparisonMode === 'full_seasons' ? 'Through season' : 'Season'}<select bind:value={comparison}>
                                        {#each scopeSeasons as season}
                                            <option value={season}>{seasonLabel(season)}</option>
                                        {/each}
                                    </select></label>
                                    {#if comparisonMode === 'week_ranges'}
                                        <div class="week-pair"><label>Start<select bind:value={comparisonStartWeek}>
                                            {#each analysisOptions?.week_values ?? [] as week}
                                                <option value={week} disabled={week > comparisonEndWeek}>W{week}</option>
                                            {/each}
                                        </select></label><label>End<select bind:value={comparisonEndWeek}>
                                            {#each analysisOptions?.week_values ?? [] as week}
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
                                <p class="validation">Sync the missing season{missingRequiredSeasons.length === 1 ? '' : 's'} before running this
                                    range: {missingRequiredSeasons.join(', ')}.</p>
                            {/if}
                            {#if windowsDiffer && missingPlayerSeasons.length}
                                <p class="validation">The selected player has no recorded data for season{missingPlayerSeasons.length === 1 ? '' : 's'}
                                    {missingPlayerSeasons.join(', ')}. Choose a continuous range from the available player seasons.</p>
                            {/if}
                        {/if}
                    {:else}
                        <p class="empty-state">{subjectType === 'player' && selectedPlayer
                            ? 'No locally synced seasons overlap this player’s recorded career.'
                            : `Sync at least one ${activeSport === 'nba' ? 'SportsDataverse NBA' : 'nflverse'} season to configure an investigation.`}</p>
                    {/if}
                </section>

                <section class="metric-card" aria-labelledby="metric-heading">
                    <div class="scope-heading">
                        <div><span class="eyebrow">02 · METRICS</span>
                            <h3 id="metric-heading">Choose {subjectType === 'player' ? 'player metrics' : 'what to measure'}</h3></div>
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
                        {#each visibleDomains as domain}
                            <button type="button" class:active={analysisDomain === domain.value} aria-pressed={analysisDomain === domain.value}
                                    on:click={() => selectAnalysisDomain(domain.value)}>
                                <strong>{domain.label}</strong><span>{domain.description}</span>
                            </button>
                        {/each}
                    </div>
                    <p class="section-help"><strong>{subjectType === 'player' ? 'Only player-compatible metrics are shown.' : 'Recommended metrics are selected by default.'}</strong>
                        Checked metrics are included and unchecked metrics are excluded. Use Recommended Metrics replaces the current selection with the recommended set.</p>
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
                    {#if activeSport === 'nfl' && subjectType === 'player'}
                        <div class="split-selector player-diagnostic-note">
                            <div><h4>Player Context</h4>
                                <p>Player comparisons use attributed plays plus compatible synced player statistics. Team-oriented diagnostic cuts are disabled for player investigations.</p></div>
                        </div>
                    {:else}
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
                    {/if}
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
                    <p>{activeSport === 'nba' ? 'Box-score efficiency, shot mix, player usage, lineups, and possession context' : 'EPA, success, explosives, pressure outcomes, and situational splits'}
                        run through tested tools.</p></article>
                <article><span>02</span>
                    <h3>Interpretation Marked</h3>
                    <p>{activeSport === 'nba' ? 'Basketball' : 'Football'} judgment stays distinct from measured claims without losing its analytical edge.</p>
                </article>
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
                    <div class="play-visual" class:nba-loading={activeSport === 'nba'} aria-hidden="true">
                        <div class="play-caption"><span>{activeSport === 'nba' ? 'LIVE ANALYSIS POSSESSION' : 'LIVE ANALYSIS DRIVE'}</span><b>{Math.round(progress * 100)}%</b></div>
                        {#if activeSport === 'nba'}
                            <BasketballLoadingAnimation/>
                        {:else}
                            <img class="catch-scene" src="/open-sports-analyst-loader.svg" alt=""/>
                        {/if}
                        <div class="analysis-live"><i></i><span>Analysis still running...</span></div>
                    </div>
                </div>
            </section>
        {:else if active}
            <section class="conversation" aria-label="Investigation conversation">
                <div class="conversation-header">
                    <div><span class="eyebrow">INVESTIGATION THREAD</span>
                        <h2>{investigationSubject(active)} Film Room</h2>
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
                        <span>{investigationSubject(active)}</span>
                        <span>{displayDomain(active.run.analysis_domain)}</span>
                        <span>{investigationWindow(active)}</span>
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
                                        <dt>Change / value</dt>
                                        <dd>{evidence.value ?? evidence.epa ?? evidence.metric_value}</dd>
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
                            <Chart specification={chart.specification} team={active.run.subject?.team_id ?? active.run.scope.team}
                                   sport={active.run.sport ?? 'nfl'}/>
                        </article>
                    {/each}
                </div>
            </section>
            <section class="plays">
                <div class="section-title"><span>REPRESENTATIVE {activeSport === 'nba' ? 'POSSESSIONS' : 'PLAYS'}</span><small>Support & Counterexamples</small>
                </div>
                <div class="play-list">
                    {#each active.play_evidence as play}
                        <button class:selected={selectedPlay?.evidence_id === play.evidence_id} aria-expanded={selectedPlay?.evidence_id === play.evidence_id}
                                on:click={() => openPlay(play)}><span class="play-tag"
                                                                      class:supporting={play.supporting}>{play.supporting ? 'support' : 'counter'}</span><strong>{play.game_id}
                            · #{play.play_id}</strong>
                            <p>{play.description}</p><b
                                class="play-epa">{play.epa != null ? `${play.epa.toFixed(2)} EPA` : play.metric_value != null ? `${play.metric_value.toFixed(1)} value` : 'Play evidence'}</b>
                        </button>
                    {/each}
                </div>
                {#if selectedPlay}
                    {#if selectedPlay.visualization?.sport === 'nba'}
                        <BasketballPlayTablet play={selectedPlay} onclose={() => selectedPlay = null}/>
                    {:else}
                        <PlayTablet play={selectedPlay} onclose={() => selectedPlay = null}/>
                    {/if}
                {/if}
            </section>
        {/if}
    </main>
</div>

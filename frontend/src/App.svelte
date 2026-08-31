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
    type QuestionBank = Record<string, Record<'team' | 'player', Record<string, string[]>>>;
    const questionBanks: QuestionBank = {
        nfl: {
            team: {
                passing: [
                    "What drove the change in this offense's EPA per dropback: down-to-down success, completion performance, or explosive passes?",
                    "Did the passing game become consistently more efficient, or did a handful of explosive plays and outlier games drive the difference?",
                    "How did the offense's passing profile change in accuracy, success rate, and explosive-pass frequency?",
                    "When did the passing-efficiency trend meaningfully shift, and was that change sustained across the comparison window?",
                    "Which representative dropbacks best explain—and challenge—the overall passing-efficiency trend?"
                ],
                rushing: [
                    "What drove the change in this rushing attack's EPA per carry: success rate, yards per carry, or explosive-run frequency?",
                    "Did the run game improve by staying on schedule more often, or by generating more explosive gains?",
                    "Was the rushing change sustained across the full window, or concentrated in a few games?",
                    "How did the rushing attack's efficiency and consistency change from the baseline to the comparison period?",
                    "Which carries best illustrate the run game's positive and negative outcomes?"
                ],
                offense: [
                    "What drove the change in overall offensive EPA per play: efficiency, yards per play, or turnover rate?",
                    "Did the offense become better at sustaining successful plays, or was the difference mostly created by high-leverage gains?",
                    "How much of the offensive change came from play mix versus performance within the passing and rushing games?",
                    "Was the offense's improvement or decline broad-based across the window, or concentrated in a few games?",
                    "Which plays provide the clearest evidence for—and against—the overall offensive trend?"
                ]
            },
            player: {
                quarterback: [
                    "What drove the change in this quarterback's EPA per dropback: success rate, CPOE, or yards per dropback?",
                    "Did this quarterback become more consistently efficient, or did a few high-variance games drive the result?",
                    "How did this quarterback's accuracy relative to expectation translate into changes in overall passing efficiency?",
                    "When did this quarterback's performance trend shift, and was the change sustained?",
                    "Which dropbacks best represent—and contradict—this quarterback's overall performance trend?"
                ],
                receiving: [
                    "Did this receiver's production change because of target volume, catch rate, yards per target, or EPA per target?",
                    "How did this receiver's role and per-target efficiency change between the two windows?",
                    "Was this receiver's change sustained across the sample, or driven by a few high-volume or explosive games?",
                    "Did the receiver convert opportunities more efficiently even if target volume changed?",
                    "Which targets best illustrate the receiver's positive production and missed opportunities?"
                ],
                running: [
                    "Did this ball carrier's production change because of workload, EPA per carry, success rate, or yards per carry?",
                    "How did this runner's down-to-down efficiency change relative to the volume of carries received?",
                    "Was the rushing change consistent across games, or driven by a few large performances?",
                    "Did increased workload come with better efficiency, diminishing returns, or no meaningful change?",
                    "Which carries best represent the runner's efficiency trend and its counterexamples?"
                ]
            }
        },
        nba: {
            team: {
                offense: [
                    "What drove the change in this team's offensive rating: scoring volume, effective field-goal percentage, or turnover control?",
                    "Did the offense improve through better shot-making, cleaner possessions, or both?",
                    "Was the offensive change sustained across the season, or concentrated in a small number of games?",
                    "How did the team's scoring efficiency translate into changes in win percentage?",
                    "Which games best represent—and challenge—the overall offensive trend?"
                ],
                defense: [
                    "How did this team's defensive rating change, and how closely did that track with its win percentage?",
                    "Was the defensive improvement or decline sustained across the season, or driven by a few outlier games?",
                    "When did the team's defensive-efficiency trend meaningfully change?",
                    "Did the defense become more consistent from game to game, even if its average rating changed only modestly?",
                    "Which games provide the strongest evidence for—and against—the defensive trend?"
                ],
                shooting: [
                    "Was the change in team shooting efficiency driven by shot-making, three-point attempt rate, or both?",
                    "How did effective field-goal percentage and true shooting percentage move relative to the team's three-point mix?",
                    "Did the team generate a more efficient shot profile, or simply convert similar shots at a better rate?",
                    "Was the shooting change stable across the window or concentrated in hot and cold stretches?",
                    "Which games best illustrate the team's changing shooting profile?"
                ],
                playmaking: [
                    "Did the team's ball movement improve, based on assists per game and assist-to-turnover ratio?",
                    "Was the change in playmaking driven by creating more assisted baskets or by protecting possessions more effectively?",
                    "How consistently did the team generate assists without increasing turnovers?",
                    "When did the team's assist-to-turnover profile begin to change?",
                    "Which games best represent the team's strongest and weakest playmaking performances?"
                ],
                rebounding: [
                    "Did this team improve on the glass through total rebounding, offensive rebounding, or both?",
                    "How much did second-chance opportunity creation change between the two windows?",
                    "Was the rebounding change consistent across games or driven by a few dominant performances?",
                    "When did the team's rebounding trend shift during the season?",
                    "Which games best illustrate the team's rebounding strengths and weaknesses?"
                ],
                turnovers: [
                    "Did this team protect the ball more effectively, based on turnovers per game and turnover rate?",
                    "Was the change in turnovers proportional to the team's possession volume, or did its underlying ball security change?",
                    "How consistent was the team's turnover control across the comparison window?",
                    "When did the team's turnover profile begin to improve or deteriorate?",
                    "Which games had the greatest influence on the team's turnover trend?"
                ],
                lineups: [
                    "Which five-player units drove the change in net rating between these windows?",
                    "Did the team's best lineups improve through offense, defense, or both?",
                    "How concentrated was the team's performance among its most-used lineup combinations?",
                    "Which lineup changes produced the clearest gains or losses in efficiency?",
                    "Did the strongest lineup results persist across the full window or come from limited samples?"
                ]
            },
            player: {
                scoring: [
                    "Did this player's scoring change because of volume, true shooting efficiency, or both?",
                    "How efficiently did this player convert a changing scoring workload?",
                    "Was the scoring change sustained across games or driven by a few high-output performances?",
                    "When did this player's scoring trend meaningfully shift?",
                    "Which games best represent—and challenge—the player's overall scoring trend?"
                ],
                shooting: [
                    "Did this player's shooting efficiency change because of shot-making, three-point attempt rate, or both?",
                    "How did effective field-goal percentage and true shooting percentage move as the player's shot mix changed?",
                    "Did the player become a more efficient shooter, or simply take a different distribution of shots?",
                    "Was the shooting change sustained, or concentrated in hot and cold stretches?",
                    "Which games best illustrate the player's changing shooting profile?"
                ],
                playmaking: [
                    "Did this player's creation improve through more assists, better assist-to-turnover efficiency, or both?",
                    "How did this player's role as a primary or secondary creator change between the two windows?",
                    "Was the playmaking change consistent across games or driven by a few high-assist performances?",
                    "Did additional ball-handling responsibility produce better distribution without a comparable rise in turnovers?",
                    "Which games best represent the player's strongest and weakest playmaking performances?"
                ],
                rebounding: [
                    "Did this player's rebounding change through total activity, offensive-board production, or both?",
                    "How did this player's impact on second-chance opportunities change between the two windows?",
                    "Was the rebounding change sustained or driven by a few matchup-specific performances?",
                    "When did this player's rebounding trend begin to shift?",
                    "Which games best illustrate the player's work on the glass?"
                ],
                turnovers: [
                    "How did this player's turnover volume change between the two windows?",
                    "Was the change in ball security sustained across games or driven by a few high-turnover performances?",
                    "When did this player's turnover trend begin to improve or deteriorate?",
                    "Did the player's turnover burden change alongside a larger offensive role?",
                    "Which games had the greatest influence on the player's turnover trend?"
                ],
                usage: [
                    "How did this player's offensive role change in minutes and usage proxy between the two windows?",
                    "Did a larger role come from more playing time, more involvement per minute, or both?",
                    "Was the player's increased usage sustained across the sample or concentrated in specific stretches?",
                    "When did this player's rotation role and offensive involvement begin to change?",
                    "Did the player's workload expand without a comparable change in minutes?"
                ],
                impact: [
                    "How did this player's plus/minus impact change, and what does the lineup context suggest about that shift?",
                    "Was the player's impact trend sustained across the window or driven by a few extreme games?",
                    "Did the lineups featuring this player improve even when individual box-score production was stable?",
                    "When did this player's impact trend meaningfully change?",
                    "Which games and lineup contexts best explain the player's change in impact?"
                ],
                lineups: [
                    "Which five-player units best complemented this player between the two windows?",
                    "Did this player's most-used lineups improve through offense, defense, or both?",
                    "How dependent was the player's lineup impact on a small number of teammates or units?",
                    "Which lineup combinations produced the clearest gains or losses with this player on the floor?",
                    "Were the player's strongest lineup results supported by meaningful samples or limited minutes?"
                ]
            }
        }
    };
    const initialQuestion = questionBanks.nfl.team.passing[0];
    let question = initialQuestion;
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
    let playersLoading = false;
    let playerLoadError = '';
    let selectedPlayerId = '';
    let playerInput = '';
    let playerFilter = '';
    let playerComboboxOpen = false;
    let activePlayerIndex = 0;
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
    let investigationLoading = false;
    let deletingInvestigationId = '';
    let pendingFollowup = '';
    let workspaceRequestVersion = 0;
    let workspaceLoading = true;
    let workspaceLoadError = '';
    let backendReady = false;
    type DraftState = {
        question: string; team: string; teamInput: string; baseline: number; comparison: number;
        baselineStartWeek: number; baselineEndWeek: number; comparisonStartWeek: number; comparisonEndWeek: number;
        splitWeek: number; seasonType: 'REG' | 'POST' | 'ALL';
        comparisonMode: string; analysisDomain: string; subjectType: 'team' | 'player'; selectedPlayerId: string; playerInput: string;
        playerTeamId: string; baselineSegment: string; comparisonSegment: string; selectedMetrics: string[];
        selectedSplits: string[]; syncSeasons: number[]; syncDatasets: string[]; dataManagerOpen: boolean;
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
    $: playerNamesById = new Map(players.map((player) => [player.player_id, player.name]));
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

    onMount(() => {
        void refresh();
    });

    async function refresh(attempt = 0) {
        const sport = activeSport;
        const requestVersion = ++workspaceRequestVersion;
        workspaceLoading = true;
        workspaceLoadError = '';
        try {
            if (!backendReady) {
                if (!await api.ready()) throw new Error('The local analysis service is still starting.');
                backendReady = true;
            }
            const bootstrap = capabilities && sports.length
                ? Promise.resolve(null)
                : Promise.all([api.capabilities(), api.sports()]);
            const [[nextOptions, nextDatasets, nextHistory], nextBootstrap] = await Promise.all([
                Promise.all([
                    api.analysisOptions(sport),
                    api.datasets(sport),
                    api.investigations(undefined, 0, sport)
                ]),
                bootstrap
            ]);
            if (requestVersion !== workspaceRequestVersion || sport !== activeSport) return;
            if (nextBootstrap) {
                const [nextCapabilities, nextSports] = nextBootstrap;
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
            }
            analysisOptions = nextOptions;
            datasets = nextDatasets;
            history = nextHistory;
            initializeSelections();
            const unresolvedPlayerHistory = nextHistory.some((item) => item.run.subject?.type === 'player' && !item.run.subject.display_name);
            if (subjectType === 'player' || unresolvedPlayerHistory) void loadPlayers();
        } catch (problem) {
            if (requestVersion !== workspaceRequestVersion || sport !== activeSport) return;
            const startupAttempt = !backendReady;
            const retryLimit = startupAttempt ? 120 : 4;
            if (attempt < retryLimit) {
                workspaceLoadError = 'Waiting for the local analysis service…';
                const retryDelay = startupAttempt ? 500 : 500 * (attempt + 1);
                await new Promise((resolve) => setTimeout(resolve, retryDelay));
                if (requestVersion === workspaceRequestVersion && sport === activeSport) await refresh(attempt + 1);
                return;
            }
            workspaceLoadError = String(problem);
            error = workspaceLoadError;
        } finally {
            if (requestVersion === workspaceRequestVersion && sport === activeSport) workspaceLoading = false;
        }
    }

    async function switchSport(sport: string) {
        if (sport === activeSport || busy) return;
        sportDrafts[activeSport] = captureDraft();
        workspaceRequestVersion += 1;
        playerSearchVersion += 1;
        activeSport = sport;
        active = null;
        conversationThread = [];
        clearEvidenceSelection();
        analysisOptions = null;
        datasets = [];
        history = [];
        players = [];
        playersLoading = false;
        playerLoadError = '';
        error = '';
        resetDraft(sport);
        const draft = sportDrafts[sport];
        if (draft) {
            applyDraft(draft);
            initializedSelections = true;
        }
        await refresh();
    }

    function captureDraft(): DraftState {
        return {
            question, team, teamInput, baseline, comparison, baselineStartWeek, baselineEndWeek,
            comparisonStartWeek, comparisonEndWeek, splitWeek, seasonType, comparisonMode, analysisDomain, subjectType,
            selectedPlayerId, playerInput, playerTeamId, baselineSegment, comparisonSegment,
            selectedMetrics: [...selectedMetrics], selectedSplits: [...selectedSplits],
            syncSeasons: [...syncSeasons], syncDatasets: [...syncDatasets], dataManagerOpen
        };
    }

    function resetDraft(sport: string) {
        initializedSelections = false;
        team = '';
        teamInput = '';
        teamFilter = '';
        teamComboboxOpen = false;
        activeTeamIndex = 0;
        selectedPlayerId = '';
        playerInput = '';
        playerFilter = '';
        playerComboboxOpen = false;
        activePlayerIndex = 0;
        playerTeamId = '';
        baselineStartWeek = 1;
        baselineEndWeek = 18;
        comparisonStartWeek = 1;
        comparisonEndWeek = 18;
        splitWeek = 10;
        seasonType = 'REG';
        subjectType = 'team';
        analysisDomain = sport === 'nba' ? 'offense' : 'passing';
        comparisonMode = sport === 'nba' ? 'season_segments' : 'full_seasons';
        baselineSegment = 'regular_season';
        comparisonSegment = 'post_all_star';
        question = examplesFor(sport, subjectType, analysisDomain)[0];
        selectedMetrics = [];
        selectedSplits = [];
        syncSeasons = [];
        syncDatasets = ['play_by_play'];
        dataManagerOpen = true;
    }

    function applyDraft(draft: DraftState) {
        ({
            question, team, teamInput, baseline, comparison, baselineStartWeek, baselineEndWeek,
            comparisonStartWeek, comparisonEndWeek, splitWeek, seasonType, comparisonMode, analysisDomain, subjectType,
            selectedPlayerId, playerInput, playerTeamId, baselineSegment, comparisonSegment
        } = draft);
        selectedMetrics = [...draft.selectedMetrics];
        selectedSplits = [...draft.selectedSplits];
        syncSeasons = [...draft.syncSeasons];
        syncDatasets = [...draft.syncDatasets];
        dataManagerOpen = draft.dataManagerOpen;
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
            playerSearchVersion += 1;
            playersLoading = false;
            playerLoadError = '';
            selectedPlayerId = '';
            playerInput = '';
            playerTeamId = '';
        }
        selectedSplits = [];
        const nextDomain = (analysisOptions?.analysis_domains ?? []).find((domain) => domainAvailableForSubject(domain, type))?.value;
        if (nextDomain) selectAnalysisDomain(nextDomain, true);
        else selectedMetrics = [];
        if (type === 'player' && !players.length) void loadPlayers();
    }

    async function loadPlayers() {
        const sport = activeSport;
        const version = ++playerSearchVersion;
        playersLoading = true;
        playerLoadError = '';
        try {
            const matches = await api.players(sport);
            if (version === playerSearchVersion && sport === activeSport) players = matches;
        } catch (problem) {
            if (version === playerSearchVersion && sport === activeSport) playerLoadError = String(problem);
        } finally {
            if (version === playerSearchVersion && sport === activeSport) playersLoading = false;
        }
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
    }

    function selectPlayer(player: PlayerOption) {
        playerSearchVersion += 1;
        playersLoading = false;
        playerLoadError = '';
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

    function examplesFor(sport = activeSport, type = subjectType, domain = analysisDomain) {
        return questionBanks[sport]?.[type]?.[domain] ?? [initialQuestion];
    }

    function isCuratedExample(value: string) {
        return Object.values(questionBanks).some((sport) =>
            Object.values(sport).some((subject) => Object.values(subject).some((examples) => examples.includes(value)))
        );
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
        if (isCuratedExample(question)) {
            question = examplesFor(activeSport, subjectType, domain)[0];
        }
        if (selectedPlayer) normalizePlayerSeasonSelection(selectedPlayer);
    }

    function selectAllMetrics() {
        selectedMetrics = availableMetrics.map((metric) => metric.value);
    }

    function showAnotherExample() {
        const examples = examplesFor();
        const alternatives = examples.filter((example) => example !== question);
        question = alternatives[Math.floor(Math.random() * alternatives.length)] ?? examples[0] ?? initialQuestion;
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

    function investigationSubject(item: Investigation | InvestigationSummary, playerNames = playerNamesById) {
        const subject = item.run.subject;
        if (subject?.type === 'player') {
            return subject.display_name || playerNames.get(subject.id) || subject.id;
        }
        return subject?.display_name || subject?.id || item.run.scope.team;
    }

    function investigationSubjectInitials(item: Investigation | InvestigationSummary, playerNames = playerNamesById) {
        const label = investigationSubject(item, playerNames).trim();
        const words = label.split(/\s+/).filter(Boolean);
        if (words.length > 1) return `${words[0][0]}${words[words.length - 1][0]}`.toUpperCase();
        return label.slice(0, 3).toUpperCase();
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
                    ...(subjectType === 'player' && selectedPlayer ? {display_name: selectedPlayer.name} : {}),
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
            investigationLoading = false;
            active = null;
            conversationThread = [];
            return;
        }
        investigationLoading = true;
        try {
            active = 'claims' in investigation
                ? investigation
                : await api.investigation(investigation.run.investigation_id);
            conversationThread = await api.investigationThread(active.run.investigation_id);
        } catch (problem) {
            error = String(problem);
        } finally {
            investigationLoading = false;
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
        if (!window.confirm(`Delete the saved ${investigationSubject(item, playerNamesById)} analysis? This cannot be undone.`)) return;
        deletingInvestigationId = identifier;
        try {
            const deletedRoot = rootIdFor(item);
            await api.deleteInvestigation(identifier);
            history = history.filter((saved) => rootIdFor(saved) !== deletedRoot);
            if (active && rootIdFor(active) === deletedRoot) {
                await openInvestigation(null);
            }
        } catch (problem) {
            error = String(problem);
        } finally {
            deletingInvestigationId = '';
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
                        <span class="recent-subject-badge" title={investigationSubject(item, playerNamesById)}>{investigationSubjectInitials(item, playerNamesById)}</span>
                        <div><strong class="recent-subject-name">{investigationSubject(item, playerNamesById)}</strong>
                            <span class="recent-question">{item.run.question}</span>
                            <small>{investigationWindow(item)}</small>
                            {#if threadFor(item).length > 1}<small class="thread-count">{threadFor(item).length - 1}
                                follow-up{threadFor(item).length === 2 ? '' : 's'}</small>{/if}
                        </div>
                    </button>
                    <button class="delete-report" type="button" aria-label={`Delete investigation thread: ${item.run.question}`} title="Delete investigation thread"
                            disabled={deletingInvestigationId === item.run.investigation_id}
                            on:click={() => deleteInvestigation(item)}>
                        {#if deletingInvestigationId === item.run.investigation_id}<span class="button-spinner" aria-label="Deleting investigation"></span>{:else}<Icon name="trash" size={16}/>{/if}
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
                <h1>{active ? `${investigationSubject(active, playerNamesById)} investigation` : `Analyze and Discuss ${activeSport === 'nba' ? 'Basketball' : 'Football'} Play-by-Play Data!`}</h1>
            </div>
            <div class="status-chip">
                <Icon name="database" size={16}/>{indexedSeasonCount} seasons · {datasets.length} data packages
            </div>
        </header>

        {#if error}
            <div class="error" role="alert">{error}</div>
        {/if}

        {#if investigationLoading}
            <section class="page-operation-loading" role="status" aria-live="polite" aria-busy="true">
                <span class="library-spinner" aria-hidden="true"></span>
                <div><strong>Loading saved investigation</strong><small>Retrieving its conversation, report, and evidence references…</small></div>
            </section>
        {:else if !active && !busy}
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
                            <span><strong>Manage Local {activeSport === 'nba' ? 'SportsDataverse NBA' : 'nflverse'} Data</strong><small>Choose the seasons and packages to load for your investigations.</small></span><b>{workspaceLoading ? 'Loading data…' : `${datasets.length} local files`} <i>
                                <Icon name="chevron-down" size={16}/>
                            </i></b></summary>
                        <div class="onboarding">
                            <div class="sync-guidance"><strong>Local Data Library</strong><span>Play-by-play is required. Package checkboxes choose what to sync next; coverage is calculated for the selected seasons, and “not offered” means those seasons predate that package.</span>
                            </div>
                            {#if workspaceLoading}
                                <div class="library-loading" role="status" aria-live="polite">
                                    <span class="library-spinner" aria-hidden="true"></span>
                                    <span><strong>Loading data catalog</strong><small>{workspaceLoadError || 'Checking available seasons, packages, and local file coverage…'}</small></span>
                                </div>
                                <div class="library-skeleton" aria-hidden="true">
                                    <div><span class="skeleton-label"></span><span class="skeleton-block"></span></div>
                                    <div><span class="skeleton-label wide"></span><span class="skeleton-row"></span><span class="skeleton-row short"></span></div>
                                </div>
                            {:else if !analysisOptions}
                                <div class="library-load-error" role="alert">
                                    <span><strong>Data catalog unavailable</strong><small>The local analysis service did not respond. Start the API or try loading the catalog again.</small></span>
                                    <button type="button" on:click={() => refresh()}>Retry</button>
                                </div>
                            {:else}
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
                            {/if}
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
                                           aria-busy={playersLoading}
                                           aria-controls="sport-player-options"
                                           aria-autocomplete="list"
                                           aria-activedescendant={playerComboboxOpen && filteredPlayers[activePlayerIndex] ? `player-option-${filteredPlayers[activePlayerIndex].player_id}` : undefined}
                                           aria-invalid={Boolean(playerInput && !selectedPlayerId)} autocomplete="off" placeholder="Search Players…"
                                           on:focus={openPlayerCombobox}
                                           on:input={updatePlayerFilter} on:keydown={handlePlayerKeydown} on:blur={() => playerComboboxOpen = false}/>
                                    <button class="combobox-toggle" type="button" aria-label={`Show ${activeSport.toUpperCase()} players`} tabindex="-1"
                                            on:mousedown|preventDefault={() => playerComboboxOpen = !playerComboboxOpen}>
                                        {#if playersLoading}<span class="button-spinner" aria-hidden="true"></span>{:else}<Icon name="chevron-down" size={17}/>{/if}
                                    </button>
                                    {#if playerComboboxOpen}
                                        <div class="team-options" id="sport-player-options" role="listbox" aria-label={`${activeSport.toUpperCase()} players`}>
                                            {#if playersLoading}
                                                <div class="combobox-loading" role="status"><span class="button-spinner" aria-hidden="true"></span>
                                                    <span>Loading {activeSport.toUpperCase()} players…</span></div>
                                            {:else if playerLoadError}
                                                <div class="combobox-error"><span>Player list is unavailable.</span><button type="button" on:mousedown|preventDefault={() => loadPlayers()}>Retry</button></div>
                                            {:else}
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
                                            {/if}
                                        </div>
                                    {/if}
                                </div>
                                {#if playerInput && !selectedPlayerId && !playersLoading}<small class="validation">Choose a player from the list.</small>{/if}
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
                        <h2>{investigationSubject(active, playerNamesById)} Film Room</h2>
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
                        <span>{investigationSubject(active, playerNamesById)}</span>
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

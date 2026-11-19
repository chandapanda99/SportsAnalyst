<script lang="ts">
  import {onMount, tick} from 'svelte';
  import {api, pendingJob, pollingStream} from './api';
  import type {EventStreamResponse} from './api';
  import AnalysisBrief from './AnalysisBrief.svelte';
  import AnalysisProgress from './AnalysisProgress.svelte';
  import DataManager from './DataManager.svelte';
  import FilmRoomRail from './FilmRoomRail.svelte';
  import GettingStartedGuide from './GettingStartedGuide.svelte';
  import MetricStep from './MetricStep.svelte';
  import QuestionStep from './QuestionStep.svelte';
  import ReportView from './ReportView.svelte';
  import SubjectStep from './SubjectStep.svelte';
  import TimeFrameStep from './TimeFrameStep.svelte';
  import type {DownloadSelection} from './types';
  import Icon from './Icon.svelte';
  import ModelSettingsDialog from './ModelSettingsDialog.svelte';
  import CompletionToast from './CompletionToast.svelte';
  import {MAX_HEAD_TO_HEAD_SEASONS} from './analysisScope';
  import {datasetLabel as packageLabel} from './datasetLabels';
  import {expandedQuestions} from './expandedQuestions';
  import {initializeBranding} from './sportsBranding';
  import {questionBanks, supplementalQuestionBanks} from './questionCatalog';
  import {keyMetrics} from './reportHelpers';
  import type {PrefetchedEvidence} from './reportHelpers';
  import {rootIdFor} from './reportThreads';
  import {revealPanel} from './revealPanel';
  import type {
    AnalysisOptions,
    Capabilities,
    DatasetManifest,
    Investigation,
    InvestigationSummary,
    MetricExplanation,
    MetricOption,
    PlayerOption,
    SportOption,
    TeamOption
  } from './types';

  const sportLogos: Record<string, string> = {
    nfl: '/NFL/NFL-Logo.png',
    nba: '/NBA/NBA-Logo.png',
    soccer: '/Soccer/Soccer-Ball.png',
    cfb: '/CFB/ncaa-logo.png'
  };
  class RunCancelled extends Error {}

  function problemMessage(problem: unknown) {
    return problem instanceof Error ? problem.message : String(problem);
  }

  const providerLabels: Record<string, string> = {azure_foundry: 'Azure AI Foundry', ollama: 'Ollama'};
  let capabilities: Capabilities | null = null;
  let modelSettingsOpen = false;
  let modelChecking = false;
  let modelCheckError = '';
  // The rail indicator's state: ready, connecting, error or not configured (offline while the service is down).
  $: modelState = modelChecking || (!capabilities && !serviceOffline) ? 'connecting'
    : !capabilities ? 'offline'
      : modelCheckError ? 'error'
        : capabilities.model_configured ? 'ready' : 'unconfigured';
  $: modelTitle = capabilities?.configured_provider ? providerLabels[capabilities.configured_provider] ?? capabilities.configured_provider
    : serviceOffline ? 'Not connected' : 'Connecting…';
  $: modelDetail = modelState === 'connecting' ? (capabilities ? 'Checking connection…' : 'Loading')
    : modelState === 'offline' ? 'Service offline'
      : modelState === 'error' ? 'Connection check failed'
        : modelState === 'ready' ? 'AI model ready' : 'No AI model set up';
  let completionNotifications: Array<{ id: number; title: string; message: string }> = [];
  let nextNotificationId = 0;

  function notifyCompletion(title: string, message: string) {
    completionNotifications = [...completionNotifications.slice(-2), {id: ++nextNotificationId, title, message}];
  }

  function dismissCompletion(id: number) {
    completionNotifications = completionNotifications.filter(item => item.id !== id);
  }

  let sports: SportOption[] = [];
  let activeSport = 'nfl';
  const soccerCompetitions = [
    {value: 'eng.1', label: 'Premier League', calendar: false},
    {value: 'usa.1', label: 'MLS', calendar: true},
    {value: 'esp.1', label: 'La Liga', calendar: false},
    {value: 'ger.1', label: 'Bundesliga', calendar: false},
    {value: 'ita.1', label: 'Serie A', calendar: false},
    {value: 'fra.1', label: 'Ligue 1', calendar: false},
    {value: 'usa.nwsl', label: 'NWSL', calendar: true},
    {value: 'uefa.champions', label: 'UEFA Champions League', calendar: false}
  ];
  let selectedCompetition = 'eng.1';
  let baselineStartDate = '';
  let baselineEndDate = '';
  let comparisonStartDate = '';
  let comparisonEndDate = '';
  let analysisOptions: AnalysisOptions | null = null;
  let datasets: DatasetManifest[] = [];
  let history: InvestigationSummary[] = [];
  let active: Investigation | null = null;
  let conversationThread: Investigation[] = [];
  let appShellElement: HTMLDivElement | null = null;
  let railWidth = 300;

  const initialQuestion = questionBanks.nfl.team.passing[0];
  let question = '';
  let lastSuggestedQuestion = '';
  let questionExamples = questionBanks.nfl.team.passing;
  let showAllQuestionExamples = false;
  let previousQuestionContext = '';
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
  let comparisonSegment = 'regular_season';
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
  let cfbBrowseSeason = 2025;
  let cfbSubdivision = 'fbs';
  let cfbConference = '';
  let cfbConferenceLabel = '';
  let cfbLoading = false;
  let cfbError = '';
  let cfbHistoryLoading = false;
  let cfbSeasons: number[] = [];
  let cfbTeams: Array<{ value: string; label: string }> = [];
  let cfbSearchTimer: ReturnType<typeof setTimeout>;
  // The downloaded player list is capped, so typed searches also ask the server and merge in its matches.
  let searchedPlayers: PlayerOption[] = [];
  let playerSearching = false;
  let playerQueryVersion = 0;
  let playerQueryTimer: ReturnType<typeof setTimeout>;
  let scopeSeasons: number[] = [];
  let seasonType: 'REG' | 'POST' | 'ALL' = 'REG';
  let selectedMetrics: string[] = [];
  let selectedSplits: string[] = [];
  let syncSeasons: number[] = [];
  let downloadScope: DownloadSelection = {kind: 'league', ready: true, label: 'Entire League'};
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
  const desktopMode = new URLSearchParams(window.location.search).has('desktop');
  let initialWorkspaceReady = false;
  let initialWorkspaceError = '';
  let startupStatus = 'Connecting to the local app…';
  let historyLoading = false;
  let historyLoadError = '';
  let historyRequestVersion = 0;
  type DraftState = {
    question: string; team: string; teamInput: string; baseline: number; comparison: number;
    baselineStartWeek: number; baselineEndWeek: number; comparisonStartWeek: number; comparisonEndWeek: number;
    splitWeek: number; seasonType: 'REG' | 'POST' | 'ALL';
    comparisonMode: string; analysisDomain: string; subjectType: 'team' | 'player'; selectedPlayerId: string; playerInput: string;
    playerTeamId: string; baselineSegment: string; comparisonSegment: string; selectedMetrics: string[];
    selectedSplits: string[]; syncSeasons: number[]; syncDatasets: string[]; dataManagerOpen: boolean;
    customizeSources: boolean; customizeMetrics: boolean; metricsEdited: boolean; compareSubjectId: string; headToHeadFirst: number;
    selectedCompetition: string; baselineStartDate: string; baselineEndDate: string; comparisonStartDate: string; comparisonEndDate: string;
  };
  const sportDrafts: Record<string, DraftState> = {};
  let showGuidance = true;
  let customizeSources = false;
  let customizeMetrics = false;
  let metricsEdited = false;
  let readinessKey = '';
  let syncComplete = false;
  let syncing = false;
  let mobileHistoryOpen = false;
  let metricDirections: Record<string, boolean | null> = {};
  let firstEvidence: PrefetchedEvidence | null = null;
  let metricInfo: MetricExplanation | null = null;
  let metricInfoError = '';
  let metricInfoLoading = false;
  let metricInfoVersion = 0;
  let metricInfoElement: HTMLElement | null = null;
  let metricInfoTrigger: HTMLElement | null = null;
  let showFullFilmRoom = false;
  // The desktop rail scrolls its list, so it lists every report; the stacked phone layout keeps the toggle.
  let railScrolls = false;
  let compareSubjectId = '';
  // Head-to-head runs from this season through `comparison`; 0 until the mode is chosen.
  let headToHeadFirst = 0;
  // College football picks the second subject by browsing to its school.
  let compareCfbTeams: TeamOption[] = [];
  let compareCfbSchool = '';
  let compareCfbSeason = 0;
  let comparePlayers: PlayerOption[] = [];
  let comparePlayersLoading = false;
  let comparePlayerVersion = 0;
  let runningInvestigationId = '';
  let cancelling = false;
  let routeHandled = false;
  let mainElement: HTMLElement | null = null;
  let progressHeading: HTMLElement | null = null;
  const offlineSports: SportOption[] = [['nfl', 'NFL'], ['nba', 'NBA'], ['soccer', 'Soccer'], ['cfb', 'College Football']]
      .map(([value, label]) => ({value, label, available: false, live_available: false}));
  $: setup = analysisOptions?.data_setup;
  $: serviceOffline = !backendReady && !workspaceLoading && Boolean(workspaceLoadError);
  $: sportTabs = sports.length || !serviceOffline ? sports : offlineSports;
  $: pageTitle = active ? `${investigationSubject(active, playerNamesById)} report · Open Sports Analyst` : 'Open Sports Analyst';
  $: requiredSources = (setup?.required_datasets?.length ? setup.required_datasets : ['play_by_play'])
      .filter(source => !(analysisOptions?.automatic_preparation && activeSport === 'nba'
          && source === (subjectType === 'player' ? 'team_boxscores' : 'player_boxscores')));
  $: suggestedSources = [...new Set([...requiredSources, ...(setup?.recommended_datasets ?? [])])];
  $: visibleSyncDatasets = customizeSources ? analysisOptions?.syncable_datasets ?? []
      : suggestedSources.filter(source => analysisOptions?.syncable_datasets.includes(source));
  $: sourceGaps = [...new Set(requiredSeasons)].flatMap(season => requiredSources.filter(source => !datasets.some(item => (item.sport ?? 'nfl') === activeSport && item.season === season && item.dataset === source && (activeSport !== 'soccer' || item.competition === selectedCompetition)
      && item.row_count !== 0 && item.availability !== 'source_unavailable'
      && (!item.partition_key || item.partition_key === `${subjectType}:${resolvedSubject}`
          || item.partition_key === `team:${resolvedTeam}`))).map(source => `${seasonLabel(season)} · ${datasetLabel(source)}`));
  $: dataReady = activeSport === 'cfb' ? Boolean(analysisOptions && resolvedTeam && !cfbLoading && !cfbError && !cfbHistoryLoading)
      : Boolean(analysisOptions && requiredSeasons.length && (analysisOptions.automatic_preparation || !sourceGaps.length));
  $: scopeDataSynced = dataReady && !sourceGaps.length;
  // Names the seasons the analysis will use, so the data header and the form refer to the same thing.
  $: analysisSpan = requiredSeasons.length
      ? seasonSpan(Math.min(...requiredSeasons), Math.max(...requiredSeasons)) : 'the selected seasons';
  $: dataStatusLabel = scopeDataSynced ? 'Data synced'
      : activeSport === 'cfb' && !resolvedTeam ? 'Choose a school to check its data'
          : dataReady ? 'Missing data will prepare when you run' : 'Sync required data';
  $: dataStatusDetail = activeSport === 'cfb' && !resolvedTeam ? 'Choose a school above to see the data this analysis needs.'
      : scopeDataSynced ? `Required data is ready for ${analysisSpan}.`
          : dataReady ? `${sourceGaps.length} required ${sourceGaps.length === 1 ? 'source is' : 'sources are'} not synced yet. Sync now, or anything missing prepares when you run the analysis.`
              : `Sync ${sourceGaps.length} required ${sourceGaps.length === 1 ? 'source' : 'sources'} to run this analysis.`;
  $: periodBlocker = !windowsDiffer
      ? headToHead ? periodStart > comparison ? 'Choose a first season on or before the last season'
          : `Head-to-head covers up to ${MAX_HEAD_TO_HEAD_SEASONS} seasons`
      : analysisDesign === 'full_seasons' ? 'Choose an end season after the start season' : 'Choose two different periods'
      : !hasSubjectData ? `${selectedPlayer?.name ?? 'This player'} has no recorded data for ${missingPlayerSeasons.map(seasonLabel).join(', ')}`
          : !hasRequiredData ? `Sync ${missingRequiredSeasons.map(seasonLabel).join(', ')} before running` : '';
  $: readinessSteps = [
    {ready: dataReady, label: dataStatusLabel, target: 'data-setup'},
    {
      ready: Boolean(resolvedSubject) && (!headToHead || Boolean(compareSubjectId)),
      label: !resolvedSubject ? 'Choose a team or player' : headToHead ? compareSubjectId ? 'Subjects selected' : 'Choose who to compare with' : 'Subject selected',
      target: 'scope-heading'
    },
    {ready: !periodBlocker, label: periodBlocker || (headToHead ? 'Seasons selected' : 'Time frame selected'), target: 'comparison-heading'},
    {
      ready: selectedAvailableMetricCount > 0,
      label: selectedAvailableMetricCount ? `${selectedAvailableMetricCount} metrics selected` : 'Choose at least one metric',
      target: 'metric-heading'
    },
    {ready: question.trim().length >= 3, label: question.trim().length >= 3 ? 'Question ready' : 'Add your question', target: 'investigation-question'}
  ];
  $: readiness = activeSport === 'cfb' ? [readinessSteps[1], readinessSteps[0], ...readinessSteps.slice(2)] : readinessSteps;
  $: firstBlocker = readiness.find(item => !item.ready);
  $: recommendedMetricIds = analysisOptions?.default_metrics_by_domain?.[analysisDomain] ?? analysisOptions?.default_metrics ?? [];
  $: periodBrief = draftPeriodBrief({
    activeSport,
    comparisonMode,
    baseline: periodStart,
    comparison,
    baselineSegment,
    comparisonSegment,
    splitWeek,
    baselineStartWeek,
    baselineEndWeek,
    comparisonStartWeek,
    comparisonEndWeek,
    baselineStartDate,
    baselineEndDate,
    comparisonStartDate,
    comparisonEndDate
  });
  $: if (!metricsEdited && analysisOptions) selectedMetrics = availableMetrics.filter(metric => recommendedMetricIds.includes(metric.value)).map(metric => metric.value);
  $: if (analysisOptions && !workspaceLoading) updateReadiness(`${activeSport}:${selectedCompetition}:${requiredSeasons.join(',')}:${sourceGaps.join(',')}`, scopeDataSynced);

  function updateReadiness(key: string, ready: boolean) {
    if (key === readinessKey) return;
    readinessKey = key;
    // Setup stays open until this scope is synced, then folds into its status line.
    if (!ready) dataManagerOpen = true;
    else if (!syncComplete) dataManagerOpen = false;
  }

  function dismissGuidance() {
    showGuidance = false;
    try {
      localStorage.setItem('sports-analyst:onboarding:v1', 'done');
    } catch { /* Storage is optional. */
    }
  }

  async function focusSection(id: string) {
    if (id === 'data-setup') dataManagerOpen = true;
    await tick();
    const element = document.getElementById(id);
    element?.focus({preventScroll: true});
    element?.scrollIntoView?.({block: 'center', behavior: 'auto'});
  }

  function sourceRole(source: string) {
    return requiredSources.includes(source) ? 'Required' : suggestedSources.includes(source) ? 'Recommended' : 'Optional enrichment';
  }

  function chooseQuickSetup() {
    customizeSources = false;
    syncDatasets = suggestedSources.filter(source => packageEligible(source));
  }

  async function explainMetric(metric: MetricOption) {
    const version = ++metricInfoVersion;
    metricInfo = null;
    metricInfoError = '';
    metricInfoLoading = true;
    metricInfoTrigger = document.activeElement as HTMLElement | null;
    void revealPanel(() => metricInfoElement, 'nearest');
    try {
      const response = await fetch(`/api/sports/${activeSport}/metrics/${encodeURIComponent(metric.value)}`);
      if (!response.ok) throw new Error('Metric explanation unavailable. Try again.');
      const definition = await response.json();
      if (version === metricInfoVersion) metricInfo = definition;
    } catch (problem) {
      if (version === metricInfoVersion) metricInfoError = problemMessage(problem);
    } finally {
      if (version === metricInfoVersion) metricInfoLoading = false;
    }
  }

  function closeMetricInfo() {
    metricInfoVersion += 1;
    metricInfo = null;
    metricInfoError = '';
    metricInfoLoading = false;
    metricInfoTrigger?.focus();
  }

  // Directions are fetched as soon as a report is chosen, so head-to-head leaders show when it opens.
  async function loadMetricDirections(result: Investigation) {
    const sport = result.run.sport ?? 'nfl';
    const missing = keyMetrics(result).map(item => item.metric ?? '').filter(metric => metric && !(`${sport}:${metric}` in metricDirections));
    await Promise.all(missing.map(async metric => {
      try {
        const response = await fetch(`/api/sports/${sport}/metrics/${encodeURIComponent(metric)}`);
        if (!response.ok) return;
        const definition = await response.json();
        metricDirections = {...metricDirections, [`${sport}:${metric}`]: definition.higher_is_better ?? null};
      } catch { /* The direction cue is optional. */
      }
    }));
  }

  $: if (active) void loadMetricDirections(active);

  // The first finding's evidence is requested while the report loads, so it opens with that evidence in place.
  function prefetchFirstEvidence(report: Investigation) {
    const claim = report.claims[0];
    if (!claim) {
      firstEvidence = null;
      return;
    }
    const request = api.evidenceBatch(report.run.investigation_id, claim.evidence_ids);
    request.catch(() => { /* The report shows the failure when it reads this request. */ });
    firstEvidence = {investigationId: report.run.investigation_id, claimId: claim.claim_id, request};
  }

  function draftPeriodBrief(context: {
    activeSport: string;
    comparisonMode: string;
    baseline: number;
    comparison: number;
    baselineSegment: string;
    comparisonSegment: string;
    splitWeek: number;
    baselineStartWeek: number;
    baselineEndWeek: number;
    comparisonStartWeek: number;
    comparisonEndWeek: number;
    baselineStartDate: string;
    baselineEndDate: string;
    comparisonStartDate: string;
    comparisonEndDate: string
  }) {
    const {
      activeSport,
      comparisonMode,
      baseline,
      comparison,
      baselineSegment,
      comparisonSegment,
      splitWeek,
      baselineStartWeek,
      baselineEndWeek,
      comparisonStartWeek,
      comparisonEndWeek,
      baselineStartDate,
      baselineEndDate,
      comparisonStartDate,
      comparisonEndDate
    } = context;
    if (comparisonMode === 'season_vs_prior') return `${seasonLabel(comparison)}, measured against ${seasonLabel(baseline)}`;
    if (comparisonMode === 'head_to_head') return `${seasonSpan(baseline, comparison)} · head-to-head`;
    if (comparisonMode === 'full_seasons') return `${seasonLabel(baseline)} → ${seasonLabel(comparison)} · every season in this range`;
    if (comparisonMode === 'before_after_milestone') return `${seasonLabel(baseline)} · before vs. after the All-Star break`;
    if (comparisonMode === 'before_after') return `${seasonLabel(baseline)} · weeks 1–${splitWeek - 1} vs. ${splitWeek}–22`;
    if (activeSport === 'soccer') return `${baselineStartDate}–${baselineEndDate} → ${comparisonStartDate}–${comparisonEndDate}`;
    if (activeSport === 'nba') return `${seasonLabel(baseline)} ${baselineSegment.replaceAll('_', ' ')} → ${seasonLabel(comparison)} ${comparisonSegment.replaceAll('_', ' ')}`;
    return `${baseline} weeks ${baselineStartWeek}–${baselineEndWeek} → ${comparison} weeks ${comparisonStartWeek}–${comparisonEndWeek}`;
  }

  const MODE_ORDER = ['full_seasons', 'season_vs_prior', 'week_ranges', 'date_ranges', 'season_segments', 'before_after', 'before_after_milestone'];
  function modeRank(value: string) {
    const rank = MODE_ORDER.indexOf(value);
    return rank < 0 ? MODE_ORDER.length : rank;
  }

  let timeFrameMode = 'full_seasons';
  function chooseHeadToHead(on: boolean) {
    if (on === headToHead) return;
    if (on) timeFrameMode = comparisonMode;
    comparisonMode = on ? 'head_to_head' : comparisonOptions.some(option => option.value === timeFrameMode) ? timeFrameMode : 'full_seasons';
  }

  function seasonSpan(first: number, last: number) {
    // Split-year labels ("2024–25") already contain a dash, so their range reads "2024–25 to 2025–26".
    const [start, end] = [seasonLabel(first), seasonLabel(last)];
    return first === last ? end : start.includes('–') ? `${start} to ${end}` : `${start}–${end}`;
  }

  // One season is reported against the season before it, as a two-season range.
  $: analysisDesign = comparisonMode === 'season_vs_prior' ? 'full_seasons' : comparisonMode;
  $: headToHead = comparisonMode === 'head_to_head';
  $: if (headToHead && !headToHeadFirst) headToHeadFirst = comparison;
  $: periodStart = comparisonMode === 'season_vs_prior' ? comparison - 1 : headToHead ? headToHeadFirst || comparison : baseline;
  // Every sport lists its time frames in the same order and wording; head-to-head is chosen in the Subject step.
  $: comparisonOptions = (analysisOptions?.comparison_windows ?? [])
      .filter(option => option.value !== 'head_to_head')
      .flatMap(option => option.value === 'full_seasons'
          ? [option, {value: 'season_vs_prior', label: 'One season vs. the season before', description: 'Analyze one season, using the season before it as the reference point.'}]
          : [option])
      .sort((left, right) => modeRank(left.value) - modeRank(right.value));
  $: headToHeadAvailable = (analysisOptions?.comparison_windows ?? []).some(option => option.value === 'head_to_head');
  $: currentSeason = analysisOptions?.current_season ?? null;
  $: requiredSeasons = headToHead
      ? periodStart <= comparison ? Array.from({length: comparison - periodStart + 1}, (_, index) => periodStart + index) : [comparison]
      : analysisDesign === 'before_after' || analysisDesign === 'before_after_milestone'
      ? [baseline]
      : analysisDesign === 'full_seasons' && periodStart < comparison
          ? Array.from({length: comparison - periodStart + 1}, (_, index) => periodStart + index)
          : [periodStart, comparison];
  $: resolvedTeam = resolveTeam(teamInput);
  $: knownPlayers = mergePlayers(players, searchedPlayers);
  $: selectedPlayer = knownPlayers.find((player) => player.player_id === selectedPlayerId) ?? null;
  $: {
    // Keep question cards reactive to every piece of context read by examplesFor.
    activeSport;
    subjectType;
    analysisDomain;
    selectedPlayer;
    resolvedTeam;
    analysisOptions;
    questionExamples = examplesFor(activeSport, subjectType, analysisDomain, selectedPlayer);
    const nextQuestionContext = [activeSport, subjectType, analysisDomain, selectedPlayer?.player_id ?? '', resolvedTeam].join(':');
    if (previousQuestionContext && nextQuestionContext !== previousQuestionContext) showAllQuestionExamples = false;
    previousQuestionContext = nextQuestionContext;
  }
  $: scopeSeasons = (() => {
    const local = [...new Set([...(analysisOptions?.available_seasons ?? []), ...(analysisOptions?.automatic_preparation ? analysisOptions.preparable_seasons ?? [] : [])])].sort((left, right) => right - left);
    if (subjectType !== 'player' || !selectedPlayer) return local;
    const played = new Set(playerSeasonsForDomain(selectedPlayer, analysisDomain, activeSport).map(Number));
    return local.filter((season) => played.has(season));
  })();
  $: resolvedSubject = subjectType === 'player' ? selectedPlayerId : resolvedTeam;
  $: filteredTeams = (analysisOptions?.teams ?? []).filter((option) => {
    const query = teamFilter.trim().toUpperCase();
    return !query || option.value.includes(query) || option.label.toUpperCase().includes(query);
  });
  $: filteredPlayers = knownPlayers.filter((player) => {
    const query = playerFilter.trim().toLowerCase();
    return !query || player.name.toLowerCase().includes(query) || player.player_id.toLowerCase().includes(query)
        || player.teams.some((value) => value.toLowerCase().includes(query));
  });
  $: playerNamesById = new Map(knownPlayers.map((player) => [player.player_id, player.name]));
  $: visibleDomains = (analysisOptions?.analysis_domains ?? []).filter((domain) => domainAvailableForSubject(domain, subjectType, selectedPlayer));
  $: windowsDiffer = headToHead ? periodStart <= comparison && comparison - periodStart < MAX_HEAD_TO_HEAD_SEASONS
      : analysisDesign === 'before_after' || analysisDesign === 'before_after_milestone'
      || (analysisDesign === 'full_seasons' ? periodStart < comparison : activeSport === 'nba'
          ? baseline !== comparison || baselineSegment !== comparisonSegment
          : ['soccer', 'cfb'].includes(activeSport) && comparisonMode === 'date_ranges'
              ? baseline !== comparison || baselineStartDate !== comparisonStartDate || baselineEndDate !== comparisonEndDate
              : baseline !== comparison
              || baselineStartWeek !== comparisonStartWeek
              || baselineEndWeek !== comparisonEndWeek);
  $: missingRequiredSeasons = requiredSeasons.filter((season) => !analysisOptions?.available_seasons.includes(season));
  $: hasRequiredData = requiredSeasons.every((season) => analysisOptions?.available_seasons.includes(season)
      || (analysisOptions?.automatic_preparation && analysisOptions.preparable_seasons?.includes(season)));
  $: missingPlayerSeasons = subjectType === 'player' && selectedPlayer
      ? requiredSeasons.filter((season) => !scopeSeasons.includes(season))
      : [];
  $: hasSubjectData = missingPlayerSeasons.length === 0;
  // Head-to-head candidates are the same kind of subject with recorded data in the chosen season.
  $: compareOptions = !headToHead ? [] : subjectType === 'team'
      ? (activeSport === 'cfb' ? compareCfbTeams : analysisOptions?.teams ?? []).filter(option => option.value !== resolvedTeam)
          .map(option => ({value: option.value, label: option.label, detail: activeSport === 'cfb' ? '' : option.value}))
      : (activeSport === 'cfb' ? comparePlayers : knownPlayers.filter(player => {
          const seasons = playerSeasonsForDomain(player).map(Number);
          return requiredSeasons.every(season => seasons.includes(season));
        })).filter(player => player.player_id !== selectedPlayerId)
          .map(player => ({value: player.player_id, label: player.name, detail: [player.positions.join('/'), player.teams.join('/')].filter(Boolean).join(' · ')}));
  $: if (compareSubjectId && compareOptions.length && !compareOptions.some(option => option.value === compareSubjectId)) compareSubjectId = '';
  $: compareSubjectLabel = compareOptions.find(option => option.value === compareSubjectId)?.label ?? '';
  $: canRun = Boolean(
      resolvedSubject && (!headToHead || compareSubjectId) && question.trim().length >= 3 && windowsDiffer && hasRequiredData && hasSubjectData
      && selectedAvailableMetricCount > 0 && dataReady
  );
  $: syncedSeasonCount = new Set(datasets.filter((dataset) => dataset.season > 0 && dataset.row_count !== 0).map((dataset) => dataset.season)).size;
  $: domainMetrics = (analysisOptions?.metrics ?? []).filter((metric) =>
      metric.analysis_domain === analysisDomain && (!metric.subject_types?.length || metric.subject_types.includes(subjectType))
  );
  $: metricCategories = [...new Set(domainMetrics.map((metric) => metric.category))];
  $: availableMetrics = domainMetrics.filter(metric => metricAvailable(metric, requiredSeasons, analysisOptions?.automatic_preparation)
      && !(activeSport === 'soccer' && metric.value.startsWith('season_') && analysisDesign !== 'full_seasons'));
  $: availableMetricIds = new Set(availableMetrics.map(metric => metric.value));
  $: selectedAvailableMetricCount = availableMetrics.filter((metric) => selectedMetrics.includes(metric.value)).length;
  $: allAvailableMetricsSelected = availableMetrics.length > 0 && selectedAvailableMetricCount === availableMetrics.length;
  $: eligibleSyncDatasets = syncSeasons.length
      ? (analysisOptions?.syncable_datasets ?? []).filter((dataset) => packageEligible(dataset, syncSeasons))
      : [];
  $: allEligibleSyncDatasetsSelected = eligibleSyncDatasets.length > 0
      && eligibleSyncDatasets.every((dataset) => syncDatasets.includes(dataset));
  $: rootHistory = history.filter((item) => !item.run.parent_investigation_id && (item.run.sport ?? 'nfl') === activeSport);

  onMount(() => {
    try {
      showGuidance = localStorage.getItem('sports-analyst:onboarding:v1') !== 'done';
    } catch { /* Storage is optional. */
    }
    const wideLayout = window.matchMedia?.('(min-width: 901px)');
    const followLayout = () => railScrolls = wideLayout?.matches ?? false;
    followLayout();
    wideLayout?.addEventListener?.('change', followLayout);
    const followRoute = () => void openRoute();
    window.addEventListener('popstate', followRoute);
    void refresh().then(async () => {
      const pending = pendingJob();
      if (!pending || busy) return;
      busy = true;
      syncing = pending.kind === 'sync';
      try {
        if (syncing) {
          await streamDatasetSync(pollingStream(pending));
          syncComplete = true;
          await refresh();
          notifyCompletion('Data Sync Complete', 'Your data library has been refreshed.');
        } else {
          await streamInvestigation(pollingStream(pending));
        }
      } catch (problem) {
        if (problem instanceof RunCancelled) notifyCompletion('Analysis Cancelled', 'The analysis was stopped.');
        else error = problemMessage(problem);
      } finally {
        busy = false;
        syncing = false;
      }
    });
    return () => {
      window.removeEventListener('popstate', followRoute);
      wideLayout?.removeEventListener?.('change', followLayout);
    };
  });

  async function refresh(attempt = 0) {
    const sport = activeSport;
    const requestVersion = ++workspaceRequestVersion;
    workspaceLoading = true;
    if (error === workspaceLoadError) error = '';
    workspaceLoadError = '';
    try {
      if (!backendReady) {
        if (!await api.ready()) throw new Error('The local analysis service is still starting.');
        backendReady = true;
      }
      const waiting = new Set<string>();

      function startupStep<T>(label: string, request: Promise<T>): Promise<T> {
        waiting.add(label);
        startupStatus = `Loading ${[...waiting].join(', ')}…`;
        return request.then(value => {
          waiting.delete(label);
          if (requestVersion === workspaceRequestVersion) startupStatus = waiting.size ? `Loading ${[...waiting].join(', ')}…` : 'Preparing your selections…';
          return value;
        }, problem => {
          throw new Error(`${label}: ${problem instanceof Error ? problem.message : String(problem)}`);
        });
      }

      const bootstrap = capabilities && sports.length
          ? Promise.resolve(null)
          : Promise.all([startupStep('analysis settings', api.capabilities()), startupStep('available sports', api.sports())]);
      const [[nextOptions, nextDatasets], nextBootstrap] = await Promise.all([
        Promise.all([
          startupStep('season and analysis options', api.analysisOptions(sport, sport === 'soccer' ? selectedCompetition : undefined)),
          startupStep('downloaded data catalog', api.datasets(sport))
        ]),
        bootstrap,
        startupStep('team branding', initializeBranding(sport))
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
      analysisOptions = sport === 'cfb' && cfbSeasons.length
          ? {
            ...nextOptions, available_seasons: cfbSeasons, syncable_seasons: cfbSeasons, teams: cfbTeams,
            metrics: nextOptions.metrics.map(metric => ({...metric, available_seasons: cfbSeasons}))
          } : nextOptions;
      datasets = sport === 'soccer' ? nextDatasets.filter(item => item.competition === selectedCompetition) : nextDatasets;
      initializeSelections();
      initialWorkspaceReady = true;
      initialWorkspaceError = '';
      void loadHistory();
      if (subjectType === 'player') void loadPlayers();
      if (!routeHandled) {
        routeHandled = true;
        if (!pendingJob()) void openRoute();
      }
    } catch (problem) {
      if (requestVersion !== workspaceRequestVersion || sport !== activeSport) return;
      const startupAttempt = !backendReady;
      const retryLimit = startupAttempt ? 5 : 0;
      if (attempt < retryLimit) {
        workspaceLoadError = 'Waiting for the local analysis service…';
        startupStatus = workspaceLoadError;
        const retryDelay = startupAttempt ? 500 : 500 * (attempt + 1);
        await new Promise((resolve) => setTimeout(resolve, retryDelay));
        if (requestVersion === workspaceRequestVersion && sport === activeSport) await refresh(attempt + 1);
        return;
      }
      workspaceLoadError = startupAttempt
          ? `The analysis service isn't running. ${desktopMode ? 'Restart Open Sports Analyst' : 'Start it'}, then try again.`
          : problemMessage(problem);
      error = workspaceLoadError;
      initialWorkspaceError = workspaceLoadError;
    } finally {
      if (requestVersion === workspaceRequestVersion && sport === activeSport) workspaceLoading = false;
    }
  }

  async function loadHistory() {
    const version = ++historyRequestVersion;
    const sport = activeSport;
    const competition = selectedCompetition;
    historyLoading = true;
    historyLoadError = '';
    const current = () => version === historyRequestVersion && sport === activeSport && competition === selectedCompetition;
    try {
      const items = await api.investigations(undefined, 0, sport);
      if (!current()) return;
      history = sport === 'soccer' ? items.filter(item => item.run.scope.competition === competition) : items;
      if (items.some(item => item.run.subject?.type === 'player' && !item.run.subject.display_name) && !playersLoading) void loadPlayers();
    } catch (problem) {
      if (current()) historyLoadError = problem instanceof Error ? problem.message : String(problem);
    } finally {
      if (current()) historyLoading = false;
    }
  }

  async function switchSport(sport: string, keepRoute = false) {
    if (sport === activeSport || busy) return;
    if (!keepRoute) setReportRoute('');
    sportDrafts[activeSport] = captureDraft();
    workspaceRequestVersion += 1;
    historyRequestVersion += 1;
    historyLoadError = '';
    historyLoading = false;
    playerSearchVersion += 1;
    activeSport = sport;
    active = null;
    conversationThread = [];
    analysisOptions = null;
    datasets = [];
    history = [];
    players = [];
    searchedPlayers = [];
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
      syncSeasons: [...syncSeasons], syncDatasets: [...syncDatasets], dataManagerOpen,
      customizeSources, customizeMetrics, metricsEdited, compareSubjectId, headToHeadFirst,
      selectedCompetition, baselineStartDate, baselineEndDate, comparisonStartDate, comparisonEndDate
    };
  }

  function resetDraft(sport: string) {
    downloadScope = {kind: 'league', ready: true, label: 'Entire League'};
    cfbHistoryLoading = false;
    cfbLoading = sport === 'cfb';
    cfbError = '';
    clearTimeout(cfbSearchTimer);
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
    analysisDomain = sport === 'nba' ? 'offense' : ['soccer', 'cfb'].includes(sport) ? 'results' : 'passing';
    comparisonMode = 'full_seasons';
    baselineSegment = 'regular_season';
    comparisonSegment = 'regular_season';
    baselineStartDate = baselineEndDate = comparisonStartDate = comparisonEndDate = '';
    question = '';
    showFullFilmRoom = false;
    compareSubjectId = '';
    headToHeadFirst = 0;
    compareCfbTeams = [];
    compareCfbSchool = '';
    comparePlayers = [];
    comparePlayerVersion += 1;
    selectedMetrics = [];
    selectedSplits = [];
    syncSeasons = [];
    syncDatasets = ['play_by_play'];
    dataManagerOpen = true;
    syncComplete = false;
    customizeSources = false;
    customizeMetrics = false;
    metricsEdited = false;
    readinessKey = '';
    metricInfo = null;
    metricInfoVersion += 1;
    metricInfoLoading = false;
    metricInfoError = '';
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
    customizeSources = draft.customizeSources;
    customizeMetrics = draft.customizeMetrics;
    metricsEdited = draft.metricsEdited;
    compareSubjectId = draft.compareSubjectId ?? '';
    headToHeadFirst = draft.headToHeadFirst ?? 0;
    selectedCompetition = draft.selectedCompetition;
    baselineStartDate = draft.baselineStartDate;
    baselineEndDate = draft.baselineEndDate;
    comparisonStartDate = draft.comparisonStartDate;
    comparisonEndDate = draft.comparisonEndDate;
  }

  function initializeSelections() {
    if (!analysisOptions) return;
    const seasons = [...new Set([...analysisOptions.available_seasons, ...(analysisOptions.automatic_preparation ? analysisOptions.preparable_seasons ?? [] : [])])].sort((left, right) => right - left);
    if (seasons.length) {
      if (!seasons.includes(comparison)) comparison = seasons[0];
      if (!seasons.includes(baseline)) baseline = seasons[1] ?? seasons[0];
    }
    if (!initializedSelections) {
      // A fresh sport starts on its latest completed seasons, never ones carried over from another sport.
      const pair = defaultSeasonPair(analysisOptions, seasons);
      if (pair) [baseline, comparison] = pair;
      selectedMetrics = [...analysisOptions.default_metrics];
      const syncable = analysisOptions.syncable_seasons.filter(season => {
        const required = analysisOptions?.data_setup?.required_datasets ?? ['play_by_play'];
        return required.every(source => eligibleSelectedSeasons(source, [season]).length);
      });
      // Tick the seasons the analysis will use, so the download list and the form agree.
      const analysed = syncable.filter(season => season >= baseline && season <= comparison);
      syncSeasons = analysed.length ? analysed : syncable.slice(0, 2);
      selectLocallyAvailablePackages();
      const required = analysisOptions.data_setup?.required_datasets?.length ? analysisOptions.data_setup.required_datasets : ['play_by_play'];
      dataManagerOpen = ![baseline, comparison].every(season => required.every(source => syncedPackages(season).has(source)));
      initializedSelections = true;
    }
    const validDomains = analysisOptions.analysis_domains.filter((domain) => domainAvailableForSubject(domain));
    if (!validDomains.some((domain) => domain.value === analysisDomain)) {
      analysisDomain = validDomains[0]?.value ?? analysisOptions.analysis_domains[0]?.value ?? analysisDomain;
      useRecommendedMetrics();
    }
  }

  // The latest two completed seasons, preferring ones already synced.
  function defaultSeasonPair(options: AnalysisOptions, seasons: number[]): [number, number] | null {
    const current = options.current_season;
    const complete = seasons.filter(season => current == null || season < current);
    const synced = options.available_seasons.filter(season => complete.includes(season)).sort((left, right) => right - left);
    const pool = synced.length >= 2 ? synced : complete.length ? complete : seasons;
    return pool.length ? [pool[1] ?? pool[0], pool[0]] : null;
  }

  function domainAvailableForSubject(
      domain: { value?: string; subject_type?: string },
      type = subjectType,
      player: PlayerOption | null = selectedPlayer
  ) {
    if (domain.subject_type) {
      if (domain.subject_type !== 'both' && domain.subject_type !== type) return false;
      if (activeSport === 'nfl' && type === 'player' && player) {
        const value = domain.value ?? '';
        const recordedSeasons = player.seasons_by_domain?.[value];
        if (recordedSeasons) return recordedSeasons.length > 0;
        const role = playerRole(player);
        if (role === 'quarterback') return value === 'quarterback';
        if (role === 'receiver') return value === 'receiving';
        if (role === 'running back') return value === 'running' || value === 'receiving';
      }
      return true;
    }
    // Keep older saved/stale option payloads from exposing team domains to
    // player investigations when they predate explicit subject metadata.
    const inferredPlayerDomains = activeSport === 'nfl'
        ? new Set(['quarterback', 'receiving', 'running', 'defender'])
        : new Set(['scoring', 'usage', 'impact']);
    const inferredTeamDomains = activeSport === 'nfl'
        ? new Set(['passing', 'rushing', 'offense', 'defense'])
        : new Set(['offense', 'defense', 'lineups']);
    if (inferredPlayerDomains.has(domain.value ?? '')) return type === 'player';
    if (inferredTeamDomains.has(domain.value ?? '')) return type === 'team';
    return true;
  }

  function selectSubjectType(type: 'team' | 'player') {
    subjectType = type;
    compareSubjectId = activeSport === 'cfb' && type === 'team' ? compareCfbSchool : '';
    if (activeSport === 'cfb' && type === 'player' && compareCfbSchool) void loadComparePlayers(compareCfbSchool, compareCfbSeason);
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
      const scopeKey = `${resolvedTeam}:${cfbBrowseSeason}`;
      if (sport === 'cfb' && !resolvedTeam) {
        players = [];
        return;
      }
      const matches = await api.players(sport, sport === 'cfb' ? playerFilter : '', sport === 'soccer' ? selectedCompetition : undefined,
          sport === 'cfb' ? resolvedTeam : undefined, sport === 'cfb' ? cfbBrowseSeason : undefined);
      if (sport === 'cfb' && scopeKey !== `${resolvedTeam}:${cfbBrowseSeason}`) return;
      if (version === playerSearchVersion && sport === activeSport) players = matches;
    } catch (problem) {
      if (version === playerSearchVersion && sport === activeSport) playerLoadError = String(problem);
    } finally {
      if (version === playerSearchVersion && sport === activeSport) playersLoading = false;
    }
  }

  function mergePlayers(loaded: PlayerOption[], extra: PlayerOption[]) {
    if (!extra.length) return loaded;
    const known = new Set(loaded.map(player => player.player_id));
    return [...loaded, ...extra.filter(player => !known.has(player.player_id))];
  }

  function searchPlayers(query: string) {
    const term = query.trim();
    clearTimeout(playerQueryTimer);
    if (activeSport === 'cfb' || term.length < 2) return;
    const version = ++playerQueryVersion;
    const sport = activeSport;
    const competition = selectedCompetition;
    playerQueryTimer = setTimeout(async () => {
      playerSearching = true;
      try {
        const matches = await api.players(sport, term, sport === 'soccer' ? competition : undefined);
        if (sport === activeSport && competition === selectedCompetition) searchedPlayers = mergePlayers(searchedPlayers, matches);
      } catch { /* The downloaded list still works when a search fails. */
      } finally {
        if (version === playerQueryVersion) playerSearching = false;
      }
    }, 250);
  }

  function playerDisplay(player: PlayerOption) {
    return `${player.name}${player.teams.length ? ` · ${player.teams.map(team => playerTeamLabel(team)).join('/')}` : ''}`;
  }

  function compareCfbChanged(selection: {season: number; teams: TeamOption[]; team: string; loading: boolean; error: string}) {
    compareCfbTeams = selection.teams;
    const school = selection.loading || selection.error ? '' : selection.team;
    if (school === compareCfbSchool && selection.season === compareCfbSeason) return;
    compareCfbSchool = school;
    compareCfbSeason = selection.season;
    compareSubjectId = subjectType === 'team' ? school : '';
    comparePlayers = [];
    comparePlayerVersion += 1;
    if (subjectType === 'player' && school) void loadComparePlayers(school, selection.season);
  }

  async function loadComparePlayers(school: string, season: number) {
    const version = ++comparePlayerVersion;
    comparePlayersLoading = true;
    try {
      const matches = await api.players('cfb', '', undefined, school, season);
      if (version === comparePlayerVersion) comparePlayers = matches;
    } catch {
      if (version === comparePlayerVersion) comparePlayers = [];
    } finally {
      if (version === comparePlayerVersion) comparePlayersLoading = false;
    }
  }

  function cfbSelectionChanged(selection: {
    season: number; seasons: number[]; teams: Array<{ value: string; label: string }>;
    team: string; subdivision: string; conference: string; conferenceLabel: string; loading: boolean; error: string
  }) {
    if (activeSport !== 'cfb') return;
    const changed = team !== selection.team || cfbBrowseSeason !== selection.season;
    cfbBrowseSeason = selection.season;
    cfbSubdivision = selection.subdivision;
    cfbConference = selection.conference;
    cfbConferenceLabel = selection.conferenceLabel;
    cfbLoading = selection.loading;
    cfbError = selection.error;
    if (analysisOptions && selection.seasons.length) {
      cfbSeasons = selection.seasons;
      cfbTeams = selection.teams;
      const firstCatalog = !analysisOptions.syncable_seasons.length;
      analysisOptions = {
        ...analysisOptions, teams: selection.teams, available_seasons: selection.seasons,
        syncable_seasons: selection.seasons,
        metrics: analysisOptions.metrics.map(metric => ({...metric, available_seasons: selection.seasons}))
      };
      if (firstCatalog) {
        initializedSelections = false;
        initializeSelections();
      }
      if (!syncSeasons.length) syncSeasons = selection.seasons.slice(0, 2);
      if (syncDatasets.includes('play_by_play')) syncDatasets = [...suggestedSources];
    }
    team = selection.team;
    teamInput = selection.teams.find(option => option.value === team)?.label ?? '';
    if (changed) {
      selectedPlayerId = '';
      players = [];
      playerInput = '';
      playerFilter = '';
      playerTeamId = '';
      cfbHistoryLoading = false;
      playerSearchVersion += 1;
      clearTimeout(cfbSearchTimer);
      if (subjectType === 'player' && team && !selection.loading) void tick().then(() => loadPlayers());
    }
  }

  function playerTeamLabel(team: string) {
    return activeSport === 'soccer' ? analysisOptions?.teams.find(option => option.value === team)?.label ?? team : team;
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
    if (activeSport === 'cfb') {
      clearTimeout(cfbSearchTimer);
      playerSearchVersion += 1;
      cfbSearchTimer = setTimeout(() => {
        if (activeSport === 'cfb') void loadPlayers();
      }, 250);
    } else {
      searchPlayers(playerInput);
    }
  }

  async function selectPlayer(player: PlayerOption) {
    playerSearchVersion += 1;
    playersLoading = false;
    playerLoadError = '';
    selectedPlayerId = player.player_id;
    playerInput = playerDisplay(player);
    playerFilter = '';
    playerTeamId = player.teams.length === 1 ? player.teams[0] : '';
    if (activeSport === 'cfb') {
      const version = playerSearchVersion;
      cfbHistoryLoading = true;
      try {
        const history = await api.cfbPlayerSeasons(player.player_id);
        if (activeSport !== 'cfb' || version !== playerSearchVersion) return;
        player = {...player, seasons: history.seasons};
        players = players.map(option => option.player_id === player.player_id ? player : option);
      } catch (problem) {
        if (version === playerSearchVersion) {
          playerLoadError = String(problem);
          selectedPlayerId = '';
        }
        return;
      } finally {
        if (version === playerSearchVersion) cfbHistoryLoading = false;
      }
    }
    if (activeSport === 'nfl') {
      const role = playerRole(player);
      const preferredDomain = role === 'quarterback' ? 'quarterback'
          : role === 'running back' ? 'running'
              : role === 'receiver' ? 'receiving'
                  : role === 'defender' ? 'defender' : analysisDomain;
      selectAnalysisDomain(preferredDomain, true, player);
    } else if (activeSport === 'cfb') {
      const positions = new Set(player.positions.map(position => position.toUpperCase()));
      selectAnalysisDomain(positions.has('QB') ? 'quarterback'
          : ['RB', 'FB', 'HB'].some(position => positions.has(position)) ? 'rushing'
              : ['DE', 'DT', 'NT', 'DL', 'EDGE', 'LB', 'ILB', 'MLB', 'OLB', 'CB', 'DB', 'S', 'FS', 'SS', 'SAF']
                  .some(position => positions.has(position)) ? 'defender' : 'receiving', true, player);
    } else {
      selectAnalysisDomain(analysisDomain, true, player);
    }
    normalizePlayerSeasonSelection(player);
    playerComboboxOpen = false;
  }

  function normalizePlayerSeasonSelection(player: PlayerOption) {
    const local = new Set([...(analysisOptions?.available_seasons ?? []), ...(analysisOptions?.automatic_preparation ? analysisOptions.preparable_seasons ?? [] : [])]);
    const seasons = playerSeasonsForDomain(player).map(Number).filter((season) => local.has(season)).sort((left, right) => right - left);
    if (!seasons.length) return;
    if (!seasons.includes(comparison)) comparison = seasons[0];
    if (!seasons.includes(baseline)) baseline = seasons[1] ?? seasons[0];
    if (comparisonMode === 'full_seasons' && seasons.length > 1 && baseline >= comparison) {
      baseline = seasons[1];
      comparison = seasons[0];
    }
  }

  function playerSeasonsForDomain(player: PlayerOption, domain = analysisDomain, sport = activeSport) {
    if (sport === 'nfl' && player.seasons_by_domain) {
      return player.seasons_by_domain[domain] ?? [];
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

  function metricAvailable(metric: MetricOption, seasons = requiredSeasons, automatic = analysisOptions?.automatic_preparation) {
    return activeSport === 'cfb' || seasons.every((season) => metric.available_seasons.includes(season)
        || (automatic && metric.preparable_seasons?.includes(season)));
  }

  function toggleMetric(metric: string) {
    metricsEdited = true;
    selectedMetrics = selectedMetrics.includes(metric)
        ? selectedMetrics.filter((value) => value !== metric)
        : [...selectedMetrics, metric];
  }

  function splitAvailable(availableSeasons: number[], seasons = requiredSeasons) {
    return seasons.every((season) => availableSeasons.includes(season));
  }

  function toggleSplit(split: string) {
    selectedSplits = selectedSplits.includes(split)
        ? selectedSplits.filter((value) => value !== split)
        : [...selectedSplits, split];
  }

  function useRecommendedMetrics() {
    metricsEdited = false;
    const recommended = new Set(analysisOptions?.default_metrics_by_domain?.[analysisDomain] ?? analysisOptions?.default_metrics ?? []);
    selectedMetrics = availableMetrics.filter((metric) => recommended.has(metric.value)).map((metric) => metric.value);
  }

  function possessive(name: string) {
    return /s$/i.test(name) ? `${name}'` : `${name}'s`;
  }

  function playerRole(player: PlayerOption | null, sport = activeSport) {
    const positions = new Set((player?.positions ?? []).map(position => position.trim().toUpperCase()));
    if (sport === 'nfl') {
      if (positions.has('QB') || positions.has('QUARTERBACK')) return 'quarterback';
      if (['RB', 'FB', 'RUNNING BACK', 'FULLBACK'].some(position => positions.has(position))) return 'running back';
      if (['WR', 'TE', 'WIDE RECEIVER', 'TIGHT END', 'RECEIVER'].some(position => positions.has(position))) return 'receiver';
      if (['DE', 'DT', 'NT', 'DL', 'EDGE', 'LB', 'ILB', 'MLB', 'OLB', 'CB', 'DB', 'S', 'FS', 'SS', 'SAF']
          .some(position => positions.has(position))) return 'defender';
      return 'player';
    }
    if ([...positions].some(position => ['PG', 'SG', 'G', 'G-F', 'GUARD', 'POINT GUARD', 'SHOOTING GUARD', 'GUARD-FORWARD'].includes(position))) return 'guard';
    if ([...positions].some(position => ['SF', 'F', 'F-G', 'SMALL FORWARD', 'FORWARD', 'FORWARD-GUARD'].includes(position))) return 'wing';
    if ([...positions].some(position => ['PF', 'C', 'F-C', 'C-F', 'POWER FORWARD', 'CENTER', 'FORWARD-CENTER', 'CENTER-FORWARD'].includes(position))) return 'big';
    return 'player';
  }

  const nbaRoleQuestions: Record<string, Record<string, string>> = {
    guard: {
      scoring: "Did {player}'s scoring change through on-ball volume, perimeter shooting, or free-throw creation?",
      shooting: "How did {player}'s three-point volume, perimeter accuracy, and overall shot efficiency change?",
      playmaking: "Did {player} create more efficiently as a guard without adding a comparable turnover burden?",
      rebounding: "Did {player}'s guard rebounding add meaningful possessions, or was the change mostly matchup-driven?",
      turnovers: "Did {player}'s ball security improve relative to the guard creation load handled?",
      usage: "Did {player}'s guard role expand through more minutes, more on-ball involvement, or both?",
      impact: "How did {player}'s impact change across lead-guard and off-ball lineup contexts?",
      lineups: "Which backcourt and five-player combinations best complemented {player}?"
    },
    wing: {
      scoring: "Did {player}'s scoring change through rim pressure, perimeter volume, shot-making, or free throws?",
      shooting: "How did {player}'s shot-making change across the perimeter and higher-value scoring opportunities?",
      playmaking: "Did {player}'s secondary creation improve without sacrificing scoring efficiency or ball security?",
      rebounding: "Did {player}'s rebounding contribution as a wing change consistently or only in particular matchups?",
      turnovers: "Did {player} protect the ball more effectively as scoring and creation responsibilities changed?",
      usage: "Did {player}'s wing role expand through minutes, scoring involvement, or added creation duties?",
      impact: "Which two-way lineup contexts best explain the change in {player}'s impact?",
      lineups: "Which guard, wing, and frontcourt combinations best complemented {player}?"
    },
    big: {
      scoring: "Did {player}'s scoring change through rim finishing, free throws, offensive boards, or expanded range?",
      shooting: "Did {player}'s efficiency change because of finishing, floor-spacing volume, or a different shot mix?",
      playmaking: "Did {player} create more effectively from post, short-roll, or handoff opportunities without adding turnovers?",
      rebounding: "Did {player}'s rebounding change through offensive-board production, overall activity, or matchup effects?",
      turnovers: "Did {player}'s turnover burden change in proportion to touches and offensive responsibility?",
      usage: "Did {player}'s frontcourt role expand through minutes, finishing volume, or greater offensive involvement?",
      impact: "Which frontcourt and lineup contexts best explain the change in {player}'s overall impact?",
      lineups: "Which frontcourt partners and five-player units best complemented {player}?"
    }
  };

  function contextualizeQuestion(example: string, type: 'team' | 'player', player: PlayerOption | null) {
    if (type === 'player' && player) {
      const name = player.name;
      const owned = possessive(name);
      return example
          .replaceAll("this quarterback's", owned)
          .replaceAll("this receiver's", owned)
          .replaceAll("this runner's", owned)
          .replaceAll("this ball carrier's", owned)
          .replaceAll("this player's", owned)
          .replaceAll("the player's", owned)
          .replaceAll('this quarterback', name)
          .replaceAll('this receiver', name)
          .replaceAll('this runner', name)
          .replaceAll('the player', name)
          .replaceAll('this player', name);
    }
    if (type === 'team' && resolvedTeam) {
      const name = analysisOptions?.teams.find(option => option.value === resolvedTeam)?.label;
      if (name) {
        const owned = possessive(name);
        return example.replaceAll("this team's", owned).replaceAll("the team's", owned)
            .replaceAll('this team', name).replaceAll('the team', name);
      }
    }
    return example;
  }

  function examplesFor(sport = activeSport, type = subjectType, domain = analysisDomain, player = selectedPlayer) {
    const primary = questionBanks[sport]?.[type]?.[domain] ?? [];
    const supplemental = supplementalQuestionBanks[sport]?.[type]?.[domain] ?? [];
    const expanded = expandedQuestions[sport]?.[type]?.[domain] ?? [];
    const available = [...new Set([...primary, ...supplemental, ...expanded])];
    const base = available.length ? available : [initialQuestion];
    const contextualized = base.map(example => contextualizeQuestion(example, type, player));
    if (sport !== 'nba' || type !== 'player' || !player) return contextualized;
    const roleQuestion = nbaRoleQuestions[playerRole(player, sport)]?.[domain]?.replaceAll('{player}', player.name);
    return roleQuestion ? [roleQuestion, ...contextualized.filter(example => example !== roleQuestion)] : contextualized;
  }

  function isCuratedExample(value: string) {
    return [questionBanks, supplementalQuestionBanks, expandedQuestions].some((bank) => Object.values(bank).some((sport) =>
        Object.values(sport).some((subject) => Object.values(subject).some((examples) => examples.includes(value)))
    ));
  }

  function selectAnalysisDomain(domain: string, force = false, player = selectedPlayer) {
    if (analysisDomain === domain && !force) return;
    const replaceSuggested = question.trim() && (question === lastSuggestedQuestion || isCuratedExample(question));
    analysisDomain = domain;
    metricsEdited = false;
    metricInfoVersion += 1;
    metricInfo = null;
    metricInfoLoading = false;
    metricInfoError = '';
    const recommended = new Set(analysisOptions?.default_metrics_by_domain?.[domain] ?? []);
    selectedMetrics = (analysisOptions?.metrics ?? [])
        .filter((metric) => metric.analysis_domain === domain
            && (!metric.subject_types?.length || metric.subject_types.includes(subjectType))
            && metricAvailable(metric) && recommended.has(metric.value))
        .map((metric) => metric.value);
    if (replaceSuggested) {
      question = examplesFor(activeSport, subjectType, domain, player)[0];
      lastSuggestedQuestion = question;
    }
    if (selectedPlayer) normalizePlayerSeasonSelection(selectedPlayer);
  }

  function selectAllMetrics() {
    metricsEdited = true;
    selectedMetrics = availableMetrics.map((metric) => metric.value);
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
    if (!customizeSources) syncDatasets = [...new Set([...(analysisOptions?.data_setup?.required_datasets?.length ? analysisOptions.data_setup.required_datasets : ['play_by_play']), ...(analysisOptions?.data_setup?.recommended_datasets ?? [])])].filter(source => packageEligible(source));
  }

  function toggleSyncSeason(season: number) {
    syncSeasons = syncSeasons.includes(season)
        ? syncSeasons.filter((value) => value !== season)
        : [...syncSeasons, season].sort((left, right) => right - left);
    selectLocallyAvailablePackages();
  }

  function datasetLabel(dataset: string) {
    return packageLabel(dataset, activeSport);
  }

  function snapshotMatchesTeam(dataset: DatasetManifest, selectedTeam = resolvedTeam, fullLibrary = false) {
    if (activeSport === 'soccer' && dataset.competition !== selectedCompetition) return false;
    if (activeSport === 'cfb') return dataset.partition_key === `team:${selectedTeam}`;
    return !dataset.partition_key || (!fullLibrary && dataset.partition_key === `team:${selectedTeam}`);
  }

  function syncedPackages(season: number, selectedTeam = resolvedTeam, fullLibrary = false) {
    return new Set(datasets.filter((dataset) => (dataset.sport ?? 'nfl') === activeSport && dataset.season === season
        && dataset.row_count !== 0 && dataset.availability !== 'source_unavailable'
        && snapshotMatchesTeam(dataset, selectedTeam, fullLibrary)).map((dataset) => dataset.dataset));
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
    if (!packages.size) return 'Not local';
    const missing = requiredSources.filter(source => !packages.has(source)).length;
    return missing ? `${missing} required missing` : 'Required ready';
  }

  function packageCoverage(dataset: string, selectedSeasons = syncSeasons) {
    if (isReferenceDataset(dataset)) {
      return 'shared reference data';
    }
    if (!selectedSeasons.length) return 'Select seasons';
    const eligibleSeasons = eligibleSelectedSeasons(dataset, selectedSeasons);
    const minimum = datasetMinimumSeason(dataset);
    const published = datasetAvailableSeasons(dataset);
    if (published) {
      if (!eligibleSeasons.length) return 'not offered for selected seasons';
      const first = Math.min(...published);
      const last = Math.max(...published);
      return `${seasonLabel(first)} to ${seasonLabel(last)}`;
    }
    const minimumLabel = minimum ? `${seasonLabel(minimum)}+` : '';
    if (!eligibleSeasons.length) return `not offered · ${minimumLabel}`;
    return minimumLabel || 'offered for selected seasons';
  }

  function packageInstallStatus(dataset: string, selectedSeasons = syncSeasons, selectedTeam = resolvedTeam)
      : {state: string; label: string; detail?: string} | null {
    if (activeSport !== 'cfb' && ['conference', 'division'].includes(downloadScope.kind))
      return {state: 'partial', label: 'Per-season group coverage checked on sync'};
    if (activeSport !== 'cfb' && downloadScope.kind === 'team') selectedTeam = downloadScope.team_ids?.[0] ?? '';
    const fullLibrary = activeSport !== 'cfb' && downloadScope.kind === 'league';
    if (isReferenceDataset(dataset)) {
      return datasets.some((item) => item.dataset === dataset)
          ? {state: 'installed', label: 'Installed'}
          : null;
    }
    const eligibleSeasons = eligibleSelectedSeasons(dataset, selectedSeasons);
    if (!eligibleSeasons.length) return null;
    const scopedSnapshots = datasets.filter(item => (item.sport ?? 'nfl') === activeSport
        && item.dataset === dataset && eligibleSeasons.includes(item.season)
        && snapshotMatchesTeam(item, selectedTeam, fullLibrary));
    if (scopedSnapshots.some(item => item.availability === 'download_failed'))
      return {state: 'partial', label: 'Download failed · retry'};
    if (scopedSnapshots.some(item => item.availability === 'source_unavailable'))
      return {state: 'partial', label: activeSport === 'cfb' ? 'Limited source coverage · recheck hourly' : 'Not published for selection · recheck'};
    if (scopedSnapshots.some(item => item.coverage?.retained_previous_data || item.coverage?.source_unavailable))
      return {state: 'partial', label: 'Previous data retained · retry refresh'};
    const local = eligibleSeasons.filter((season) => syncedPackages(season, selectedTeam, fullLibrary).has(dataset)).length;
    if (!local) return null;
    if (activeSport === 'cfb') {
      const snapshots = datasets.filter(item => item.sport === 'cfb' && item.partition_key === `team:${selectedTeam}`
          && item.dataset === dataset && eligibleSeasons.includes(item.season));
      if (snapshots.some(item => item.availability === 'download_failed')) return {state: 'partial', label: 'Download failed · retry'};
      if (snapshots.some(item => item.availability === 'season_unverified')) return {state: 'partial', label: 'Season unverified · recheck'};
      if (snapshots.some(item => item.availability === 'source_unavailable')) return {state: 'partial', label: 'Limited source coverage · recheck hourly'};
      if (snapshots.every(item => item.row_count === 0)) return {state: 'partial', label: 'No recorded rows'};
      if (snapshots.some(item => (item.coverage?.completed_matches ?? 0) < (item.coverage?.expected_matches ?? 0)))
        return {state: 'partial', label: 'Partial · resume sync'};
    }
    if (activeSport === 'soccer' && dataset === 'team_stats') {
      const teamSources = datasets.filter(item => item.sport === 'soccer' && snapshotMatchesTeam(item, selectedTeam, fullLibrary) && item.dataset === 'team_stats' && eligibleSeasons.includes(item.season));
      const teamMatches = teamSources.reduce((sum, item) => sum + (item.coverage?.recorded_matches ?? 0), 0);
      const statsLabel = teamSources.every(item => item.coverage?.recorded_matches !== undefined)
          ? `Team stats: ${teamMatches} matches` : `Team stats: ${local}/${eligibleSeasons.length} seasons`;
      const sources = datasets.filter(item => snapshotMatchesTeam(item, selectedTeam, fullLibrary) && item.dataset === 'expected_goals' && eligibleSeasons.includes(item.season));
      const covered = sources.reduce((sum, item) => sum + (item.coverage?.recorded_matches ?? 0), 0);
      const expected = sources.reduce((sum, item) => sum + (item.coverage?.expected_matches ?? 0), 0);
      const incomplete = local < eligibleSeasons.length || eligibleSeasons.some(season => soccerPackageIncomplete(dataset, season, selectedTeam, fullLibrary));
      return {
        state: incomplete ? 'partial' : 'installed',
        label: incomplete ? 'Partial · resume sync' : 'Installed',
        detail: `${statsLabel} · xG for ${covered} of ${expected} matches${!incomplete && covered < expected ? ' (limited source coverage)' : ''}`
      };
    }
    if (activeSport === 'soccer' && eligibleSeasons.some(season => soccerPackageIncomplete(dataset, season, selectedTeam, fullLibrary))) {
      return {state: 'partial', label: 'Partial · resume sync'};
    }
    return local === eligibleSeasons.length
        ? {state: 'installed', label: 'Installed'}
        : {state: 'partial', label: `Local ${local}/${eligibleSeasons.length}`};
  }

  function packageEligible(dataset: string, selectedSeasons = syncSeasons) {
    if (isReferenceDataset(dataset)) return true;
    return eligibleSelectedSeasons(dataset, selectedSeasons).length > 0;
  }

  function soccerPackageIncomplete(dataset: string, season: number, selectedTeam = resolvedTeam, fullLibrary = false) {
    if (activeSport === 'cfb') {
      const snapshot = datasets.find(item => item.sport === 'cfb' && item.partition_key === `team:${resolvedTeam}`
          && item.dataset === dataset && item.season === season);
      return Boolean(snapshot && ((snapshot.availability && snapshot.availability !== 'available')
          || (snapshot.coverage?.completed_matches ?? 0) < (snapshot.coverage?.expected_matches ?? 0)));
    }
    if (activeSport !== 'soccer') return false;
    if (dataset === 'team_stats') {
      const xg = datasets.find(item => item.sport === 'soccer' && snapshotMatchesTeam(item, selectedTeam, fullLibrary) && item.dataset === 'expected_goals' && item.season === season);
      if (!xg || (xg.coverage?.completed_matches ?? 0) < (xg.coverage?.expected_matches ?? 0)) return true;
    }
    const manifest = datasets.find(item => item.sport === 'soccer' && snapshotMatchesTeam(item, selectedTeam, fullLibrary) && item.dataset === dataset && item.season === season);
    const completed = dataset === 'play_by_play' ? manifest?.coverage?.fetched_intervals : manifest?.coverage?.completed_matches;
    const expected = dataset === 'play_by_play' ? manifest?.coverage?.expected_intervals : manifest?.coverage?.expected_matches;
    return completed !== undefined && expected !== undefined && completed < expected;
  }

  function missingSyncSeasons(dataset: string, selectedSeasons = syncSeasons) {
    if (activeSport !== 'cfb' && downloadScope.kind !== 'league') return eligibleSelectedSeasons(dataset, selectedSeasons);
    if (isReferenceDataset(dataset)) {
      return datasets.some((item) => (item.sport ?? 'nfl') === activeSport && item.dataset === dataset) ? [] : selectedSeasons.slice(0, 1);
    }
    const currentNflSeason = activeSport === 'nfl' ? 2026 : null;
    const now = new Date();
    const currentNbaSeason = activeSport === 'nba' ? now.getUTCFullYear() + (now.getUTCMonth() >= 6 ? 1 : 0) : null;
    const currentSoccerSeason = activeSport === 'soccer' ? now.getFullYear() +
        (!soccerCompetitions.find(item => item.value === selectedCompetition)?.calendar && now.getMonth() >= 6 ? 1 : 0) : null;
    return eligibleSelectedSeasons(dataset, selectedSeasons).filter((season) =>
        season === currentNflSeason || season === currentNbaSeason || season === currentSoccerSeason
        || (activeSport === 'cfb' && season === now.getUTCFullYear())
        || !syncedPackages(season, resolvedTeam, activeSport !== 'cfb').has(dataset)
        || soccerPackageIncomplete(dataset, season, resolvedTeam, activeSport !== 'cfb'));
  }

  function seasonLabel(season: number) {
    if (activeSport === 'soccer' && !soccerCompetitions.find(item => item.value === selectedCompetition)?.calendar) return `${season - 1}–${String(season).slice(-2)}`;
    return activeSport === 'nba' ? `${season - 1}–${String(season).slice(-2)}` : String(season);
  }

  async function selectCompetition(competition: string, keepRoute = false) {
    if (competition === selectedCompetition || busy) return;
    if (!keepRoute) setReportRoute('');
    selectedCompetition = competition;
    workspaceRequestVersion += 1;
    historyRequestVersion += 1;
    historyLoadError = '';
    historyLoading = false;
    playerSearchVersion += 1;
    resetDraft('soccer');
    analysisOptions = null;
    datasets = [];
    history = [];
    players = [];
    searchedPlayers = [];
    active = null;
    await refresh();
  }

  function availableSegments(season: number) {
    const allowed = analysisOptions?.segment_availability?.[String(season)];
    const segments = analysisOptions?.season_segments ?? [];
    if (allowed?.length) return segments.filter((segment) => allowed.includes(segment.value));
    return segments.filter((segment) => ['full_season', 'regular_season', 'playoffs'].includes(segment.value));
  }

  function investigationSubject(item: Investigation | InvestigationSummary, playerNames = playerNamesById) {
    const first = subjectName(item, item.run.subject, playerNames);
    return item.run.comparison_subject ? `${first} vs ${subjectName(item, item.run.comparison_subject, playerNames)}` : first;
  }

  function subjectName(item: Investigation | InvestigationSummary, subject: Investigation['run']['subject'], playerNames = playerNamesById) {
    if (subject?.type === 'player') {
      return subject.display_name || playerNames.get(subject.id) || subject.id;
    }
    const teamId = subject?.id || item.run.scope.team;
    const sameContext = (item.run.sport ?? 'nfl') === activeSport
        && (activeSport !== 'soccer' || item.run.scope.competition === selectedCompetition);
    const teamName = sameContext ? analysisOptions?.teams.find(team => team.value === teamId)?.label : undefined;
    return subject?.display_name || teamName || teamId;
  }

  function investigationSubjectInitials(item: Investigation | InvestigationSummary, playerNames = playerNamesById) {
    const label = investigationSubject(item, playerNames).trim();
    const words = label.split(/\s+/).filter(Boolean);
    if (words.length > 1) return `${words[0][0]}${words[words.length - 1][0]}`.toUpperCase();
    return label.slice(0, 3).toUpperCase();
  }

  function investigationWindow(item: Investigation | InvestigationSummary) {
    if (item.run.scope.comparison_design === 'head_to_head') {
      return `${seasonSpan(item.run.scope.baseline.season, item.run.scope.comparison.season)} · Head-to-head`;
    }
    const baselineWindow = item.run.scope.baseline;
    const comparisonWindow = item.run.scope.comparison;
    if (item.run.sport === 'soccer') {
      const competition = item.run.scope.competition ?? selectedCompetition;
      const label = (season: number) => soccerCompetitions.find(entry => entry.value === competition)?.calendar
          ? String(season) : `${season - 1}–${String(season).slice(-2)}`;
      if (item.run.scope.comparison_design === 'date_ranges') {
        return `${baselineWindow.start_date ?? label(baselineWindow.season)}–${baselineWindow.end_date ?? ''} → ${comparisonWindow.start_date ?? label(comparisonWindow.season)}–${comparisonWindow.end_date ?? ''}`;
      }
      return `${label(baselineWindow.season)} → ${label(comparisonWindow.season)}`;
    }
    if (baselineWindow.segment || comparisonWindow.segment) {
      return `${seasonLabel(baselineWindow.season)} ${baselineWindow.segment?.replaceAll('_', ' ') ?? ''} → ${seasonLabel(comparisonWindow.season)} ${comparisonWindow.segment?.replaceAll('_', ' ') ?? ''}`;
    }
    return item.run.scope.comparison_design === 'full_seasons'
        ? `Season Range ${baselineWindow.season}–${comparisonWindow.season}`
        : `${baselineWindow.season} W${baselineWindow.weeks[0]}–${baselineWindow.weeks[1]} → ${comparisonWindow.season} W${comparisonWindow.weeks[0]}–${comparisonWindow.weeks[1]}`;
  }

  function displayDomain(domain?: string) {
    return (analysisOptions?.analysis_domains ?? []).find((option) => option.value === domain)?.label
        ?? domain?.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase())
        ?? 'Analysis';
  }

  function wait(milliseconds: number) {
    return new Promise((resolve) => setTimeout(resolve, milliseconds));
  }

  class ReportedInvestigationFailure extends Error {
  }

  async function scrollToPageTop() {
    await tick();
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    window.scrollTo({top: 0, left: 0, behavior: reduceMotion ? 'auto' : 'smooth'});
  }

  function isCompleteInvestigation(result: Investigation | null | undefined, investigationId: string) {
    return result?.run?.investigation_id === investigationId
        && result.summary != null
        && Array.isArray(result.claims)
        && Array.isArray(result.aggregate_evidence)
        && Array.isArray(result.play_evidence)
        && Array.isArray(result.charts);
  }

  async function loadCompletedInvestigation(investigationId: string) {
    stage = 'Loading completed analysis';
    progress = 1;
    let lastError: unknown = new Error('The completed analysis is not available yet.');
    for (let attempt = 0; attempt < 8; attempt += 1) {
      try {
        const [result, thread] = await Promise.all([
          api.investigation(investigationId),
          api.investigationThread(investigationId)
        ]);
        if (!isCompleteInvestigation(result, investigationId)) {
          throw new Error('The completed analysis response was incomplete.');
        }
        if (!thread.some((turn) => turn.run.investigation_id === investigationId)) {
          throw new Error('The completed analysis thread was incomplete.');
        }
        // A follow-up joins the thread; the report the reader is on stays as written.
        if (followupBusy && active) {
          conversationThread = thread;
          void loadHistory();
          await tick();
          [...document.querySelectorAll('.analyst-row')].at(-1)?.scrollIntoView?.({block: 'nearest'});
          notifyCompletion('Follow-up Answered', 'Your answer is in the thread below the report.');
          return true;
        }
        active = result.run.parent_investigation_id && thread[0] ? thread[0] : result;
        conversationThread = thread;
        setReportRoute(active.run.investigation_id);
        await refresh();
        dismissGuidance();
        prefetchFirstEvidence(active);
        await scrollToPageTop();
        notifyCompletion('Report Ready', 'Your results and supporting evidence are ready to explore.');
        return true;
      } catch (problem) {
        lastError = problem;
        if (attempt < 7) await wait(Math.min(250 * 2 ** attempt, 2_000));
      }
    }
    throw lastError;
  }

  async function recoverInterruptedInvestigation(investigationId: string, streamProblem: unknown) {
    const deadline = Date.now() + 60 * 60_000;
    let lastError = streamProblem;
    stage = 'Connection interrupted · checking your analysis';
    while (Date.now() < deadline) {
      try {
        const status = await api.investigationStatus(investigationId);
        if (status.stage === 'failed') throw new ReportedInvestigationFailure(status.message);
        if (status.stage === 'cancelled') throw new RunCancelled();
        if (status.stage !== 'pending' && status.message) {
          stage = `Reconnecting · ${status.message}`;
          progress = Math.max(progress, Number(status.progress || 0));
        }
      } catch (problem) {
        if (problem instanceof ReportedInvestigationFailure || problem instanceof RunCancelled) throw problem;
        lastError = problem;
      }

      try {
        const result = await api.investigation(investigationId);
        if (isCompleteInvestigation(result, investigationId)) {
          await loadCompletedInvestigation(investigationId);
          return;
        }
      } catch (problem) {
        lastError = problem;
      }
      await wait(2_500);
    }
    throw new Error(
        `Live updates could not be restored within an hour. Your job ID is ${investigationId}. ` +
        `A queued job may still finish; check the Film Room before submitting again. ${String(lastError)}`
    );
  }

  async function streamInvestigation(stream: EventStreamResponse) {
    const reader = stream.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let investigationId = stream.investigationId;
    runningInvestigationId = investigationId ?? '';
    try {
      while (true) {
        const {value, done} = await reader.read();
        buffer += decoder.decode(value, {stream: !done});
        const messages = buffer.split(/\r?\n\r?\n/);
        buffer = messages.pop() ?? '';
        for (const message of messages) {
          const data = message.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
          if (!data) continue;
          const event = JSON.parse(data);
          stage = event.message;
          progress = Math.max(progress, Number(event.progress || 0));
          if (event.investigation_id) investigationId = runningInvestigationId = String(event.investigation_id);
          if (event.stage === 'failed') throw new ReportedInvestigationFailure(event.message);
          if (event.stage === 'cancelled') throw new RunCancelled();
          if (event.stage === 'timeout') throw new Error('The live progress stream timed out.');
          if (event.stage === 'complete') {
            await loadCompletedInvestigation(investigationId!);
            return;
          }
        }
        if (done) throw new Error('The analysis connection ended before the result was ready.');
      }
    } catch (problem) {
      if (problem instanceof ReportedInvestigationFailure || problem instanceof RunCancelled || !investigationId) throw problem;
      await recoverInterruptedInvestigation(investigationId, problem);
    } finally {
      runningInvestigationId = '';
      cancelling = false;
      reader.releaseLock();
    }
  }

  async function cancelRun() {
    if (!runningInvestigationId || cancelling) return;
    cancelling = true;
    try {
      // The progress stream ends the run; False means a result is already arriving.
      await api.cancelInvestigation(runningInvestigationId);
    } catch (problem) {
      cancelling = false;
      error = problemMessage(problem);
    }
  }

  async function streamDatasetSync(stream: EventStreamResponse) {
    const reader = stream.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      while (true) {
        const {value, done} = await reader.read();
        buffer += decoder.decode(value, {stream: !done});
        const messages = buffer.split(/\r?\n\r?\n/);
        buffer = messages.pop() ?? '';
        for (const message of messages) {
          const data = message.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
          if (!data) continue;
          const event = JSON.parse(data);
          stage = event.message;
          progress = Math.max(progress, Number(event.progress || 0));
          if (event.stage === 'failed') throw new ReportedInvestigationFailure(event.message);
          if (event.stage === 'timeout') throw new Error('The data sync timed out before it completed. Try fewer seasons or sources.');
          if (event.stage === 'complete') return;
        }
        if (done) throw new Error('The data-sync connection ended before the download completed.');
      }
    } catch (problem) {
      if (problem instanceof ReportedInvestigationFailure || !stream.jobId) throw problem;
      const deadline = Date.now() + Math.max(3600, stream.timeoutSeconds || 0) * 1000;
      while (Date.now() < deadline) {
        try {
          const status = await api.datasetJobStatus(stream.jobId);
          stage = status.message;
          progress = Math.max(progress, Number(status.progress || 0));
          if (status.stage === 'failed') throw new ReportedInvestigationFailure(status.message);
          if (status.stage === 'complete') return;
        } catch (error) {
          if (error instanceof ReportedInvestigationFailure) throw error;
          stage = 'Connection interrupted · checking download status';
        }
        await wait(2_000);
      }
      throw new Error(`Download updates are unavailable. Job ${stream.jobId} may still finish; check your data library before retrying.`);
    } finally {
      reader.releaseLock();
    }
  }

  async function runAnalysis() {
    if (!canRun || !resolvedSubject) return;
    error = '';
    busy = true;
    active = null;
    progress = 0.03;
    stage = 'Starting analysis';
    void tick().then(() => progressHeading?.focus({preventScroll: true}));
    try {
      let baselineWindow: { season: number; weeks: [number, number]; segment?: string; start_date?: string; end_date?: string } = {season: periodStart, weeks: [1, 22]};
      let comparisonWindow: { season: number; weeks: [number, number]; segment?: string; start_date?: string; end_date?: string } = {
        season: comparison,
        weeks: [1, 22]
      };
      if (headToHead) {
        baselineWindow = {season: periodStart, weeks: [1, 22]};
        comparisonWindow = {season: comparison, weeks: [1, 22]};
      } else if (comparisonMode === 'week_ranges') {
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
        baselineWindow = {season: periodStart, weeks: [1, 22], segment: 'full_season'};
        comparisonWindow = {season: comparison, weeks: [1, 22], segment: 'full_season'};
      } else if (['soccer', 'cfb'].includes(activeSport) && comparisonMode === 'date_ranges') {
        baselineWindow = {...baselineWindow, ...(baselineStartDate ? {start_date: baselineStartDate} : {}), ...(baselineEndDate ? {end_date: baselineEndDate} : {})};
        comparisonWindow = {...comparisonWindow, ...(comparisonStartDate ? {start_date: comparisonStartDate} : {}), ...(comparisonEndDate ? {end_date: comparisonEndDate} : {})};
      }
      const metrics = selectedMetrics.filter((value) => {
        const option = analysisOptions?.metrics.find((metric) => metric.value === value);
        return option ? metricAvailable(option) : false;
      });
      const splits = selectedSplits.filter((value) => {
        const option = analysisOptions?.split_dimensions.find((split) => split.value === value);
        return option ? splitAvailable(option.available_seasons) : false;
      });
      const body = await api.investigateStream({
        sport: activeSport,
        subject: {
          type: subjectType,
          id: resolvedSubject,
          ...(subjectType === 'team' ? {display_name: analysisOptions?.teams.find(team => team.value === resolvedSubject)?.label} : {}),
          ...(subjectType === 'player' && selectedPlayer ? {display_name: selectedPlayer.name} : {}),
          ...(subjectType === 'player' && playerTeamId ? {team_id: playerTeamId} : {})
        },
        ...(headToHead ? {comparison_subject: {type: subjectType, id: compareSubjectId, display_name: compareSubjectLabel}} : {}),
        question: question.trim(),
        analysis_domain: analysisDomain,
        scope: {
          team: subjectType === 'team' ? resolvedTeam : playerTeamId || (activeSport === 'nba' ? 'NBA' : activeSport === 'soccer' ? 'SOCCER' : 'NFL'),
          ...(activeSport === 'soccer' ? {competition: selectedCompetition} : {}),
          baseline: baselineWindow,
          comparison: comparisonWindow,
          season_type: seasonType,
          comparison_design: analysisDesign
        },
        metrics,
        splits
      });
      await streamInvestigation(body);
      busy = false;
    } catch (problem) {
      busy = false;
      if (problem instanceof RunCancelled) {
        notifyCompletion('Analysis Cancelled', 'Your selections are still here, so you can adjust them and run again.');
        await tick();
        document.querySelector<HTMLElement>('.brief-run .primary')?.focus();
      } else {
        error = problemMessage(problem);
      }
    }
  }

  async function clearDownloadedData() {
    const scope = activeSport === 'soccer' ? soccerCompetitions.find(item => item.value === selectedCompetition)?.label : activeSport.toUpperCase();
    if (!window.confirm(`Permanently clear all downloaded ${scope} data for every season? Saved reports and settings stay, but their dataset-backed tools will need a fresh sync. On cloud deployments this clears the shared library for all users.`)) return;
    busy = true;
    stage = 'Clearing downloaded data';
    error = '';
    try {
      try {
        await api.clearDatasets(activeSport, activeSport === 'soccer' ? selectedCompetition : undefined);
      } catch (problem) {
        if (!String(problem).includes('administrator token')) throw problem;
        const token = window.prompt('Enter the cloud data administrator token (not saved):');
        if (!token) return;
        await api.clearDatasets(activeSport, activeSport === 'soccer' ? selectedCompetition : undefined, token);
      }
      syncComplete = false;
      await refresh();
      notifyCompletion('Synced Data Reset', scope + ' synced data has been cleared. Saved reports and settings are preserved.');
    } catch (problem) {
      error = problemMessage(problem);
    } finally {
      busy = false;
    }
  }

  async function syncData() {
    if (activeSport !== 'cfb' && !downloadScope.ready) {
      error = 'Choose a valid download team or group first.';
      return;
    }
    if (activeSport === 'cfb' && !resolvedTeam) {
      error = 'Choose a college-football school before an explicit sync.';
      return;
    }
    if (!syncSeasons.length || !syncDatasets.length) return;
    const offeredDatasets = new Set(analysisOptions?.syncable_datasets ?? []);
    const requestedDatasets = syncDatasets.filter((dataset) =>
        offeredDatasets.has(dataset) && visibleSyncDatasets.includes(dataset) && packageEligible(dataset, syncSeasons) && missingSyncSeasons(dataset).length
    );
    const requestedSeasons = syncSeasons.map(Number).filter((season) => Number.isInteger(season));
    if (!requestedSeasons.length || !requestedDatasets.length) return;
    error = '';
    busy = true;
    syncing = true;
    syncComplete = false;
    stage = 'Preparing data sync';
    progress = 0.03;
    try {
      const missingSeasons = [...new Set(requestedDatasets.flatMap(dataset => missingSyncSeasons(dataset, requestedSeasons)))];
      const stream = await api.syncStream(activeSport, missingSeasons, requestedDatasets, activeSport === 'soccer' ? selectedCompetition : undefined,
          activeSport === 'cfb' ? [resolvedTeam] : downloadScope.team_ids,
          activeSport === 'cfb' ? undefined : {conference_id: downloadScope.conference_id, division_id: downloadScope.division_id});
      await streamDatasetSync(stream);
      syncComplete = true;
      await refresh();
      busy = false;
      syncing = false;
      notifyCompletion('Data Sync Complete', activeSport === 'cfb' ? 'Your data library has been refreshed.'
          : `${downloadScope.label} library refreshed. Check the source coverage below before running.`);
    } catch (problem) {
      error = problemMessage(problem);
      try {
        await refresh();
      } catch {
        // Preserve the source-specific sync error; a manual refresh remains available.
      }
      busy = false;
      syncing = false;
    }
  }

  async function syncCFBConference() {
    const sources = syncDatasets.filter(source => analysisOptions?.syncable_datasets.includes(source) && packageEligible(source, syncSeasons));
    if (activeSport !== 'cfb' || !cfbConference || cfbLoading || cfbError || !cfbTeams.length || !syncSeasons.length || !sources.length) return;
    error = '';
    busy = syncing = true;
    progress = 0.03;
    stage = 'Preparing selected conference teams';
    try {
      const stream = await api.syncStream('cfb', syncSeasons, sources, undefined, undefined,
          {subdivision: cfbSubdivision, conference_id: cfbConference});
      await streamDatasetSync(stream);
      await refresh();
      syncComplete = true;
    } catch (problem) {
      error = problemMessage(problem);
    } finally {
      busy = syncing = false;
    }
  }

  function reportRoute() {
    const match = window.location.hash.match(/^#\/reports\/([^/?#]+)$/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  // Hash routes work unchanged on every host, including the desktop WebView.
  function setReportRoute(investigationId: string) {
    const hash = investigationId ? `#/reports/${encodeURIComponent(investigationId)}` : '';
    if (window.location.hash === hash) return;
    window.history.pushState(null, '', `${window.location.pathname}${window.location.search}${hash}`);
  }

  async function openRoute() {
    const investigationId = reportRoute();
    // Offline links stay in the address bar; the first successful load opens them.
    if (!backendReady || busy || investigationId === (active?.run.investigation_id ?? '')) return;
    if (!investigationId) return openInvestigation(null);
    try {
      const report = await api.investigation(investigationId);
      const sport = report.run.sport ?? 'nfl';
      await switchSport(sport, true);
      if (sport === 'soccer' && report.run.scope.competition) await selectCompetition(report.run.scope.competition, true);
      await openInvestigation(report);
    } catch {
      window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
      error = 'That report could not be found. It may have been deleted.';
    }
  }

  async function openInvestigation(investigation: Investigation | InvestigationSummary | null) {
    if (!investigation) {
      investigationLoading = false;
      active = null;
      conversationThread = [];
      setReportRoute('');
      return;
    }
    investigationLoading = true;
    try {
      active = 'claims' in investigation
          ? investigation
          : await api.investigation(investigation.run.investigation_id);
      conversationThread = await api.investigationThread(active.run.investigation_id);
      setReportRoute(active.run.investigation_id);
      mobileHistoryOpen = false;
      dismissGuidance();
      prefetchFirstEvidence(active);
      await scrollToPageTop();
    } catch (problem) {
      error = problemMessage(problem);
    } finally {
      investigationLoading = false;
    }
  }

  function startNewAnalysis() {
    void openInvestigation(null);
    useRecommendedMetrics();
  }

  async function openGettingStartedGuide() {
    await openInvestigation(null);
    showGuidance = true;
    mobileHistoryOpen = false;
    await focusSection('getting-started');
  }

  async function sendFollowup() {
    if (!active || !followup.trim() || followupBusy) return;
    const question = followup.trim();
    const root = conversationThread[0] ?? active;
    followupBusy = true;
    pendingFollowup = question;
    followup = '';
    try {
      const body = await api.followUpStream(root.run.investigation_id, question);
      await streamInvestigation(body);
      busy = false;
      followupBusy = false;
      pendingFollowup = '';
    } catch (problem) {
      followupBusy = false;
      pendingFollowup = '';
      if (problem instanceof RunCancelled) followup = question;
      else error = problemMessage(problem);
    }
    await tick();
    document.getElementById('followup-question')?.focus({preventScroll: true});
  }

  async function deleteInvestigation(item: Investigation | InvestigationSummary) {
    const identifier = item.run.investigation_id;
    if (!window.confirm(`Delete the saved ${investigationSubject(item, playerNamesById)} report? This cannot be undone.`)) return;
    deletingInvestigationId = identifier;
    try {
      const deletedRoot = rootIdFor(item, history);
      await api.deleteInvestigation(identifier);
      history = history.filter((saved) => rootIdFor(saved, history) !== deletedRoot);
      if (active && rootIdFor(active, history) === deletedRoot) {
        await openInvestigation(null);
      }
      notifyCompletion('Report Deleted', 'The saved report and its follow-ups have been removed.');
    } catch (problem) {
      error = problemMessage(problem);
    } finally {
      deletingInvestigationId = '';
    }
  }
</script>

<svelte:head><title>{pageTitle}</title></svelte:head>

<div class="app-shell" class:nba-theme={activeSport === 'nba'} class:soccer-theme={activeSport === 'soccer'} bind:this={appShellElement}
     style={`--rail-width: ${railWidth}px`}>
  <button class="skip-link" type="button" on:click={() => mainElement?.focus()}>Skip to main content</button>
  <FilmRoomRail {activeSport} {sportTabs} {active} {history} {rootHistory} {playerNamesById} {historyLoading} {historyLoadError}
                {deletingInvestigationId} {showGuidance} bind:mobileHistoryOpen bind:showFullFilmRoom {railScrolls} bind:railWidth
                {appShellElement} {capabilities} {modelState} {modelTitle} {modelDetail} bind:modelSettingsOpen
                {investigationSubject} {investigationSubjectInitials} {investigationWindow} {loadHistory} {openInvestigation}
                {startNewAnalysis} {openGettingStartedGuide} {deleteInvestigation}/>

  <ModelSettingsDialog bind:open={modelSettingsOpen}
                       on:checking={(event) => modelChecking = event.detail}
                       on:failed={(event) => modelCheckError = event.detail}
                       on:applied={(event) => {
                         modelCheckError = '';
                         if (capabilities) capabilities = {...capabilities, configured_provider: event.detail.provider, model_configured: event.detail.configured};
                       }}/>

  <main class={`sport-background ${activeSport}-background`} data-sport-background={activeSport} bind:this={mainElement} tabindex="-1">
    <nav class="sport-tabs" aria-label="Sports">
      {#each sportTabs as sport}
        <button type="button" class:active={activeSport === sport.value} aria-pressed={activeSport === sport.value}
                disabled={!sport.available || busy} on:click={() => switchSport(sport.value)}>
          {#if sportLogos[sport.value]}
            <span class="sport-tab-logo" class:nba-logo={sport.value === 'nba'} class:ncaa-logo={sport.value === 'cfb'}>
              <img src={sportLogos[sport.value]} alt="" aria-hidden="true"/>
            </span>
          {/if}
          <strong>{sport.label}</strong>
        </button>
      {/each}
    </nav>
    <!-- The sport tab above already names the sport; a report page needs only its title. -->
    <header class="topbar" class:report-topbar={!!active}>
      <div>
        <h1>{active ? `${investigationSubject(active, playerNamesById)} report` : `${activeSport === 'nba' ? 'Basketball' : activeSport === 'soccer' ? 'Soccer' : activeSport === 'cfb' ? 'College football' : 'Football'} analysis`}</h1>
      </div>
      {#if analysisOptions && !active}
        <div class="status-chip">
          <Icon name="database" size={16}/>{syncedSeasonCount} {syncedSeasonCount === 1 ? 'season' : 'seasons'} synced · {datasets.length} local files
        </div>
      {/if}
    </header>

    {#if error}
      <div class="error" role="alert">{error}</div>
    {/if}
    {#if workspaceLoadError && !workspaceLoading && (initialWorkspaceReady || serviceOffline)}
      <button class="retry-workspace" type="button" on:click={() => { error = ''; void refresh(); }}>Try Again</button>
    {/if}

    {#if investigationLoading}
      <section class="page-operation-loading" role="status" aria-live="polite" aria-busy="true">
        <span class="library-spinner" aria-hidden="true"></span>
        <div><strong>Loading saved report</strong><small>Retrieving its findings, follow-ups and evidence…</small></div>
      </section>
    {:else if !active && !busy}
      {#snippet subjectCard()}
        <SubjectStep {activeSport} {analysisOptions} {busy} {subjectType} {headToHead} {headToHeadAvailable} {scopeSeasons} {team}
                     bind:teamInput {teamFilter} bind:teamComboboxOpen bind:activeTeamIndex {filteredTeams} {resolvedTeam}
                     {players} {playersLoading} {playerLoadError} {playerSearching} bind:playerInput {playerFilter}
                     bind:playerComboboxOpen bind:activePlayerIndex {filteredPlayers} {selectedPlayerId} {selectedPlayer}
                     bind:playerTeamId {resolvedSubject} {cfbBrowseSeason} {cfbSubdivision} {cfbConference} {cfbHistoryLoading}
                     {compareOptions} bind:compareSubjectId {compareCfbSchool} {comparePlayersLoading} {chooseHeadToHead}
                     {selectSubjectType} {cfbSelectionChanged} {compareCfbChanged} {openTeamCombobox} {updateTeamFilter}
                     {handleTeamKeydown} {selectTeam} {openPlayerCombobox} {updatePlayerFilter} {handlePlayerKeydown}
                     {selectPlayer} {loadPlayers} {searchPlayers} {playerTeamLabel}/>
      {/snippet}
      <section class="ask-panel">
        <div class="intro-grid">
          <GettingStartedGuide {activeSport} {showGuidance} {dismissGuidance} {focusSection}/>
          {#if activeSport === 'cfb'}{@render subjectCard()}{/if}
          {#if activeSport === 'soccer'}
            <div class="soccer-competition-bar">
              <label for="soccer-competition">Competition</label>
              <span class="soccer-competition-select">
                <select id="soccer-competition" value={selectedCompetition} disabled={busy}
                        on:change={(event) => void selectCompetition(event.currentTarget.value)}>
                  {#each soccerCompetitions as competition}
                    <option value={competition.value}>{competition.label}</option>
                  {/each}
                </select>
                <Icon name="chevron-down" size={17}/>
              </span>
            </div>
          {/if}
          <DataManager {activeSport} {sports} {selectedCompetition} {analysisOptions} {setup} {datasets} {comparison} {currentSeason}
                       {resolvedTeam} {cfbConference} {cfbConferenceLabel} {cfbLoading} {cfbError} {cfbTeams} {syncSeasons} {syncDatasets}
                       bind:downloadScope bind:dataManagerOpen bind:customizeSources {syncComplete} {busy} {stage} {workspaceLoading}
                       {workspaceLoadError} {serviceOffline} {scopeDataSynced} {dataStatusDetail} {requiredSources} {visibleSyncDatasets}
                       {sourceGaps} {eligibleSyncDatasets} {allEligibleSyncDatasetsSelected} {seasonLabel} {datasetLabel} {sourceRole}
                       {seasonPackageStatus} {packageCoverage} {packageInstallStatus} {packageEligible} {focusSection} {refresh}
                       {chooseQuickSetup} {toggleSyncSeason} {toggleSyncDataset} {toggleAllSyncDatasets} {syncData} {syncCFBConference}
                       {clearDownloadedData}/>
        </div>
        <div class="guided-workbench">
          <div class="configuration">
            {#if activeSport !== 'cfb'}{@render subjectCard()}{/if}
            <TimeFrameStep {activeSport} {analysisOptions} {subjectType} {selectedPlayer} {headToHead} bind:comparisonMode {comparisonOptions}
                           bind:seasonType {scopeSeasons} {currentSeason} {requiredSeasons} {missingRequiredSeasons} {missingPlayerSeasons}
                           {periodBlocker} {windowsDiffer} {periodStart} bind:headToHeadFirst bind:baseline bind:comparison bind:baselineStartWeek
                           bind:baselineEndWeek bind:comparisonStartWeek bind:comparisonEndWeek bind:splitWeek bind:baselineSegment
                           bind:comparisonSegment bind:baselineStartDate bind:baselineEndDate bind:comparisonStartDate bind:comparisonEndDate
                           {seasonLabel} {availableSegments}/>

            <MetricStep {activeSport} {analysisOptions} {subjectType} {analysisDomain} {visibleDomains} {domainMetrics} {availableMetrics}
                        {availableMetricIds} {recommendedMetricIds} bind:selectedMetrics {selectedAvailableMetricCount}
                        {allAvailableMetricsSelected} bind:customizeMetrics bind:metricsEdited {selectedSplits} {requiredSeasons}
                        {metricInfo} {metricInfoLoading} {metricInfoError} bind:metricInfoElement {selectAnalysisDomain} {toggleMetric}
                        {selectAllMetrics} {useRecommendedMetrics} {explainMetric} {closeMetricInfo} {splitAvailable} {toggleSplit}/>

            <QuestionStep bind:question bind:lastSuggestedQuestion {questionExamples} bind:showAllQuestionExamples/>
          </div>
          <AnalysisBrief {activeSport} {analysisOptions} {subjectType} {selectedPlayer} {resolvedTeam} {teamInput} {headToHead}
                         {compareSubjectLabel} {periodBrief} {analysisDomain} {availableMetrics} {selectedMetrics} {selectedSplits}
                         {readiness} {firstBlocker} {canRun} {displayDomain} {focusSection} {runAnalysis}/>
        </div>
      </section>
    {:else if busy}
      <AnalysisProgress {activeSport} {syncing} {stage} {progress} {runningInvestigationId} {cancelling} {cancelRun}
                        bind:progressHeading/>
    {:else if active}
      {#key active.run.investigation_id}
        <ReportView {active} {conversationThread} {activeSport} {playerNamesById} bind:followup {followupBusy} {pendingFollowup}
                    {stage} {runningInvestigationId} {cancelling} {metricDirections} {firstEvidence} {seasonLabel} {datasetLabel}
                    {displayDomain} {investigationSubject} {subjectName} {investigationWindow} {focusSection} {openInvestigation}
                    {startNewAnalysis} {cancelRun} {sendFollowup}/>
      {/key}
    {/if}
  </main>
  <div class="completion-notifications" role="status" aria-live="polite" aria-atomic="false" aria-relevant="additions">
    {#each completionNotifications as notification (notification.id)}
      <CompletionToast title={notification.title} message={notification.message}
                       ondismiss={() => dismissCompletion(notification.id)}/>
    {/each}
  </div>
</div>
{#if desktopMode && !initialWorkspaceReady}
  <div class="desktop-startup-overlay" role="status" aria-live="polite">
    <div class="desktop-startup-card">
      <div class="desktop-startup-brand"><img class="desktop-startup-logo" src="/favicon.svg" alt=""
                                              aria-hidden="true"/><span>Open Sports <strong>Analyst</strong></span></div>
      <span class="desktop-startup-kicker">Getting Ready</span>
      <h1>Preparing your workspace</h1>
      <p>Loading your sports library and analysis settings.</p>
      <div class="desktop-startup-track" aria-hidden="true"><span></span></div>
      {#if initialWorkspaceError}
        <p class="desktop-startup-error">We couldn't finish opening your workspace. {initialWorkspaceError}</p>
        <button type="button" on:click={() => { initialWorkspaceError = ''; void refresh(); }}>Try Again</button>
      {:else}
        <p class="desktop-startup-status">{startupStatus}</p>
      {/if}
    </div>
  </div>
{/if}

<script lang="ts">
  import {onMount, tick} from 'svelte';
  import {api} from './api';
  import Chart from './Chart.svelte';
  import SupportingEvidence from './SupportingEvidence.svelte';
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
  const supplementalQuestionBanks: QuestionBank = {
    nfl: {
      team: {
        passing: [
          "How much did sacks, turnovers, and pressure-sensitive outcomes influence the passing-efficiency change?",
          "Did the passing offense improve across downs and game situations, or only in a narrow set of favorable contexts?",
          "How did opponent quality and game-to-game volatility affect the apparent passing trend?"
        ],
        rushing: [
          "Did rushing efficiency change across downs, distances, and field position, or only in favorable situations?",
          "How much did opponent quality and game script shape the rushing comparison?",
          "Were changes in negative runs and explosive gains more important than the average yards-per-carry result?"
        ],
        offense: [
          "Which phase—passing, rushing, sacks, or turnovers—accounted for the largest share of the offensive change?",
          "Did the offense improve across score states and field zones, or mostly when game conditions were favorable?",
          "How robust is the offensive trend after accounting for opponent strength and outlier games?"
        ]
      },
      player: {
        quarterback: [
          "How much did sacks, interceptions, and explosive completions shape this quarterback's efficiency change?",
          "Did this quarterback improve across the full game sample, or mainly against particular opponents?",
          "How reliable is the comparison given the number and distribution of recorded dropbacks?"
        ],
        receiving: [
          "Did changes in target opportunity or per-target results matter more to this receiver's production?",
          "How much of this receiver's change came from explosive catches versus repeatable down-to-down efficiency?",
          "How reliable is the receiving trend across games and recorded targets?"
        ],
        running: [
          "Did changes in carry volume or per-carry efficiency matter more to this runner's production?",
          "How much of this runner's change came from explosive carries versus avoiding negative outcomes?",
          "How reliable is the rushing trend across games and recorded attempts?"
        ]
      }
    },
    nba: {
      team: {
        offense: [
          "How much did pace, shooting efficiency, and turnover rate each contribute to the offensive change?",
          "Did the offense perform differently by opponent, venue, rest, or game state?",
          "How robust is the offensive-rating trend after reducing the influence of outlier games?"
        ],
        defense: [
          "Did opponent quality, venue, or rest explain part of the defensive-rating change?",
          "Was the defensive change driven by repeatable possession outcomes or unusually hot and cold opponent shooting?",
          "Which periods and score states contributed most to the defensive trend?"
        ],
        shooting: [
          "How did rim, midrange, and three-point outcomes contribute to the change where shot detail is available?",
          "Did shooting efficiency hold across opponents and venues, or depend on a few favorable matchups?",
          "How much uncertainty comes from three-point variance and the number of recorded attempts?"
        ],
        playmaking: [
          "Did playmaking results change with pace, opponent pressure, or game state?",
          "Were assist gains distributed across the roster or concentrated among a few creators?",
          "How much of the assist-to-turnover change remained after excluding outlier games?"
        ],
        rebounding: [
          "Did rebounding performance vary materially by opponent size, venue, or rest?",
          "Were extra possessions created consistently or concentrated in a few matchup advantages?",
          "How closely did changes on the glass translate into scoring and net-rating results?"
        ],
        turnovers: [
          "Which opponents, periods, and score states produced the largest changes in turnover rate?",
          "Did ball security improve independently of pace and possession volume?",
          "Were live-ball mistakes or a handful of extreme games disproportionately influential where event detail is available?"
        ],
        lineups: [
          "Which high-minute units provide the strongest evidence after accounting for lineup sample size?",
          "Which new, departed, and returning combinations explain the change between periods?",
          "Were lineup results stable across opponents, or driven by a small set of favorable matchups?"
        ]
      },
      player: {
        scoring: [
          "Did opponent, venue, rest, or game state materially change this player's scoring comparison?",
          "How much of the scoring change came from shot volume, free throws, and shooting efficiency?",
          "How robust is the scoring trend after accounting for minutes and outlier games?"
        ],
        shooting: [
          "How did this player's efficiency vary by shot value and distance where shot detail is available?",
          "Did opponent, venue, or rest meaningfully affect this player's shooting results?",
          "How much uncertainty comes from attempt volume and three-point variance?"
        ],
        playmaking: [
          "Did this player's creation change with lineup partners, opponent, or game state?",
          "How did assists and turnovers change relative to minutes and offensive involvement?",
          "Was the playmaking trend broad-based or concentrated in a few high-creation games?"
        ],
        rebounding: [
          "Did this player's rebounding change with minutes, lineup role, or opponent matchup?",
          "How consistently did this player create offensive-board opportunities across games?",
          "Did the rebounding change translate into stronger lineup or team outcomes?"
        ],
        turnovers: [
          "How did this player's turnovers change relative to minutes, usage, and playmaking responsibility?",
          "Did particular opponents or game states account for a disproportionate share of the turnovers?",
          "Was the ball-security trend stable after excluding extreme games?"
        ],
        usage: [
          "Did this player's efficiency rise, hold, or decline as offensive involvement changed?",
          "How did lineup partners and team stint affect this player's role?",
          "Was the usage change consistent across games, opponents, and rest situations?"
        ],
        impact: [
          "How much of this player's impact change can be separated from lineup and opponent context?",
          "Did offense, defense, or a small number of high-leverage games drive the plus/minus trend?",
          "Which high-minute lineup contexts support or contradict the individual impact result?"
        ],
        lineups: [
          "Which high-minute units with this player remain strongest after considering sample size?",
          "Which teammate combinations changed most between the two periods?",
          "Did this player's lineup results persist across opponents and game situations?"
        ]
      }
    }
  };
  const initialQuestion = questionBanks.nfl.team.passing[0];
  let question = initialQuestion;
  let lastSuggestedQuestion = initialQuestion;
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
    customizeSources: boolean; customizeMetrics: boolean; metricsEdited: boolean;
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
  let metricInfo: {
    label: string;
    interpretation: string;
    qualifying_plays: string;
    formula: string;
    higher_is_better: boolean | null;
    limitations: string[]
  } | null = null;
  let metricInfoError = '';
  let metricInfoLoading = false;
  let metricInfoVersion = 0;
  $: setup = analysisOptions?.data_setup;
  $: requiredSources = setup?.required_datasets?.length ? setup.required_datasets : ['play_by_play'];
  $: suggestedSources = [...new Set([...requiredSources, ...(setup?.recommended_datasets ?? [])])];
  $: sourceGaps = [...new Set(requiredSeasons)].flatMap(season => requiredSources.filter(source => !datasets.some(item => (item.sport ?? 'nfl') === activeSport && item.season === season && item.dataset === source)).map(source => `${seasonLabel(season)} · ${datasetLabel(source)}`));
  $: dataReady = Boolean(analysisOptions && requiredSeasons.length && !sourceGaps.length);
  $: readiness = [
    {ready: dataReady, label: dataReady ? 'Required data downloaded' : 'Prepare required data', target: 'data-setup'},
    {ready: Boolean(resolvedSubject), label: resolvedSubject ? 'Subject selected' : 'Choose a team or player', target: 'scope-heading'},
    {
      ready: windowsDiffer && hasSubjectData && hasRequiredData,
      label: windowsDiffer && hasSubjectData && hasRequiredData ? 'Comparison periods selected' : 'Choose available, different periods',
      target: 'comparison-heading'
    },
    {
      ready: selectedAvailableMetricCount > 0,
      label: selectedAvailableMetricCount ? `${selectedAvailableMetricCount} metrics selected` : 'Choose at least one metric',
      target: 'metric-heading'
    },
    {ready: question.trim().length >= 3, label: question.trim().length >= 3 ? 'Question ready' : 'Add your question', target: 'investigation-question'}
  ];
  $: firstBlocker = readiness.find(item => !item.ready);
  $: recommendedMetricIds = analysisOptions?.default_metrics_by_domain?.[analysisDomain] ?? analysisOptions?.default_metrics ?? [];
  $: periodBrief = draftPeriodBrief({
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
    comparisonEndWeek
  });
  $: if (!metricsEdited && analysisOptions) selectedMetrics = availableMetrics.filter(metric => recommendedMetricIds.includes(metric.value)).map(metric => metric.value);
  $: if (analysisOptions && !workspaceLoading) updateReadiness(`${activeSport}:${requiredSeasons.join(',')}:${sourceGaps.join(',')}`, dataReady);

  function updateReadiness(key: string, ready: boolean) {
    if (key === readinessKey) return;
    readinessKey = key;
    if (!ready) dataManagerOpen = true;
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
    try {
      const response = await fetch(`/api/sports/${activeSport}/metrics/${encodeURIComponent(metric.value)}`);
      if (!response.ok) throw new Error('Metric explanation unavailable. Try again.');
      const definition = await response.json();
      if (version === metricInfoVersion) metricInfo = definition;
    } catch (problem) {
      if (version === metricInfoVersion) metricInfoError = String(problem);
    } finally {
      if (version === metricInfoVersion) metricInfoLoading = false;
    }
  }

  function numberLabel(value: number | undefined) {
    return value == null || !Number.isFinite(value) ? 'Not available' : new Intl.NumberFormat(undefined, {maximumFractionDigits: 3}).format(value);
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
    comparisonEndWeek: number
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
      comparisonEndWeek
    } = context;
    if (comparisonMode === 'full_seasons') return `${seasonLabel(baseline)} → ${seasonLabel(comparison)} · every season in this range`;
    if (comparisonMode === 'before_after_milestone') return `${seasonLabel(baseline)} · before vs. after the All-Star break`;
    if (comparisonMode === 'before_after') return `${seasonLabel(baseline)} · weeks 1–${splitWeek - 1} vs. ${splitWeek}–22`;
    if (activeSport === 'nba') return `${seasonLabel(baseline)} ${baselineSegment.replaceAll('_', ' ')} → ${seasonLabel(comparison)} ${comparisonSegment.replaceAll('_', ' ')}`;
    return `${baseline} weeks ${baselineStartWeek}–${baselineEndWeek} → ${comparison} weeks ${comparisonStartWeek}–${comparisonEndWeek}`;
  }

  function keyMetrics(result: Investigation) {
    const selected = new Set(result.run.metrics ?? []);
    return result.aggregate_evidence.filter(item => item.baseline_value != null && item.comparison_value != null && (!selected.size || selected.has(item.metric ?? ''))).slice(0, 6);
  }

  $: requiredSeasons = comparisonMode === 'before_after' || comparisonMode === 'before_after_milestone'
      ? [baseline]
      : comparisonMode === 'full_seasons' && baseline < comparison
          ? Array.from({length: comparison - baseline + 1}, (_, index) => baseline + index)
          : [baseline, comparison];
  $: resolvedTeam = resolveTeam(teamInput);
  $: selectedPlayer = players.find((player) => player.player_id === selectedPlayerId) ?? null;
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
    const local = [...(analysisOptions?.available_seasons ?? [])].sort((left, right) => right - left);
    if (subjectType !== 'player' || !selectedPlayer) return local;
    const played = new Set(playerSeasonsForDomain(selectedPlayer, analysisDomain, activeSport).map(Number));
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
  $: visibleDomains = (analysisOptions?.analysis_domains ?? []).filter((domain) => domainAvailableForSubject(domain, subjectType, selectedPlayer));
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
      && selectedAvailableMetricCount > 0 && dataReady
  );
  $: indexedSeasonCount = new Set(datasets.filter((dataset) => dataset.dataset === 'play_by_play').map((dataset) => dataset.season)).size;
  $: domainMetrics = (analysisOptions?.metrics ?? []).filter((metric) =>
      metric.analysis_domain === analysisDomain && (!metric.subject_types?.length || metric.subject_types.includes(subjectType))
  );
  $: metricCategories = [...new Set(domainMetrics.map((metric) => metric.category))];
  $: availableMetrics = domainMetrics.filter(metric => requiredSeasons.every(season => metric.available_seasons.includes(season)));
  $: availableMetricIds = new Set(availableMetrics.map(metric => metric.value));
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
    try {
      showGuidance = localStorage.getItem('sports-analyst:onboarding:v1') !== 'done';
    } catch { /* Storage is optional. */
    }
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
      syncSeasons: [...syncSeasons], syncDatasets: [...syncDatasets], dataManagerOpen,
      customizeSources, customizeMetrics, metricsEdited
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
          : analysisOptions.syncable_seasons.filter(season => {
            const required = analysisOptions?.data_setup?.required_datasets ?? ['play_by_play'];
            return required.every(source => eligibleSelectedSeasons(source, [season]).length);
          }).slice(0, 2);
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
    if (activeSport === 'nfl') {
      const role = playerRole(player);
      const preferredDomain = role === 'quarterback' ? 'quarterback'
          : role === 'running back' ? 'running'
              : role === 'receiver' ? 'receiving' : analysisDomain;
      selectAnalysisDomain(preferredDomain, true, player);
    } else {
      selectAnalysisDomain(analysisDomain, true, player);
    }
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

  function metricAvailable(metric: MetricOption) {
    return requiredSeasons.every((season) => metric.available_seasons.includes(season));
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
    const primary = questionBanks[sport]?.[type]?.[domain] ?? [initialQuestion];
    const supplemental = supplementalQuestionBanks[sport]?.[type]?.[domain] ?? [];
    const base = [...primary, ...supplemental];
    const contextualized = base.map(example => contextualizeQuestion(example, type, player));
    if (sport !== 'nba' || type !== 'player' || !player) return contextualized;
    const roleQuestion = nbaRoleQuestions[playerRole(player, sport)]?.[domain]?.replaceAll('{player}', player.name);
    return roleQuestion ? [roleQuestion, ...contextualized.filter(example => example !== roleQuestion)] : contextualized;
  }

  function isCuratedExample(value: string) {
    return [questionBanks, supplementalQuestionBanks].some((bank) => Object.values(bank).some((sport) =>
        Object.values(sport).some((subject) => Object.values(subject).some((examples) => examples.includes(value)))
    ));
  }

  function selectAnalysisDomain(domain: string, force = false, player = selectedPlayer) {
    if (analysisDomain === domain && !force) return;
    const replaceSuggested = question === lastSuggestedQuestion || isCuratedExample(question);
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
    const usermeta = specification.usermeta as { chartKind?: string } | undefined;
    if (usermeta?.chartKind === 'metric-rows') {
      return 'Each metric uses its own vertical scale; labels show exact values while seasons run left to right.';
    }
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

  function orderedCharts(charts: Investigation['charts']) {
    const isMetricComparison = (chart: Investigation['charts'][number]) =>
        (chart.specification.usermeta as { chartKind?: string } | undefined)?.chartKind === 'metric-rows';
    return [...charts].sort((left, right) => Number(isMetricComparison(left)) - Number(isMetricComparison(right)));
  }

  function evidenceRoleLabel(play: Evidence) {
    const labels: Record<NonNullable<Evidence['evidence_role']>, string> = {
      typical: 'Typical',
      metric_example: 'Metric example',
      supports_change: 'Supports change',
      counterexample: 'Counterexample'
    };
    return play.evidence_role ? labels[play.evidence_role] : play.supporting ? 'Support' : 'Counter';
  }

  function evidenceGroups(plays: Evidence[]) {
    const definitions = [
      {key: 'baseline', label: 'Reference period'},
      {key: 'comparison', label: 'Comparison window'},
      {key: 'legacy', label: 'Selected evidence'}
    ];
    return definitions.map((definition) => ({
      ...definition,
      plays: plays.filter((play) => definition.key === 'legacy' ? !play.window : play.window === definition.key)
    })).filter((group) => group.plays.length > 0);
  }

  function evidenceCoverage(plays: Evidence[], noun: string) {
    const poolSize = Math.max(0, ...plays.map((play) => play.candidate_pool_size ?? 0));
    return poolSize
        ? `${plays.length} of ${poolSize} qualifying ${noun} selected`
        : `${plays.length} ${noun} selected`;
  }

  function chatTimestamp(createdAt: string) {
    const timestamp = new Date(createdAt);
    if (Number.isNaN(timestamp.getTime())) return '--:--';
    return new Intl.DateTimeFormat(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23'
    }).format(timestamp);
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

  function packageInstallStatus(dataset: string, selectedSeasons = syncSeasons) {
    if (isReferenceDataset(dataset)) {
      return datasets.some((item) => item.dataset === dataset)
          ? {state: 'installed', label: 'Installed'}
          : null;
    }
    const eligibleSeasons = eligibleSelectedSeasons(dataset, selectedSeasons);
    if (!eligibleSeasons.length) return null;
    const local = eligibleSeasons.filter((season) => syncedPackages(season).has(dataset)).length;
    if (!local) return null;
    return local === eligibleSeasons.length
        ? {state: 'installed', label: 'Installed'}
        : {state: 'partial', label: `Local ${local}/${eligibleSeasons.length}`};
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

  function wait(milliseconds: number) {
    return new Promise((resolve) => setTimeout(resolve, milliseconds));
  }

  function isMetricRowChart(specification: Record<string, unknown>) {
    return (specification.usermeta as { chartKind?: string } | undefined)?.chartKind === 'metric-rows';
  }

  function isTrendChart(specification: Record<string, unknown>) {
    if (isMetricRowChart(specification)) return false;
    const encoding = specification.encoding as Record<string, unknown> | undefined;
    const x = encoding?.x as { field?: string } | undefined;
    return x?.field === 'season' || x?.field === 'week';
  }

  function chartSeriesLabels(specification: Record<string, unknown>) {
    const labels = (specification.usermeta as { seriesLabels?: unknown[] } | undefined)?.seriesLabels;
    return Array.isArray(labels) ? labels.map(String) : [];
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
    let lastError: unknown = new Error('The completed investigation is not available yet.');
    for (let attempt = 0; attempt < 8; attempt += 1) {
      try {
        const [result, thread] = await Promise.all([
          api.investigation(investigationId),
          api.investigationThread(investigationId)
        ]);
        if (!isCompleteInvestigation(result, investigationId)) {
          throw new Error('The completed investigation response was incomplete.');
        }
        if (!thread.some((turn) => turn.run.investigation_id === investigationId)) {
          throw new Error('The completed investigation thread was incomplete.');
        }
        active = result;
        conversationThread = thread;
        await refresh();
        dismissGuidance();
        if (active.claims[0]) void inspectFinding(active.claims[0]);
        await scrollToPageTop();
        return true;
      } catch (problem) {
        lastError = problem;
        if (attempt < 7) await wait(Math.min(250 * 2 ** attempt, 2_000));
      }
    }
    throw lastError;
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
        return loadCompletedInvestigation(investigationId);
      }
      if (attempt < 29) await wait(2_000);
    }
    return false;
  }

  function stream(
      url: string,
      complete: () => Promise<void>,
      recover?: () => Promise<boolean>,
      onSettled?: () => void,
      timeoutMessage = 'The investigation is still unavailable after the progress stream timed out. Refresh to check again.',
      disconnectMessage = 'The progress stream disconnected and the investigation could not be recovered. Refresh to check again.'
  ) {
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
        await recoverOrFail(timeoutMessage);
      }
    };
    source.onerror = () => {
      void recoverOrFail(disconnectMessage);
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
          () => loadCompletedInvestigation(investigation_id).then(() => undefined),
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
    syncing = true;
    syncComplete = false;
    stage = 'Preparing data sync';
    progress = 0.03;
    try {
      const {job_id, timeout_seconds} = await api.sync(activeSport, requestedSeasons, requestedDatasets);
      const timeout = Math.max(30, Math.min(3_600, Number(timeout_seconds) || 120));
      stream(
          `/api/dataset-jobs/${job_id}/events?timeout_seconds=${timeout}`,
          async () => {
            await refresh();
            syncComplete = true;
          },
          undefined,
          () => {
            syncing = false;
          },
          'The data sync is still running after its extended progress window. Refresh the data catalog to check completed packages.',
          'The data-sync progress connection was interrupted. Refresh the data catalog to check completed packages.'
      );
    } catch (problem) {
      error = String(problem);
      busy = false;
      syncing = false;
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
      mobileHistoryOpen = false;
      dismissGuidance();
      if (active.claims[0]) void inspectFinding(active.claims[0]);
      await scrollToPageTop();
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

  async function openGettingStartedGuide() {
    await openInvestigation(null);
    showGuidance = true;
    mobileHistoryOpen = false;
    await focusSection('getting-started');
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
          () => loadCompletedInvestigation(investigation_id).then(() => undefined),
          () => pollInvestigation(investigation_id),
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

<div class="app-shell" class:nba-theme={activeSport === 'nba'}>
  <aside class="rail" class:mobile-history-open={mobileHistoryOpen}>
    <div class="brand"><img class="mark" src="/favicon.svg" alt="" aria-hidden="true"/>
      <div><strong>Open Sports</strong><span>Analyst</span></div>
    </div>
    <nav aria-label="Primary">
      <button class="sidebar-action new-investigation" class:active={!active} on:click={startNewAnalysis}>
        <span class="sidebar-action-icon"><Icon name="clipboard-plus" size={20}/></span>
        <span class="sidebar-action-label">New Analysis</span>
      </button>
      <button class="sidebar-action getting-started-button" class:active={!active && showGuidance} type="button"
              aria-expanded={!active && showGuidance} aria-controls="getting-started"
              on:click={openGettingStartedGuide}>
        <span class="sidebar-action-icon"><Icon name="book-open" size={20}/></span>
        <span class="sidebar-action-label">Getting Started</span>
      </button>
      <button class="mobile-history-toggle" type="button" aria-expanded={mobileHistoryOpen} on:click={() => mobileHistoryOpen = !mobileHistoryOpen}>Recent Analyses
        ({rootHistory.length})
      </button>
      <div class="nav-label">
        <Icon name="history" size={15}/>
        Film Room Gallery
      </div>
      {#each rootHistory.slice(0, 8) as item}
        <div class="recent-report">
          <button class="recent-report-link" class:active={active ? rootIdFor(active) === item.run.investigation_id : false}
                  on:click={() => openInvestigation(item)}>
                        <span class="recent-subject-badge"
                              title={investigationSubject(item, playerNamesById)}>{investigationSubjectInitials(item, playerNamesById)}</span>
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
            {#if deletingInvestigationId === item.run.investigation_id}<span class="button-spinner" aria-label="Deleting investigation"></span>{:else}
              <Icon name="trash" size={15}/>
            {/if}
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

  <main class={`sport-background ${activeSport}-background`} data-sport-background={activeSport}>
    <nav class="sport-tabs" aria-label="Sports">
      {#each sports as sport}
        <button type="button" class:active={activeSport === sport.value} aria-pressed={activeSport === sport.value}
                disabled={!sport.available || busy} on:click={() => switchSport(sport.value)}>
          <strong>{sport.label}</strong>
          {#if sport.value === 'nba'}<small
              title={sport.live_message ?? 'Analysis uses downloaded data; optional live sources can add detail.'}>{sport.live_available ? 'Live enrichments ready' : 'Bulk data mode'}</small>{/if}
        </button>
      {/each}
    </nav>
    <header class="topbar">
      <div><span class="eyebrow">{activeSport.toUpperCase()} · Evidence Workbench</span>
        <h1>{active ? `${investigationSubject(active, playerNamesById)} investigation` : `${activeSport === 'nba' ? 'Basketball' : 'Football'} analysis`}</h1>
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
          <div class="ask-copy"><span class="eyebrow">Your Next Question, Answered</span>
            <h2>See what changed. Understand why.</h2>
            <p>Compare a team or player across time, then explore the numbers and plays behind the answer.</p>
          </div>
          {#if showGuidance}
            <section class="getting-started" id="getting-started" tabindex="-1" aria-label="How it works">
              <div class="section-heading">
                <div>
                  <span class="eyebrow">Quick Start</span>
                  <h3>Build an evidence-backed investigation</h3>
                  <p>Start with a focused comparison. You can refine it or ask follow-up questions after the first answer.</p>
                </div>
                <button type="button" on:click={dismissGuidance}>Dismiss guide</button>
              </div>
              <ol class="guide-steps">
                <li>
                  <span class="guide-icon"><Icon name="database" size={22}/></span>
                  <div><small>Step 1</small><b>Prepare the Right Data</b>
                    <p>Download both seasons and the recommended sources. Required sources unlock the analysis; recommended sources add player names and context.</p>
                    <button type="button" class="guide-step-action" on:click={() => focusSection('data-setup')}>
                      Open Data Setup
                      <Icon name="arrow-right" size={15}/>
                    </button>
                  </div>
                </li>
                <li>
                  <span class="guide-icon"><Icon name="clipboard-plus" size={22}/></span>
                  <div><small>Step 2</small><b>Define a Focused Comparison</b>
                    <p>Choose one team or player, two distinct periods, and the metrics that best match what you want to understand.</p>
                    <button type="button" class="guide-step-action" on:click={() => focusSection('scope-heading')}>
                      Choose a subject
                      <Icon name="arrow-right" size={15}/>
                    </button>
                  </div>
                </li>
                <li>
                  <span class="guide-icon"><Icon name="search" size={22}/></span>
                  <div><small>Step 3</small><b>Ask, Run, and Inspect</b>
                    <p>Ask what changed or why. Then open any finding to inspect its calculations, representative plays, and limitations.</p>
                    <button type="button" class="guide-step-action" on:click={() => focusSection('investigation-question')}>
                      Write your question
                      <Icon name="arrow-right" size={15}/>
                    </button>
                  </div>
                </li>
              </ol>
              <div class="guide-outcome">
                <Icon name="sparkles" size={19}/>
                <p><strong>What a strong investigation includes</strong><span>A direct answer, the most important drivers, counterevidence, charts, and source-backed examples.</span>
                </p>
              </div>
            </section>
          {/if}
          <details id="data-setup" tabindex="-1" class="data-manager" class:quick-setup={!customizeSources} class:nba-data-manager={activeSport === 'nba'}
                   bind:open={dataManagerOpen}>
            <summary>
              <span><strong>{dataReady ? 'Data Ready · Manage Data' : 'Prepare Data'}</strong><small>{dataReady ? 'Required sources are downloaded for these periods.' : 'Start with the essentials. Add more detail whenever you need it.'}</small></span><b>{workspaceLoading ? 'Loading data…' : `${datasets.length} local files`}
              <i>
                <Icon name="chevron-down" size={16}/>
              </i></b></summary>
            <div class="onboarding">
              <div class="data-setup-header">
                <div class="sync-guidance">
                  <strong>{setup?.label ?? 'Recommended Data'}</strong><span>{setup?.description ?? 'Choose seasons and download their recorded plays to begin.'}</span>
                </div>
                {#if !workspaceLoading && analysisOptions}
                  <div class="setup-mode">
                    <button type="button" aria-pressed={!customizeSources} on:click={chooseQuickSetup}>Recommended setup</button>
                    <button type="button" aria-expanded={customizeSources} on:click={() => customizeSources = !customizeSources}>Customize data sources</button>
                  </div>
                {/if}
              </div>
              {#if workspaceLoading}
                <div class="library-loading" role="status" aria-live="polite">
                  <span class="library-spinner" aria-hidden="true"></span>
                  <span><strong>Loading Data Catalog</strong><small>{workspaceLoadError || 'Checking available seasons, packages, and local file coverage…'}</small></span>
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
                {#if syncComplete}
                  <div class="sync-success" role="status"><strong>Download finished</strong>
                    <p>Your data library has been refreshed. Check any missing sources below before running.</p>
                    <button type="button" on:click={() => { dataManagerOpen = false; void focusSection('scope-heading'); }}>Continue building analysis</button>
                  </div>
                {/if}
                {#if sourceGaps.length}
                  <div class="data-readiness-row"><p class="data-gaps">Needed for your current comparison: {sourceGaps.join('; ')}.</p>
                    <button type="button" on:click={() => { syncSeasons = [...new Set(requiredSeasons)]; chooseQuickSetup(); }}>Select data for this comparison
                    </button>
                  </div>
                {/if}
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
                      <button class="package-toggle" type="button" disabled={!eligibleSyncDatasets.length}
                              on:click={() => { customizeSources = true; toggleAllSyncDatasets(); }}>
                        {allEligibleSyncDatasetsSelected ? 'Deselect all' : 'Select all'}
                      </button>
                    </legend>
                    <div class="dataset-options">
                      {#each (customizeSources ? analysisOptions?.syncable_datasets ?? [] : suggestedSources.filter(source => analysisOptions?.syncable_datasets.includes(source))) as dataset}
                        {@const installStatus = packageInstallStatus(dataset, syncSeasons)}
                        <label><input type="checkbox" aria-label={datasetLabel(dataset)}
                                      checked={syncDatasets.includes(dataset)}
                                      disabled={!packageEligible(dataset, syncSeasons)}
                                      on:change={() => toggleSyncDataset(dataset)}/><span>
                          <span class="dataset-name"><span>{datasetLabel(dataset)}</span>
                            {#if installStatus}
                              <b class:partial={installStatus.state === 'partial'}
                                 aria-label={`${datasetLabel(dataset)} local status: ${installStatus.label}`}>{installStatus.label}</b>
                            {/if}
                          </span>
                          <small><span class="source-role"
                                       class:required-source={requiredSources.includes(dataset)}>{sourceRole(dataset)}</span> · {packageCoverage(dataset, syncSeasons)}</small>
                          {#if setup?.descriptions[dataset]}<small>{setup.descriptions[dataset]}</small>{/if}</span></label>
                      {/each}
                    </div>
                  </fieldset>
                </div>
                <button disabled={!syncSeasons.length || !syncDatasets.length} on:click={syncData}>
                  Download {syncDatasets.filter(source => packageEligible(source)).length} sources for {syncSeasons.length} seasons
                  <Icon name="database-import" size={18}/>
                </button>
              {/if}
            </div>
          </details>
        </div>
        <div class="guided-workbench">
          <div class="configuration">
            <section class="scope-card" aria-labelledby="scope-heading">
              <div class="scope-heading">
                <div><span class="eyebrow">01 · Subject</span>
                  <h3 id="scope-heading" tabindex="-1">Who do you want to understand?</h3></div>
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
                        {#if playersLoading}<span class="button-spinner" aria-hidden="true"></span>{:else}
                          <Icon name="chevron-down" size={17}/>
                        {/if}
                      </button>
                      {#if playerComboboxOpen}
                        <div class="team-options" id="sport-player-options" role="listbox" aria-label={`${activeSport.toUpperCase()} players`}>
                          {#if playersLoading}
                            <div class="combobox-loading" role="status"><span class="button-spinner" aria-hidden="true"></span>
                              <span>Loading {activeSport.toUpperCase()} players…</span></div>
                          {:else if playerLoadError}
                            <div class="combobox-error"><span>Player list is unavailable.</span>
                              <button type="button" on:mousedown|preventDefault={() => loadPlayers()}>Retry</button>
                            </div>
                          {:else}
                            {#each filteredPlayers as player, index}
                              <button id={`player-option-${player.player_id}`} type="button" role="option"
                                      aria-selected={selectedPlayerId === player.player_id}
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
              </div>
            </section>
            <section class="scope-card" aria-labelledby="comparison-heading">
              <div class="scope-heading">
                <div><span class="eyebrow">02 · Comparison</span>
                  <h3 id="comparison-heading" tabindex="-1">Choose the periods to compare</h3></div>
              </div>
              <p>Your reference period is the starting point. The comparison period shows what changed.</p>
              <div class="scope-controls">
                <label>Comparison type
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

              <p class="section-help">{analysisOptions?.comparison_windows.find(option => option.value === comparisonMode)?.description ?? ''}</p>
              {#if scopeSeasons.length}
                {#if activeSport === 'nba'}
                  <div class="window-grid">
                    <fieldset>
                      <legend>{comparisonMode === 'full_seasons' ? 'Range start' : 'Reference period'}</legend>
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
                      <label>Season<select bind:value={comparison} disabled={comparisonMode === 'before_after_milestone'} on:change={() => {
                    if (!availableSegments(comparison).some(segment => segment.value === comparisonSegment)) comparisonSegment = availableSegments(comparison)[0]?.value ?? 'regular_season';
                  }}>
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
                    <div class="window-summary"><span>Reference period</span><strong>{baseline} · Weeks 1–{splitWeek - 1}</strong></div>
                    <div class="window-summary"><span>Comparison</span><strong>{baseline} · Weeks {splitWeek}–22</strong></div>
                  </div>
                {:else}
                  <div class="window-grid">
                    <fieldset>
                      <legend>{comparisonMode === 'full_seasons' ? 'Range start' : 'Reference period'}</legend>
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
                <div><span class="eyebrow">03 · Focus</span>
                  <h3 id="metric-heading" tabindex="-1">Choose {subjectType === 'player' ? 'player metrics' : 'what to measure'}</h3></div>
                <div class="metric-actions">
                  <button type="button" aria-expanded={customizeMetrics} on:click={() => customizeMetrics = !customizeMetrics}>Customize metrics</button>
                  {#if customizeMetrics}
                    <button class="text-button" type="button" on:click={selectAllMetrics} disabled={allAvailableMetricsSelected || !availableMetrics.length}>
                      <Icon name="clipboard-plus" size={16}/>
                      {allAvailableMetricsSelected ? 'All Available Selected' : 'Select All Metrics'}
                    </button>
                    <button class="text-button" type="button" on:click={useRecommendedMetrics}>
                      <Icon name="sparkles" size={16}/>
                      Use Recommended Metrics
                    </button>
                  {/if}
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
              <p class="section-help">
                <strong>{subjectType === 'player' ? 'Only player-compatible metrics are shown.' : 'Recommended metrics are selected by default.'}</strong>
                Start here, or customize your selection. Open “About” to learn what a metric means and how it is calculated.</p>
              <div class="metric-groups">
                {#each [...new Set(domainMetrics.filter(metric => customizeMetrics || recommendedMetricIds.includes(metric.value) || selectedMetrics.includes(metric.value)).map(metric => metric.category))] as category}
                  <section class="metric-group" role="group" aria-label={category}>
                    <h4 class="metric-group-title">{category}</h4>
                    {#each domainMetrics.filter((metric) => metric.category === category && (customizeMetrics || recommendedMetricIds.includes(metric.value) || selectedMetrics.includes(metric.value))) as metric}
                      <label class:unavailable={!availableMetricIds.has(metric.value)} title={metric.description}>
                        <input type="checkbox" checked={selectedMetrics.includes(metric.value)} disabled={!availableMetricIds.has(metric.value)}
                               on:change={() => toggleMetric(metric.value)}/>
                        <span><strong>{metric.label}</strong><small>{metric.description}</small>
                          {#if !availableMetricIds.has(metric.value)}<small>Unavailable for one or more selected periods. Check data sources or choose another metric.</small>{/if}</span>
                      </label>
                      <button class="metric-explain" type="button" on:click={() => explainMetric(metric)}>About {metric.label}</button>
                    {/each}
                  </section>
                {/each}
              </div>
              {#if metricInfoLoading || metricInfo || metricInfoError}
                <section class="metric-info" aria-label="Metric explanation" aria-live="polite">
                  <button type="button" on:click={() => { metricInfoVersion += 1; metricInfo = null; metricInfoError = ''; metricInfoLoading = false; }}>Close
                    explanation
                  </button>
                  {#if metricInfoLoading}<p>Loading metric explanation…</p>{:else if metricInfoError}<p role="alert">{metricInfoError}</p>{:else if metricInfo}
                    <h4>{metricInfo.label}</h4>
                    <p>{metricInfo.interpretation}</p>
                    <dl>
                      <dt>Included sample</dt>
                      <dd>{metricInfo.qualifying_plays}</dd>
                      <dt>Direction</dt>
                      <dd>{metricInfo.higher_is_better == null ? 'Depends on context' : metricInfo.higher_is_better ? 'Higher is generally better' : 'Lower is generally better'}</dd>
                      <dt>Formula</dt>
                      <dd><code>{metricInfo.formula}</code></dd>
                    </dl>
                    {#each metricInfo.limitations ?? [] as limitation}<p>{limitation}</p>{/each}
                  {/if}
                </section>
              {/if}
              {#if customizeMetrics}
                <button class="text-button clear-metrics" type="button" on:click={() => { metricsEdited = true; selectedMetrics = []; }}>
                  <Icon name="wand" size={16}/>
                  Clear All Metrics
                </button>
              {/if}
              {#if analysisOptions && selectedAvailableMetricCount === 0}
                <p class="selection-warning">Choose at least one available metric to run your analysis.</p>
              {/if}
              <details class="breakdown-details">
                <summary>Optional breakdowns</summary>
                {#if activeSport === 'nfl' && subjectType === 'player'}
                  <div class="split-selector player-diagnostic-note">
                    <div><h4>Player Context</h4>
                      <p>Player comparisons use attributed plays plus compatible synced player statistics. Team-oriented diagnostic cuts are disabled for
                        player investigations.</p></div>
                  </div>
                {:else}
                  <div class="split-selector">
                    <div><h4>Explore situations</h4>
                      <p>Leave these empty for automatic recommendations. Select specific situations to include only those breakdowns.</p></div>
                    <div class="split-options">
                      {#each analysisOptions?.split_dimensions ?? [] as split}
                        <label class:unavailable={!splitAvailable(split.available_seasons, requiredSeasons)} title={split.description}>
                          <input type="checkbox" checked={selectedSplits.includes(split.value)} disabled={!splitAvailable(split.available_seasons, requiredSeasons)}
                                 on:change={() => toggleSplit(split.value)}/>
                          <span>{split.label}</span>
                        </label>
                      {/each}
                    </div>
                  </div>
                {/if}
              </details>
            </section>

            <div class="question-field">
              <span class="eyebrow">04 · Question</span>
              <div class="question-heading">
                <label for="investigation-question">Your Question:</label>

              </div>
              <div class="question-examples" aria-label="Example questions">
                {#each questionExamples.slice(0, showAllQuestionExamples ? questionExamples.length : 3) as example}
                  <button type="button" on:click={() => { question = example; lastSuggestedQuestion = example; }}>{example}</button>
                {/each}
                {#if questionExamples.length > 3}
                  <button class="question-more" type="button" aria-expanded={showAllQuestionExamples}
                          on:click={() => showAllQuestionExamples = !showAllQuestionExamples}>
                    {showAllQuestionExamples ? 'Show fewer examples' : `Show ${questionExamples.length - 3} more examples`}
                  </button>
                {/if}
              </div>
              <textarea id="investigation-question" bind:value={question} rows="3"></textarea>
            </div>
          </div>
          <aside class="analysis-brief" aria-label="Analysis brief">
            <span class="eyebrow">Your Analysis</span>
            <h3>Analysis brief</h3>
            <dl>
              <dt>Subject</dt>
              <dd>{subjectType === 'player' ? selectedPlayer?.name ?? 'Choose a player' : teamInput || 'Choose a team'}</dd>
              <dt>Periods</dt>
              <dd>{periodBrief}</dd>
              <dt>Focus</dt>
              <dd>{displayDomain(analysisDomain)}</dd>
              <dt>Metrics</dt>
              <dd>{availableMetrics.filter(metric => selectedMetrics.includes(metric.value)).map(metric => metric.label).join(', ') || 'Choose metrics'}</dd>
              <dt>Breakdowns</dt>
              <dd>{selectedSplits.length ? selectedSplits.map(value => analysisOptions?.split_dimensions.find(item => item.value === value)?.label ?? value).join(', ') : 'Recommended automatically'}</dd>
            </dl>
            <h4>Ready to run?</h4>
            <ul class="readiness">
              {#each readiness as item}
                <li>
                  <button type="button" class:ready={item.ready} on:click={() => focusSection(item.target)}><span
                      aria-label={item.ready ? 'Complete' : 'Needed'}>{item.ready ? '✓' : '○'}</span>{item.label}</button>
                </li>
              {/each}
            </ul>
            <p class="readiness-message"
               aria-live="polite">{firstBlocker ? firstBlocker.label : 'Everything is ready. Your analysis will include supporting evidence.'}</p>
            <button class="primary" disabled={!canRun} on:click={runAnalysis}>Run analysis
              <Icon name="player-play" size={19}/>
            </button>
          </aside>
        </div>
      </section>
    {:else if busy}
      <section class="working" aria-live="polite" aria-busy="true">
        <div class="field-lines" aria-hidden="true"></div>
        <div class="working-layout">
          <div class="working-copy">
            <span class="eyebrow">{syncing ? 'Downloading Data' : 'Analysis in Progress'}</span>
            <h2>{stage}</h2>
            <div class="progress" role="progressbar" aria-label={syncing ? 'Download progress' : 'Investigation progress'} aria-valuemin="0" aria-valuemax="100"
                 aria-valuenow={Math.round(progress * 100)}><i style={`width:${Math.max(4, progress * 100)}%`}></i></div>
            <p>{syncing ? 'Each source is downloaded and checked before it is added to your library.' : 'Comparing your periods and checking the evidence behind each finding.'}</p>
          </div>
          <div class="play-visual" class:nba-loading={activeSport === 'nba'} aria-hidden="true">
            <div class="play-caption">
              <span>{activeSport === 'nba' ? 'LIVE ANALYSIS POSSESSION' : 'LIVE ANALYSIS DRIVE'}</span><b>{Math.round(progress * 100)}%</b></div>
            {#if activeSport === 'nba'}
              <BasketballLoadingAnimation/>
            {:else}
              <img class="catch-scene" src="/open-sports-analyst-loader.svg" alt=""/>
            {/if}
            <div class="analysis-live"><i></i><span>{syncing ? 'Download still running…' : 'Analysis still running…'}</span></div>
          </div>
        </div>
      </section>
    {:else if active}
      <section class="report-hero">
        <div class="report-summary">
          <span class="eyebrow">Final Read · {active.fallback_used ? 'Deterministic' : active.model_id}</span>
          <h2>The answer</h2>
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
      <section class="key-metrics" aria-label="Key metric changes">
        {#each keyMetrics(active) as metric}
          <article><h3>{metric.label}</h3>
            <div><span>Reference period <b>{numberLabel(metric.baseline_value)}</b></span><span>Comparison <b>{numberLabel(metric.comparison_value)}</b></span></div>
            <p>Change: <strong>{numberLabel(metric.value)}</strong> {metric.unit ?? ''}</p>
            <small>Sample: {metric.sample_size == null ? 'Not recorded' : metric.sample_size.toLocaleString()}</small></article>
        {:else}<p>No comparable metric values are available for these periods. Review the limitations below or adjust your periods and data sources.</p>{/each}
      </section>
      <div class="report-grid">
        <section class="findings">
          <div class="section-title"><span>Core Findings</span><small>{active.claims.length} evidence-bound claims</small></div>
          <details class="reading-guide">
            <summary>How to read these findings</summary>
            <p>Measured findings are calculated from recorded data. Interpretations describe possible explanations, not proof of cause. Confidence describes how
              strongly the available evidence supports a finding; it is not a probability or a guarantee.</p></details>
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
                  class:interpretation={claim.claim_type === 'interpretation'}
                  title={claim.claim_type === 'measured' ? 'Calculated from recorded data.' : 'An explanation of the evidence, not proof of cause.'}>{claim.claim_type}</span><i
                  title="Confidence describes the strength of the evidence for this finding. It is not a probability or a guarantee.">{claim.confidence}
                confidence</i></span><span
                  class="finding-statement">{claim.statement}</span><span class="citations">{#each claim.evidence_ids as id}<span>{id.slice(0, 18)}
                …</span>{/each}</span></span>
              <span class="finding-inspect"><Icon name="search" size={17}/></span>
            </button>
            {#if selectedClaimId === claim.claim_id}
              <div class="mobile-evidence">
                <SupportingEvidence items={selectedEvidenceItems} loading={evidenceLoading} error={evidenceError} retry={() => inspectFinding(claim)}/>
              </div>
            {/if}
          {:else}<p class="empty-state">No findings could be supported by these data. Check the methodology below, then try different periods or download additional
            sources.</p>
            <button type="button" on:click={startNewAnalysis}>Adjust analysis</button>
          {/each}
        </section>
        <aside class="evidence-panel desktop-evidence" class:empty-evidence-panel={!selectedClaim}>
          {#if selectedClaim}<p class="selected-finding-label">Finding {active.claims.indexOf(selectedClaim) + 1}</p>
            <SupportingEvidence items={selectedEvidenceItems} loading={evidenceLoading} error={evidenceError}
                                retry={() => selectedClaim && inspectFinding(selectedClaim)}/>
          {:else}<p class="evidence-panel-empty">Select a finding to see its supporting evidence.</p>{/if}
        </aside>
      </div>
      <section class="charts">
        <div class="section-title"><span>Charts</span>
          {#if active.charts.length}<small>Hover a point to inspect its values.</small>{/if}
        </div>
        {#if !active.charts.length}<p class="empty-state">No charts were produced for this analysis. The findings and supporting evidence above contain the available
          measurements.</p>{/if}
        <div class="chart-grid">
          {#each orderedCharts(active.charts) as chart}
            <article class:chart-trend={isTrendChart(chart.specification)}
                     class:chart-metric-group={isMetricRowChart(chart.specification)}><h3>{chart.title}</h3>
              {#if chartGuidance(chart.specification)}<p class="chart-note">{chartGuidance(chart.specification)}</p>{/if}
              {#if chartSeriesLabels(chart.specification).length}
                <div class="chart-series-key" aria-label="Comparison windows">
                  {#each chartSeriesLabels(chart.specification) as label, index}
                    <span class:comparison-series={index === chartSeriesLabels(chart.specification).length - 1}>
                      <i aria-hidden="true"></i><small>{index === 0 ? 'Reference period' : index === chartSeriesLabels(chart.specification).length - 1 ? 'Comparison' : 'Season'}</small>
                      <strong>{label}</strong>
                    </span>
                  {/each}
                </div>
              {/if}
              <Chart specification={chart.specification} team={active.run.subject?.team_id ?? active.run.scope.team}
                     sport={active.run.sport ?? 'nfl'}/>
            </article>
          {/each}
        </div>
      </section>
      <section class="plays">
        <div class="section-title"><span>Representative {activeSport === 'nba' ? 'Possessions' : 'Plays'}</span><small>Examples from both periods—not the entire
          sample</small>
        </div>
        <p class="section-help">Select a play to inspect it. Counterexamples show outcomes that run against the overall trend.</p>
        {#if !active.play_evidence.length}<p class="empty-state">No representative plays are available for this analysis. Review the numerical evidence and source
          limitations above.</p>{/if}
        {#each evidenceGroups(active.play_evidence) as group}
          <div class="evidence-window-group">
            <div class="evidence-window-heading">
              <strong>{group.label}</strong>
              <small>{evidenceCoverage(group.plays, activeSport === 'nba' ? 'possessions' : 'plays')}</small>
            </div>
            <div class="play-list">
              {#each group.plays as play}
                <button class:selected={selectedPlay?.evidence_id === play.evidence_id}
                        aria-expanded={selectedPlay?.evidence_id === play.evidence_id}
                        aria-label={`Inspect ${evidenceRoleLabel(play)} evidence from ${play.game_id ?? 'selected game'}`}
                        on:click={() => openPlay(play)}><span class="play-tag"
                                                              class:supporting={play.evidence_role ? play.evidence_role !== 'counterexample' : play.supporting}
                                                              class:typical={play.evidence_role === 'typical'}>{evidenceRoleLabel(play)}</span>
                  <span class="play-reference"><strong>{play.game_id}</strong><small>Play #{play.play_id}</small></span>
                  <span class="play-description"><span>{play.description}</span>
                    {#if play.selection_reason}<small>{play.selection_reason}</small>{/if}</span><b
                      class="play-epa">{play.epa != null ? `${play.epa.toFixed(2)} EPA` : play.metric_value != null ? `${play.metric_value.toFixed(1)} ${play.selection_metric ?? 'value'}` : 'Play evidence'}</b>
                </button>
              {/each}
            </div>
          </div>
        {/each}
        {#if selectedPlay}
          {#if selectedPlay.visualization?.sport === 'nba'}
            <BasketballPlayTablet play={selectedPlay} onclose={() => selectedPlay = null}/>
          {:else}
            <PlayTablet play={selectedPlay} onclose={() => selectedPlay = null}/>
          {/if}
        {/if}
      </section>
      <details class="methodology">
        <summary>How this analysis was calculated</summary>
        <h3>Methodology and limitations</h3>
        {#each active.methodological_caveats as caveat}<p>{caveat}</p>{/each}
        <p>Reference period means the baseline used to calculate change. Measured findings come from recorded data; interpretations describe possible
          explanations.</p>
        <h3>Sources</h3>
        {#each active.dataset_manifests ?? [] as manifest}<p>{datasetLabel(manifest.dataset)} · {manifest.season} · {manifest.row_count.toLocaleString()}
          rows<small>{manifest.attribution ?? ''} {manifest.license ?? ''}</small><small>{manifest.source_url ?? ''}</small><small>Source
            record: {manifest.manifest_id} · SHA-256: {manifest.sha256}</small></p>{:else}<p>Source details are available in the exported report.</p>{/each}
        <h3>Analysis tools</h3>
        {#each active.executions ?? [] as execution}
          <details class="execution-detail">
            <summary>{execution.tool.replaceAll('_', ' ')}{execution.duration_ms != null ? ` · ${execution.duration_ms} ms` : ''}</summary>
            <p>Version: {execution.version ?? 'Not recorded'}</p>
            <pre>{JSON.stringify(execution.parameters ?? {}, null, 2)}</pre>
            {#if execution.sql}
              <pre>{execution.sql}</pre>
            {/if}<p>Sources: {execution.dataset_manifest_ids?.join(', ') ?? 'See source records above'}</p></details>
        {:else}<p>No separate execution records were saved with this report.</p>{/each}
      </details>
      <section class="conversation" aria-label="Investigation conversation">
        <div class="conversation-header">
          <div><span class="eyebrow">Investigation Thread</span>
            <h2>{investigationSubject(active, playerNamesById)} Film Room</h2>
            <p>The initial analysis and every follow-up are saved together. Select any analyst response to inspect its report and evidence.</p>
          </div>
          <span class="conversation-count">{Math.max(0, conversationThread.length - 1)} follow-up{conversationThread.length === 2 ? '' : 's'}</span>
        </div>
        <div class="conversation-messages" aria-live="polite">
          {#each conversationThread as turn, index}
            <article class="chat-row user-row">
              <span class="chat-avatar user-avatar">You</span>
              <div class="chat-bubble user-bubble">
                <div class="chat-message-meta"><small>{index === 0 ? 'Initial question' : `Follow-up ${index}`}</small>
                  <time datetime={turn.run.created_at}>{chatTimestamp(turn.run.created_at)}</time>
                </div>
                <p>{turn.run.question}</p></div>
            </article>
            <div class="chat-row analyst-row">
              <span class="chat-avatar analyst-avatar"><Icon name="sports-analyst" size={24}/></span>
              <button class="chat-bubble analyst-bubble" class:selected={active.run.investigation_id === turn.run.investigation_id}
                      type="button" on:click={() => openInvestigation(turn)}>
                <div class="chat-message-meta"><small>Open Sports Analyst · {turn.fallback_used ? 'Deterministic' : turn.model_id}</small>
                  <time datetime={turn.run.created_at}>{chatTimestamp(turn.run.created_at)}</time>
                </div>
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
    {/if}
  </main>
</div>

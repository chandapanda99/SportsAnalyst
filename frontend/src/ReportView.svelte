<script lang="ts">
  import {tick} from 'svelte';
  import {api} from './api';
  import Chart from './Chart.svelte';
  import {chartLayout} from './chartLayout';
  import Icon from './Icon.svelte';
  import ModelText from './ModelText.svelte';
  import PlayerPortrait from './PlayerPortrait.svelte';
  import SupportingEvidence from './SupportingEvidence.svelte';
  import TabletPanel from './TabletPanel.svelte';
  import {changeVerdict, headToHeadLeader, headToHeadSeasons, metricColumns, metricFormatter, periodLabel} from './metricFormat';
  import {gameLabel} from './reportText';
  import {
    chartGuidance,
    chatTimestamp,
    evidenceCoverage,
    evidenceGroups,
    evidenceRoleLabel,
    isMetricRowChart,
    isTrendChart,
    keyMetrics,
    orderedCharts
  } from './reportHelpers';
  import type {PrefetchedEvidence} from './reportHelpers';
  import {revealPanel} from './revealPanel';
  import type {Claim, Evidence, Investigation, InvestigationSummary} from './types';

  type SavedReport = Investigation | InvestigationSummary;

  export let active: Investigation;
  export let conversationThread: Investigation[];
  export let activeSport: string;
  export let playerNamesById: Map<string, string>;
  export let followup: string;
  export let followupBusy: boolean;
  export let pendingFollowup: string;
  export let stage: string;
  export let runningInvestigationId: string;
  export let cancelling: boolean;
  /** Whether a higher value is better, by `sport:metric`; it decides who is ahead in a head-to-head. */
  export let metricDirections: Record<string, boolean | null>;
  export let firstEvidence: PrefetchedEvidence | null = null;
  export let seasonLabel: (season: number) => string;
  export let datasetLabel: (dataset: string) => string;
  export let displayDomain: (domain?: string) => string;
  export let investigationSubject: (item: SavedReport, playerNames?: Map<string, string>) => string;
  export let subjectName: (item: SavedReport, subject: Investigation['run']['subject'], playerNames?: Map<string, string>) => string;
  export let investigationWindow: (item: SavedReport) => string;
  export let focusSection: (id: string) => Promise<void>;
  export let openInvestigation: (investigation: SavedReport | null) => Promise<void>;
  export let startNewAnalysis: () => void;
  export let cancelRun: () => Promise<void>;
  export let sendFollowup: () => Promise<void>;

  let selectedEvidenceItems: Evidence[] = [];
  let selectedClaimId: string | null = null;
  let selectedPlay: Evidence | null = null;
  let evidenceLoading = false;
  let evidenceError = '';
  let evidenceRequestVersion = 0;
  let playPanelElement: HTMLElement | null = null;
  let playTrigger: HTMLElement | null = null;
  let answerHeading: HTMLElement | null = null;

  $: selectedClaim = active.claims.find((claim) => claim.claim_id === selectedClaimId) ?? null;
  // The heading mounts with the report, so a reader starts at the answer.
  $: answerHeading?.focus({preventScroll: true});

  function problemMessage(problem: unknown) {
    return problem instanceof Error ? problem.message : String(problem);
  }

  function supplementalChart(chart: Investigation['charts'][number]) {
    return active?.run.sport === 'soccer' && (chart.specification.usermeta as {reportSection?: string})?.reportSection === 'supplemental';
  }

  function reportPeriods(result: Investigation) {
    const {baseline: start, comparison: end, comparison_design: design} = result.run.scope;
    if (result.run.comparison_subject) {
      return {baseline: subjectName(result, result.run.subject), comparison: subjectName(result, result.run.comparison_subject)};
    }
    return {baseline: periodLabel(start, design, seasonLabel), comparison: periodLabel(end, design, seasonLabel)};
  }

  function evidenceLeader(result: Investigation) {
    if (!result.run.comparison_subject) return null;
    const {baseline, comparison} = reportPeriods(result);
    return (item: Evidence) => headToHeadLeader(item.value, metricDirections[`${result.run.sport ?? 'nfl'}:${item.metric}`], [baseline, comparison]);
  }

  async function inspect(identifier: string) {
    const requestVersion = ++evidenceRequestVersion;
    selectedClaimId = null;
    selectedEvidenceItems = [];
    evidenceLoading = true;
    evidenceError = '';
    try {
      const evidence = await api.evidence(active.run.investigation_id, identifier) as Evidence;
      if (requestVersion !== evidenceRequestVersion) return;
      selectedEvidenceItems = [evidence];
      // Tablets initially receive the report's saved example. Replace it with
      // the enriched API response (cached shots, historical context, etc.).
      if (selectedPlay?.evidence_id === identifier) selectedPlay = evidence;
    } catch (problem) {
      if (requestVersion === evidenceRequestVersion) evidenceError = problemMessage(problem);
    } finally {
      if (requestVersion === evidenceRequestVersion) evidenceLoading = false;
    }
  }

  async function inspectFinding(claim: Claim, prefetched?: Promise<Evidence[]>) {
    const requestVersion = ++evidenceRequestVersion;
    selectedClaimId = claim.claim_id;
    selectedEvidenceItems = [];
    evidenceLoading = true;
    evidenceError = '';
    try {
      const evidence = await (prefetched ?? api.evidenceBatch(active.run.investigation_id, claim.evidence_ids));
      if (requestVersion !== evidenceRequestVersion) return;
      selectedEvidenceItems = evidence;
    } catch (problem) {
      if (requestVersion === evidenceRequestVersion) evidenceError = problemMessage(problem);
    } finally {
      if (requestVersion === evidenceRequestVersion) evidenceLoading = false;
    }
  }

  function openPlay(play: Evidence) {
    playTrigger = document.activeElement as HTMLElement | null;
    selectedPlay = play;
    void inspect(play.evidence_id);
    void revealPanel(() => playPanelElement, 'start');
  }

  async function closePlay() {
    selectedPlay = null;
    await tick();
    playTrigger?.focus();
  }

  // A report opens on its first finding's evidence, using the request App started while the report loaded.
  if (active.claims[0]) {
    const prefetched = firstEvidence?.investigationId === active.run.investigation_id
        && firstEvidence.claimId === active.claims[0].claim_id ? firstEvidence.request : undefined;
    void inspectFinding(active.claims[0], prefetched);
  }
</script>

<section class="report-hero">
  <div class="report-summary">
    {#if active.run.parent_investigation_id && conversationThread[0]}
      <div class="followup-view">
        <strong>Follow-up answer</strong>
        <button type="button" on:click={() => openInvestigation(conversationThread[0])}>Back to the original report</button>
      </div>
    {/if}
    <span class="eyebrow">Report · {active.fallback_used ? 'Calculated summary' : 'AI analyst'}</span>
    <p class="report-question"><span>Your question</span>{active.run.question}</p>
    <h2 bind:this={answerHeading} tabindex="-1">The answer</h2>
    {#if active.run.subject?.type === 'player'}
      <PlayerPortrait id={active.run.subject.id} sport={active.run.sport ?? 'nfl'} name={investigationSubject(active, playerNamesById)}
                      historical={active.run.sport === 'cfb'}/>
    {/if}
    <p><ModelText text={active.summary}/></p>
    <div class="report-meta" aria-label="Report scope">
      <span>{investigationSubject(active, playerNamesById)}</span>
      <span>{displayDomain(active.run.analysis_domain)}</span>
      <span>{investigationWindow(active)}</span>
      <span>{active.claims.length} {active.claims.length === 1 ? 'finding' : 'findings'}</span>
    </div>
  </div>
  <div class="report-actions">
    <a class="export" href={`/api/investigations/${active.run.investigation_id}/export?format=html`}>Export Report
      <Icon name="file-download" size={17}/>
    </a>
    <button type="button" class="export" on:click={() => focusSection('followup-question')}>Ask a Follow-up
      <Icon name="send" size={17}/>
    </button>
  </div>
</section>
{#if !active.run.parent_investigation_id}
  <section class="key-metrics" aria-label={active.run.comparison_subject ? 'Key metric comparison' : 'Key metric changes'}>
    <h2 class="sr-only">{active.run.comparison_subject ? 'Key metric comparison' : 'Key metric changes'}</h2>
    {#if active.run.comparison_subject && active.run.scope.baseline.season < active.run.scope.comparison.season}
      <p class="key-metrics-note">Each season is compared on its own; there is no combined multi-season value.</p>
    {/if}
    {#each keyMetrics(active) as metric}
      {@const period = metricColumns(metric, active.aggregate_evidence, active.run.scope, seasonLabel)}
      {@const format = metricFormatter(metric, period.columns.map(column => column.value))}
      {@const direction = metricDirections[`${active.run.sport ?? 'nfl'}:${metric.metric}`]}
      {@const verdict = active.run.comparison_subject ? '' : changeVerdict(metric.value, direction)}
      {@const leader = active.run.comparison_subject ? headToHeadLeader(metric.value, direction, [period.columns[0].label, period.columns[1].label]) : ''}
      {@const seasons = active.run.comparison_subject ? headToHeadSeasons(metric, active.aggregate_evidence) : []}
      <article><h3>{seasons.length ? metric.context?.metric_label ?? metric.label : metric.label}</h3>
        {#if seasons.length}
          {@const names = [period.columns[0].label, period.columns[1].label] as [string, string]}
          {@const rangeFormat = metricFormatter(metric, seasons.flatMap(item => [item.baseline_value, item.comparison_value]))}
          <table class="season-pairs">
            <thead><tr><th scope="col">Season</th><th scope="col">{names[0]}</th><th scope="col">{names[1]}</th><th scope="col">Ahead</th></tr></thead>
            <tbody>
              {#each seasons as item}
                <tr><th scope="row">{item.context?.season_label ?? seasonLabel(Number(item.context?.season))}</th>
                  <td>{rangeFormat.value(item.baseline_value)}</td><td>{rangeFormat.value(item.comparison_value)}</td>
                  <td>{headToHeadLeader(item.value, direction, names) || '—'}</td></tr>
              {/each}
            </tbody>
          </table>
        {:else}
        <div class:many-periods={period.columns.length > 2}>
          {#each period.columns as column}
            <span>{column.label} <b>{format.value(column.value)}</b>
              {#if column.sample != null}<small>Sample {column.sample.toLocaleString()}</small>{/if}</span>
          {/each}
        </div>
        {#if active.run.comparison_subject}
          <p>Difference: <strong>{format.change(metric.value)}</strong>{#if leader}<em>{leader} ahead</em>{/if}</p>
        {:else}
          <p>Change{period.columns.length > 2 ? `, ${period.columns[0].label} to ${period.columns.at(-1)?.label}` : ''}: <strong>{format.change(metric.value)}</strong>
            {#if verdict}<em class:worse={verdict === 'Worse'}>{verdict}</em>{/if}</p>
        {/if}
        {#if period.middleSeasonsMissing}<small>Middle seasons aren't recorded for this metric.</small>{/if}
        {/if}
      </article>
    {:else}<p>No comparable metric values are available for these periods. Review the limitations below or adjust your periods and data sources.</p>{/each}
  </section>
{/if}
<div class="report-grid">
  <section class="findings">
    <div class="section-title"><h2>Core Findings</h2><small>Each one links to its evidence</small></div>
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
          on:click={() => inspectFinding(claim)}
      >
        <span class="sr-only">Inspect evidence for finding {index + 1}: </span>
        <span class="finding-number" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
        <span class="finding-content"><span class="claim-meta"><span
            class:interpretation={claim.claim_type === 'interpretation'}
            title={claim.claim_type === 'measured' ? 'Calculated from recorded data.' : 'An explanation of the evidence, not proof of cause.'}>{claim.claim_type}</span><i
            title="Confidence describes the strength of the evidence for this finding. It is not a probability or a guarantee.">{claim.confidence}
          confidence</i></span><span
            class="finding-statement"><ModelText text={claim.statement}/></span><span class="citations" aria-hidden="true"><span>{claim.evidence_ids.length} {claim.evidence_ids.length === 1 ? 'source' : 'sources'}</span></span></span>
        <span class="finding-inspect"><Icon name="search" size={17}/></span>
      </button>
      {#if selectedClaimId === claim.claim_id}
        <div class="mobile-evidence">
          <SupportingEvidence items={selectedEvidenceItems} loading={evidenceLoading} error={evidenceError} retry={() => inspectFinding(claim)}
                              periods={reportPeriods(active)} leader={evidenceLeader(active)}/>
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
                          retry={() => selectedClaim && inspectFinding(selectedClaim)} periods={reportPeriods(active)} leader={evidenceLeader(active)}/>
    {:else}<p class="evidence-panel-empty">Select a finding to see its supporting evidence.</p>{/if}
  </aside>
</div>
<section class="charts">
  <div class="section-title"><h2>Performance comparisons</h2>
    {#if active.charts.length}<small>The measurements behind the findings. Exact values are listed under each chart.</small>{/if}
  </div>
  {#if !active.charts.length}<p class="empty-state">No charts were produced for this analysis. The findings and supporting evidence above contain the available
    measurements.</p>{/if}
  <div class="chart-grid">
    {#each orderedCharts(active.charts.filter(chart => !supplementalChart(chart))) as chart}
      <article use:chartLayout class:chart-trend={isTrendChart(chart.specification)}
               class:chart-metric-group={isMetricRowChart(chart.specification)}><h3>{chart.title}</h3>
        {#if chartGuidance(chart.specification)}<p class="chart-note">{chartGuidance(chart.specification)}</p>{/if}
        <Chart specification={chart.specification} team={active.run.comparison_subject ? '' : active.run.subject?.team_id ?? active.run.scope.team}
               sport={active.run.sport ?? 'nfl'} season={active.run.scope.comparison.season} title={chart.title}/>
      </article>
    {/each}
  </div>
  {#if active.charts.some(supplementalChart)}
    <details class="supplemental-charts">
      <summary>Additional scoped calculations ({active.charts.filter(supplementalChart).length})</summary>
      <p class="section-help">These calculations use specific filters or subsets. Their gaps do not indicate missing overall team statistics.</p>
      <div class="chart-grid">
        {#each orderedCharts(active.charts.filter(supplementalChart)) as chart}
          <article use:chartLayout class:chart-trend={isTrendChart(chart.specification)} class:chart-metric-group={isMetricRowChart(chart.specification)}>
            <h3>{chart.title}</h3>
            <Chart specification={chart.specification} team={active.run.comparison_subject ? '' : active.run.subject?.team_id ?? active.run.scope.team}
              sport={active.run.sport ?? 'nfl'} season={active.run.scope.comparison.season} title={chart.title}/>
          </article>
        {/each}
      </div>
    </details>
  {/if}
</section>
<section class="plays">
  <div class="section-title">
    <h2>Representative {activeSport === 'nba' ? 'Possessions' : activeSport === 'soccer' ? 'Matches' : activeSport === 'cfb' && !active.play_evidence.some(play => play.play_id !== 0) ? 'Games' : 'Plays'}</h2><small>Examples
    from {active.run.comparison_subject ? 'each subject' : 'both periods'}—not the entire
    sample</small>
  </div>
  <p class="section-help">Select a {activeSport === 'soccer' ? 'match' : activeSport === 'nba' ? 'possession' : 'play'} to inspect it.</p>
  <dl class="play-tag-legend">
    <div><dt>Typical</dt><dd>close to the usual result</dd></div>
    <div><dt>Metric example</dt><dd>shows a chosen metric at work, often a big gain or loss</dd></div>
    <div><dt>Supports change</dt><dd>fits the overall finding</dd></div>
    <div><dt>Counterexample</dt><dd>runs against it</dd></div>
  </dl>
  {#if !active.play_evidence.length}<p class="empty-state">No representative plays are available for this analysis. Review the numerical evidence and source
    limitations above.</p>{/if}
  {#each evidenceGroups(active.play_evidence, reportPeriods(active)) as group}
    <div class="evidence-window-group">
      <div class="evidence-window-heading">
        <strong>{group.label}</strong>
        <small>{evidenceCoverage(group.plays, activeSport === 'nba' ? 'possessions' : activeSport === 'soccer' ? 'matches' : 'plays')}</small>
      </div>
      <div class="play-list">
        {#each group.plays as play}
          <button class:selected={selectedPlay?.evidence_id === play.evidence_id}
                  aria-expanded={selectedPlay?.evidence_id === play.evidence_id}
                  on:click={() => openPlay(play)}><span class="sr-only">Inspect {evidenceRoleLabel(play)} evidence from {gameLabel(play)}: </span><span class="play-tag"
                                                        class:supporting={play.evidence_role ? play.evidence_role !== 'counterexample' : play.supporting}
                                                        class:typical={play.evidence_role === 'typical'}>{evidenceRoleLabel(play)}</span>
            <span class="play-reference"><strong title={play.game_id}>{gameLabel(play)}</strong>
              {#if play.season && (active.run.comparison_subject || active.run.scope.baseline.season !== active.run.scope.comparison.season)}<small>{seasonLabel(play.season)} season</small>{/if}</span>
            <span class="play-description"><span>{play.description}</span>
              {#if play.selection_reason}<small>{play.selection_reason}</small>{/if}</span><b
                class="play-epa">{play.epa != null ? `${play.epa.toFixed(2)} EPA${['nfl', 'cfb'].includes(activeSport) && ['defense', 'defender'].includes(active.run.analysis_domain ?? '') ? ' allowed' : ''}` : play.metric_value != null ? `${play.metric_value.toFixed(1)} ${play.selection_metric ?? 'value'}` : 'Play evidence'}</b>
          </button>
        {/each}
      </div>
    </div>
  {/each}
  {#if selectedPlay}
    <div class="play-panel" bind:this={playPanelElement} tabindex="-1" role="region" aria-label="Selected play details">
      <TabletPanel play={selectedPlay} investigationId={active.run.investigation_id} onclose={closePlay}/>
    </div>
  {/if}
</section>
<details class="methodology">
  <summary>How this analysis was calculated</summary>
  <h3>Methodology and limitations</h3>
  {#each active.methodological_caveats as caveat}<p>{caveat}</p>{/each}
  <p>{active.run.comparison_subject ? `Differences are ${reportPeriods(active).comparison} minus ${reportPeriods(active).baseline}.` : 'Change is measured from the starting point to the comparison.'}
    {active.fallback_used ? 'This summary was calculated without an AI model.' : `Written by the AI model ${active.model_id ?? 'configured for this app'}.`}
    Measured findings come from recorded data; interpretations describe possible
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
<section class="conversation" aria-label="Follow-up questions">
  <div class="conversation-header">
    <div>
      <h2>Ask about this report</h2>
      <p>Your questions and answers are saved with this report. Select an answer to inspect its evidence.</p>
    </div>
    <span class="conversation-count">{Math.max(0, conversationThread.length - 1)} follow-up{conversationThread.length === 2 ? '' : 's'}</span>
  </div>
  <div class="conversation-messages" aria-live="polite">
    {#each conversationThread as turn}
      {#if !turn.run.parent_investigation_id}
        <button class="thread-origin" class:selected={active.run.investigation_id === turn.run.investigation_id} type="button"
                on:click={() => openInvestigation(turn)}>
          <small>Report question</small><span>{turn.run.question}</span>
          <em>{active.run.investigation_id === turn.run.investigation_id ? 'Showing the report' : 'Back to the report'}</em>
        </button>
      {:else}
      <article class="chat-row user-row">
        <span class="chat-avatar user-avatar">You</span>
        <div class="chat-bubble user-bubble">
          <div class="chat-message-meta"><small>Follow-up {conversationThread.filter(item => item.run.parent_investigation_id).indexOf(turn) + 1}</small>
            <time datetime={turn.run.created_at}>{chatTimestamp(turn.run.created_at)}</time>
          </div>
          <p>{turn.run.question}</p></div>
      </article>
      <div class="chat-row analyst-row">
        <span class="chat-avatar analyst-avatar"><Icon name="sports-analyst" size={24}/></span>
        <button class="chat-bubble analyst-bubble" class:selected={active.run.investigation_id === turn.run.investigation_id}
                type="button" on:click={() => openInvestigation(turn)}>
          <div class="chat-message-meta"><small>Open Sports Analyst</small>
            <time datetime={turn.run.created_at}>{chatTimestamp(turn.run.created_at)}</time>
          </div>
          <p><ModelText text={turn.summary}/></p>
          <span>{active.run.investigation_id === turn.run.investigation_id ? 'Viewing this answer' : 'View answer and evidence'}
            <Icon name="arrow-right" size={15}/></span>
        </button>
      </div>
      {/if}
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
          <p>{stage || 'Planning the next evidence-backed analysis…'}</p>
          <button class="cancel-run" type="button" disabled={!runningInvestigationId || cancelling} on:click={cancelRun}>
            {cancelling ? 'Cancelling…' : 'Cancel Follow-up'}
          </button></div>
      </article>
    {/if}
  </div>
  <div class="chat-composer">
              <textarea id="followup-question" bind:value={followup} rows="2" disabled={followupBusy}
                        aria-label="Ask a follow-up question"
                        placeholder="Ask a follow-up about this report…"
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

<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from './api';
  import Chart from './Chart.svelte';
  import type { AnalysisOptions, Capabilities, DatasetManifest, Evidence, Investigation, MetricOption } from './types';

  let capabilities: Capabilities | null = null;
  let analysisOptions: AnalysisOptions | null = null;
  let datasets: DatasetManifest[] = [];
  let history: Investigation[] = [];
  let active: Investigation | null = null;
  let selectedEvidence: Evidence | null = null;
  let question = "Why did this team's passing efficiency change?";
  let team = 'KC';
  let teamInput = 'Kansas City Chiefs (KC)';
  let baseline = 2024;
  let comparison = 2025;
  let baselineStartWeek = 1;
  let baselineEndWeek = 18;
  let comparisonStartWeek = 1;
  let comparisonEndWeek = 18;
  let splitWeek = 10;
  let comparisonMode = 'full_seasons';
  let seasonType: 'REG' | 'POST' | 'ALL' = 'REG';
  let selectedMetrics: string[] = [];
  let selectedSplits: string[] = [];
  let syncSeasons: number[] = [];
  let syncDatasets: string[] = ['play_by_play'];
  let initializedSelections = false;
  let stage = '';
  let progress = 0;
  let error = '';
  let busy = false;
  let followup = '';
  const metricCategories = ['Efficiency', 'Passing', 'Negative outcomes'];

  $: requiredSeasons = comparisonMode === 'before_after' ? [baseline] : [baseline, comparison];
  $: resolvedTeam = resolveTeam(teamInput);
  $: windowsDiffer = comparisonMode === 'before_after'
    || baseline !== comparison
    || baselineStartWeek !== comparisonStartWeek
    || baselineEndWeek !== comparisonEndWeek;
  $: hasRequiredData = requiredSeasons.every((season) => analysisOptions?.available_seasons.includes(season));
  $: canRun = Boolean(resolvedTeam && question.trim().length >= 3 && windowsDiffer && hasRequiredData);
  $: indexedSeasonCount = new Set(datasets.filter((dataset) => dataset.dataset === 'play_by_play').map((dataset) => dataset.season)).size;

  onMount(refresh);

  async function refresh() {
    try {
      [capabilities, analysisOptions, datasets, history] = await Promise.all([
        api.capabilities(), api.analysisOptions(), api.datasets(), api.investigations()
      ]);
      initializeSelections();
      if (!active && history.length) active = history[0];
    } catch (problem) { error = String(problem); }
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
      const missing = analysisOptions.syncable_seasons.filter((season) => !analysisOptions?.available_seasons.includes(season));
      syncSeasons = missing.length ? missing.slice(0, 2) : analysisOptions.available_seasons.slice(-1);
      initializedSelections = true;
    }
  }

  function teamDisplay(value: string, label: string) {
    return `${label} (${value})`;
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
    selectedMetrics = [...(analysisOptions?.default_metrics ?? [])];
  }

  function toggleSyncDataset(dataset: string) {
    syncDatasets = syncDatasets.includes(dataset)
      ? syncDatasets.filter((value) => value !== dataset)
      : [...syncDatasets, dataset];
  }

  function stream(url: string, complete: () => Promise<void>) {
    const source = new EventSource(url);
    source.onmessage = async (message) => {
      const event = JSON.parse(message.data);
      stage = event.message;
      progress = event.progress;
      if (event.stage === 'complete') { source.close(); await complete(); busy = false; }
      if (event.stage === 'failed') { source.close(); error = event.message; busy = false; }
    };
    source.onerror = () => { source.close(); error = 'The progress stream disconnected.'; busy = false; };
  }

  async function runAnalysis() {
    if (!canRun || !resolvedTeam) return;
    error = ''; busy = true; active = null; selectedEvidence = null; progress = 0.03; stage = 'Starting investigation';
    try {
      let baselineWindow: { season: number; weeks: [number, number] } = { season: baseline, weeks: [1, 22] };
      let comparisonWindow: { season: number; weeks: [number, number] } = { season: comparison, weeks: [1, 22] };
      if (comparisonMode === 'week_ranges') {
        baselineWindow = { season: baseline, weeks: [baselineStartWeek, baselineEndWeek] };
        comparisonWindow = { season: comparison, weeks: [comparisonStartWeek, comparisonEndWeek] };
      } else if (comparisonMode === 'before_after') {
        baselineWindow = { season: baseline, weeks: [1, splitWeek - 1] };
        comparisonWindow = { season: baseline, weeks: [splitWeek, 22] };
      }
      const metrics = selectedMetrics.filter((value) => {
        const option = analysisOptions?.metrics.find((metric) => metric.value === value);
        return option ? metricAvailable(option) : false;
      });
      const splits = selectedSplits.filter((value) => {
        const option = analysisOptions?.split_dimensions.find((split) => split.value === value);
        return option ? splitAvailable(option.available_seasons) : false;
      });
      const { investigation_id } = await api.investigate({
        question: question.trim(),
        scope: { team: resolvedTeam, baseline: baselineWindow, comparison: comparisonWindow, season_type: seasonType },
        metrics,
        splits
      });
      stream(`/api/investigations/${investigation_id}/events`, async () => { active = await api.investigation(investigation_id); await refresh(); });
    } catch (problem) { error = String(problem); busy = false; }
  }

  async function syncData() {
    if (!syncSeasons.length || !syncDatasets.length) return;
    error = ''; busy = true; stage = 'Preparing data sync';
    try {
      const { job_id } = await api.sync(syncSeasons, syncDatasets);
      stream(`/api/dataset-jobs/${job_id}/events`, async () => { await refresh(); });
    } catch (problem) { error = String(problem); busy = false; }
  }

  async function inspect(identifier: string) {
    if (!active) return;
    selectedEvidence = await api.evidence(active.run.investigation_id, identifier) as Evidence;
  }

  async function sendFollowup() {
    if (!active || !followup.trim()) return;
    busy = true;
    try { active = await api.followUp(active.run.investigation_id, followup); followup = ''; await refresh(); }
    catch (problem) { error = String(problem); }
    finally { busy = false; }
  }
</script>

<svelte:head><title>Open Sports Analyst</title></svelte:head>

<div class="app-shell">
  <aside class="rail">
    <div class="brand"><div class="mark">OSA</div><div><strong>Open Sports</strong><span>Analyst</span></div></div>
    <nav aria-label="Primary">
      <button class:active={!active} on:click={() => active = null}><span>⌁</span> New investigation</button>
      <div class="nav-label">Recent film room</div>
      {#each history.slice(0, 8) as item}
        <button class:active={active?.run.investigation_id === item.run.investigation_id} on:click={() => active = item}>
          <span>{item.run.scope.team}</span><div>{item.run.question}<small>{item.run.scope.baseline.season} W{item.run.scope.baseline.weeks[0]}–{item.run.scope.baseline.weeks[1]} → {item.run.scope.comparison.season} W{item.run.scope.comparison.weeks[0]}–{item.run.scope.comparison.weeks[1]}</small></div>
        </button>
      {/each}
    </nav>
    <div class="runtime">
      <i class:ready={capabilities?.model_configured}></i>
      <div><strong>{capabilities?.configured_provider || 'Loading'}</strong><span>{capabilities?.model_configured ? 'Model ready' : 'Deterministic mode'}</span></div>
    </div>
  </aside>

  <main>
    <header class="topbar">
      <div><span class="eyebrow">NFL · EVIDENCE WORKBENCH</span><h1>{active ? `${active.run.scope.team} investigation` : 'Ask a better football question.'}</h1></div>
      <div class="status-chip"><i></i>{indexedSeasonCount} seasons · {datasets.length} data packages</div>
    </header>

    {#if error}<div class="error" role="alert">{error}</div>{/if}

    {#if !active && !busy}
      <section class="ask-panel">
        <div class="ask-copy"><span class="eyebrow">START WITH THE EVIDENCE</span><h2>Turn play-by-play into an argument you can inspect.</h2><p>Choose the exact team, windows, and metrics. The analyst handles the football reasoning while every measurement stays tied to valid local data.</p></div>
        <section class="scope-card" aria-labelledby="scope-heading">
          <div class="scope-heading"><div><span class="eyebrow">01 · SCOPE</span><h3 id="scope-heading">Define the comparison</h3></div><span>{analysisOptions?.available_seasons.length ?? 0} seasons available</span></div>
          <div class="scope-controls">
            <label class="team-control">Team
              <input list="nfl-team-options" bind:value={teamInput} aria-label="NFL team" aria-invalid={!resolvedTeam} autocomplete="off" />
              <datalist id="nfl-team-options">{#each analysisOptions?.teams ?? [] as option}<option value={teamDisplay(option.value, option.label)}></option>{/each}</datalist>
              {#if teamInput && !resolvedTeam}<small class="validation">Choose a team from the list.</small>{/if}
            </label>
            <label>Comparison design
              <select bind:value={comparisonMode}>
                {#each analysisOptions?.comparison_windows ?? [] as option}
                  <option value={option.value} disabled={option.value === 'full_seasons' && (analysisOptions?.available_seasons.length ?? 0) < 2}>{option.label}</option>
                {/each}
              </select>
            </label>
            <label>Season type
              <select bind:value={seasonType}><option value="REG">Regular season</option><option value="POST">Postseason</option><option value="ALL">All games</option></select>
            </label>
          </div>

          {#if analysisOptions?.available_seasons.length}
            {#if comparisonMode === 'before_after'}
              <div class="window-grid before-after">
                <label>Season<select bind:value={baseline}>{#each [...analysisOptions.available_seasons].sort((a, b) => b - a) as season}<option value={season}>{season}</option>{/each}</select></label>
                <label>First week after split<select bind:value={splitWeek}>{#each analysisOptions.week_values.filter((week) => week > 1) as week}<option value={week}>Week {week}</option>{/each}</select></label>
                <div class="window-summary"><span>Baseline</span><strong>{baseline} · Weeks 1–{splitWeek - 1}</strong></div>
                <div class="window-summary"><span>Comparison</span><strong>{baseline} · Weeks {splitWeek}–22</strong></div>
              </div>
            {:else}
              <div class="window-grid">
                <fieldset>
                  <legend>Baseline window</legend>
                  <label>Season<select bind:value={baseline}>{#each [...analysisOptions.available_seasons].sort((a, b) => b - a) as season}<option value={season}>{season}</option>{/each}</select></label>
                  {#if comparisonMode === 'week_ranges'}<div class="week-pair"><label>Start<select bind:value={baselineStartWeek}>{#each analysisOptions.week_values as week}<option value={week} disabled={week > baselineEndWeek}>W{week}</option>{/each}</select></label><label>End<select bind:value={baselineEndWeek}>{#each analysisOptions.week_values as week}<option value={week} disabled={week < baselineStartWeek}>W{week}</option>{/each}</select></label></div>{/if}
                </fieldset>
                <span class="arrow">→</span>
                <fieldset>
                  <legend>Comparison window</legend>
                  <label>Season<select bind:value={comparison}>{#each [...analysisOptions.available_seasons].sort((a, b) => b - a) as season}<option value={season}>{season}</option>{/each}</select></label>
                  {#if comparisonMode === 'week_ranges'}<div class="week-pair"><label>Start<select bind:value={comparisonStartWeek}>{#each analysisOptions.week_values as week}<option value={week} disabled={week > comparisonEndWeek}>W{week}</option>{/each}</select></label><label>End<select bind:value={comparisonEndWeek}>{#each analysisOptions.week_values as week}<option value={week} disabled={week < comparisonStartWeek}>W{week}</option>{/each}</select></label></div>{/if}
                </fieldset>
              </div>
              {#if !windowsDiffer}<p class="validation">Choose two different seasons or week ranges.</p>{/if}
            {/if}
          {:else}
            <p class="empty-state">Sync at least one nflverse season to configure an investigation.</p>
          {/if}
        </section>

        <section class="metric-card" aria-labelledby="metric-heading">
          <div class="scope-heading"><div><span class="eyebrow">02 · METRICS</span><h3 id="metric-heading">Choose what to measure</h3></div><button class="text-button" type="button" on:click={useRecommendedMetrics}>Use recommended</button></div>
          <p class="section-help">Selections constrain the investigation. Leave every metric clear to let the analyst use its standard set.</p>
          <div class="metric-groups">
            {#each metricCategories as category}
              <section class="metric-group" role="group" aria-label={category}>
                <h4 class="metric-group-title">{category}</h4>
                {#each analysisOptions?.metrics.filter((metric) => metric.category === category) ?? [] as metric}
                  <label class:unavailable={!metricAvailable(metric)} title={metric.description}>
                    <input type="checkbox" checked={selectedMetrics.includes(metric.value)} disabled={!metricAvailable(metric)} on:change={() => toggleMetric(metric.value)} />
                    <span><strong>{metric.label}</strong><small>{metric.description}</small></span>
                  </label>
                {/each}
              </section>
            {/each}
          </div>
          <button class="text-button clear-metrics" type="button" on:click={() => selectedMetrics = []}>Let the analyst choose</button>
          <div class="split-selector">
            <div><h4>Diagnostic cuts</h4><p>Optionally constrain which situations the analyst decomposes.</p></div>
            <div class="split-options">
              {#each analysisOptions?.split_dimensions ?? [] as split}
                <label class:unavailable={!splitAvailable(split.available_seasons)} title={split.description}>
                  <input type="checkbox" checked={selectedSplits.includes(split.value)} disabled={!splitAvailable(split.available_seasons)} on:change={() => toggleSplit(split.value)} />
                  <span>{split.label}</span>
                </label>
              {/each}
            </div>
          </div>
        </section>

        <label class="question-label">Your question<textarea bind:value={question} rows="3"></textarea></label>
        <button class="primary" disabled={!canRun} on:click={runAnalysis}>Run investigation <span>↗</span></button>
        <details class="data-manager" open={indexedSeasonCount < 2}>
          <summary><span><strong>Manage local nflverse data</strong><small>Play-by-play plus optional player, roster, injury, schedule, snap, and Next Gen Stats packages.</small></span><b>{datasets.length} synced ↘</b></summary>
          <div class="onboarding"><div><strong>Select seasons and packages</strong><span>Supplemental tools run only when their packages are available for both windows.</span></div><select multiple bind:value={syncSeasons} aria-label="Seasons to sync">{#each analysisOptions?.syncable_seasons ?? [] as season}<option value={season}>{season}{analysisOptions?.available_seasons.includes(season) ? ' · PBP synced' : ''}</option>{/each}</select><div class="dataset-options">{#each analysisOptions?.syncable_datasets ?? [] as dataset}<label><input type="checkbox" checked={syncDatasets.includes(dataset)} on:change={() => toggleSyncDataset(dataset)} /><span>{dataset.replaceAll('_', ' ')}</span></label>{/each}</div><button disabled={!syncSeasons.length || !syncDatasets.length} on:click={syncData}>Sync selected</button></div>
        </details>
      </section>
      <section class="promise-grid">
        <article><span>01</span><h3>Measured first</h3><p>EPA, success, explosives, pressure outcomes, and situational splits run through tested tools.</p></article>
        <article><span>02</span><h3>Interpretation marked</h3><p>Football judgment stays distinct from measured claims without losing its analytical edge.</p></article>
        <article><span>03</span><h3>Every trail preserved</h3><p>Inputs, versions, queries, evidence IDs, caveats, and report artifacts travel together.</p></article>
      </section>
    {:else if busy}
      <section class="working"><div class="field-lines"></div><span class="eyebrow">ANALYSIS IN PROGRESS</span><h2>{stage}</h2><div class="progress"><i style={`width:${Math.max(4, progress * 100)}%`}></i></div><p>The evidence trail is being recorded as each tool completes.</p></section>
    {:else if active}
      <section class="report-hero"><div><span class="eyebrow">FINAL READ · {active.fallback_used ? 'DETERMINISTIC' : active.model_id}</span><h2>{active.summary}</h2></div><a class="export" href={`/api/investigations/${active.run.investigation_id}/export?format=html`}>Export report ↗</a></section>
      <div class="report-grid">
        <section class="findings"><div class="section-title"><span>CORE FINDINGS</span><small>{active.claims.length} evidence-bound claims</small></div>
          {#each active.claims as claim, index}
            <article class="finding"><div class="finding-number">{String(index + 1).padStart(2, '0')}</div><div><div class="claim-meta"><span class:interpretation={claim.claim_type === 'interpretation'}>{claim.claim_type}</span><i>{claim.confidence} confidence</i></div><p>{claim.statement}</p><div class="citations">{#each claim.evidence_ids as id}<button on:click={() => inspect(id)}>{id.slice(0, 18)}…</button>{/each}</div></div></article>
          {/each}
        </section>
        <aside class="evidence-panel">
          <div class="section-title"><span>EVIDENCE INSPECTOR</span></div>
          {#if selectedEvidence}
            <span class="evidence-id">{selectedEvidence.evidence_id}</span><h3>{selectedEvidence.label || `Play ${selectedEvidence.play_id}`}</h3>
            {#if selectedEvidence.baseline_value !== undefined}<div class="delta"><div><span>Baseline</span><strong>{selectedEvidence.baseline_value?.toFixed(3)}</strong></div><b>→</b><div><span>Comparison</span><strong>{selectedEvidence.comparison_value?.toFixed(3)}</strong></div></div>{/if}
            {#if selectedEvidence.description}<p>{selectedEvidence.description}</p>{/if}
            <dl><dt>Metric</dt><dd>{selectedEvidence.metric || 'source play'}</dd><dt>Sample</dt><dd>{selectedEvidence.sample_size || '1 play'}</dd><dt>Change / EPA</dt><dd>{selectedEvidence.value ?? selectedEvidence.epa}</dd></dl>
            {#each selectedEvidence.caveats || [] as caveat}<p class="caveat">{caveat}</p>{/each}
          {:else}<div class="empty-evidence"><b>↖</b><p>Select an evidence chip to inspect its values, sample, and caveats.</p></div>{/if}
        </aside>
      </div>
      <section class="charts"><div class="section-title"><span>THE SHAPE OF THE CHANGE</span></div><div class="chart-grid">{#each active.charts as chart}<article><h3>{chart.title}</h3><Chart specification={chart.specification}/></article>{/each}</div></section>
      <section class="plays"><div class="section-title"><span>REPRESENTATIVE PLAYS</span><small>Support and counterexamples</small></div>
        <div class="play-list">{#each active.play_evidence as play}<button on:click={() => inspect(play.evidence_id)}><span class:supporting={play.supporting}>{play.supporting ? 'support' : 'counter'}</span><strong>{play.game_id} · #{play.play_id}</strong><p>{play.description}</p><b>{play.epa?.toFixed(2)} EPA</b></button>{/each}</div>
      </section>
      <section class="followup"><span class="eyebrow">CHALLENGE THE READ</span><h2>Ask the analyst to go one level deeper.</h2><div><input bind:value={followup} placeholder="Was this driven more by sacks or unsuccessful early-down passes?" on:keydown={(event) => event.key === 'Enter' && sendFollowup()} /><button on:click={sendFollowup}>Ask follow-up ↗</button></div></section>
    {/if}
  </main>
</div>

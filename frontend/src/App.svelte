<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from './api';
  import Chart from './Chart.svelte';
  import type { Capabilities, DatasetManifest, Evidence, Investigation } from './types';

  let capabilities: Capabilities | null = null;
  let datasets: DatasetManifest[] = [];
  let history: Investigation[] = [];
  let active: Investigation | null = null;
  let selectedEvidence: Evidence | null = null;
  let question = "Why did this team's passing efficiency change?";
  let team = 'KC';
  let baseline = 2024;
  let comparison = 2025;
  let syncSeasons = '2024, 2025';
  let stage = '';
  let progress = 0;
  let error = '';
  let busy = false;
  let followup = '';

  onMount(refresh);

  async function refresh() {
    try {
      [capabilities, datasets, history] = await Promise.all([api.capabilities(), api.datasets(), api.investigations()]);
      if (!active && history.length) active = history[0];
    } catch (problem) { error = String(problem); }
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
    error = ''; busy = true; active = null; selectedEvidence = null; progress = 0.03; stage = 'Starting investigation';
    try {
      const { investigation_id } = await api.investigate(question, team, baseline, comparison);
      stream(`/api/investigations/${investigation_id}/events`, async () => { active = await api.investigation(investigation_id); await refresh(); });
    } catch (problem) { error = String(problem); busy = false; }
  }

  async function syncData() {
    error = ''; busy = true; stage = 'Preparing data sync';
    try {
      const seasons = syncSeasons.split(',').map((value) => Number(value.trim())).filter(Boolean);
      const { job_id } = await api.sync(seasons);
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
          <span>{item.run.scope.team}</span><div>{item.run.question}<small>{item.run.scope.baseline_season} → {item.run.scope.comparison_season}</small></div>
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
      <div class="status-chip"><i></i>{datasets.length} seasons indexed</div>
    </header>

    {#if error}<div class="error" role="alert">{error}</div>{/if}

    {#if !active && !busy}
      <section class="ask-panel">
        <div class="ask-copy"><span class="eyebrow">START WITH THE EVIDENCE</span><h2>Turn play-by-play into an argument you can inspect.</h2><p>Compare two seasons. The analyst plans the work, runs versioned metrics, challenges its own read, and links every finding to the source plays.</p></div>
        <div class="scope-grid">
          <label>Team<input bind:value={team} maxlength="3" aria-label="NFL team" /></label>
          <label>Baseline<input type="number" bind:value={baseline} /></label>
          <span class="arrow">→</span>
          <label>Comparison<input type="number" bind:value={comparison} /></label>
        </div>
        <label class="question-label">Your question<textarea bind:value={question} rows="3"></textarea></label>
        <button class="primary" on:click={runAnalysis}>Run investigation <span>↗</span></button>
        {#if datasets.length < 2}
          <div class="onboarding"><div><strong>Load local nflverse seasons</strong><span>Raw data stays on this machine.</span></div><input bind:value={syncSeasons} aria-label="Seasons to sync"/><button on:click={syncData}>Sync data</button></div>
        {/if}
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

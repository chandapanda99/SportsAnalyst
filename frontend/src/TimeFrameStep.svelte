<script lang="ts">
  import Icon from './Icon.svelte';
  import {MAX_HEAD_TO_HEAD_SEASONS} from './analysisScope';
  import type {AnalysisOptions, ComparisonWindowOption, PlayerOption} from './types';

  type Segment = {value: string; label: string; description: string};

  /** The step number shown on the card, such as "3". */
  export let step: string;
  export let activeSport: string;
  export let analysisOptions: AnalysisOptions | null;
  export let subjectType: 'team' | 'player';
  export let selectedPlayer: PlayerOption | null;
  export let headToHead: boolean;
  export let comparisonMode: string;
  export let comparisonOptions: ComparisonWindowOption[];
  export let seasonType: 'REG' | 'POST' | 'ALL';
  export let scopeSeasons: number[];
  export let currentSeason: number | null;
  export let requiredSeasons: number[];
  export let missingRequiredSeasons: number[];
  export let missingPlayerSeasons: number[];
  export let periodBlocker: string;
  export let windowsDiffer: boolean;
  export let periodStart: number;
  export let headToHeadFirst: number;
  export let baseline: number;
  export let comparison: number;
  export let baselineStartWeek: number;
  export let baselineEndWeek: number;
  export let comparisonStartWeek: number;
  export let comparisonEndWeek: number;
  export let splitWeek: number;
  export let baselineSegment: string;
  export let comparisonSegment: string;
  export let baselineStartDate: string;
  export let baselineEndDate: string;
  export let comparisonStartDate: string;
  export let comparisonEndDate: string;
  export let seasonLabel: (season: number) => string;
  export let availableSegments: (season: number) => Segment[];
</script>

<section class="scope-card" aria-labelledby="comparison-heading">
  <div class="scope-heading">
    <div><span class="eyebrow step-label"><b class="step-number">{step}</b>{headToHead ? 'Seasons' : 'Time frame'}</span>
      <h3 id="comparison-heading" tabindex="-1">{headToHead ? 'Choose the seasons' : 'Choose the time frame'}</h3></div>
  </div>
  <div class="scope-controls">
    {#if !headToHead}<label>Compare
      <select bind:value={comparisonMode}>
        {#each comparisonOptions as option}
          <option value={option.value}
                  disabled={['full_seasons', 'season_vs_prior'].includes(option.value) && scopeSeasons.length < 2}>{option.label}</option>
        {/each}
      </select>
    </label>{/if}
    {#if ['nfl', 'cfb'].includes(activeSport)}<label>Season type
      <select bind:value={seasonType}>
        <option value="REG">Regular season</option>
        <option value="POST">Postseason</option>
        <option value="ALL">All games</option>
      </select>
    </label>{/if}
  </div>

  {#if !headToHead}<p class="section-help">{comparisonOptions.find(option => option.value === comparisonMode)?.description ?? ''}</p>{/if}
  {#if scopeSeasons.length}
    {#if headToHead}
      <div class="window-grid before-after">
        <label>First season<select bind:value={headToHeadFirst}>
          {#each scopeSeasons as season}
            <option value={season}>{seasonLabel(season)}</option>
          {/each}
        </select></label>
        <label>Last season<select bind:value={comparison}>
          {#each scopeSeasons as season}
            <option value={season}>{seasonLabel(season)}</option>
          {/each}
        </select></label>
      </div>
      <p class="section-help">Choose one season, or a range of up to {MAX_HEAD_TO_HEAD_SEASONS}. Each season is compared on its own.</p>
      {#if periodBlocker}<p class="validation">{periodBlocker}</p>{/if}
    {:else if comparisonMode === 'season_vs_prior'}
      <div class="window-grid before-after">
        <label>Season<select bind:value={comparison}>
          {#each scopeSeasons as season}
            <option value={season}>{seasonLabel(season)}</option>
          {/each}
        </select></label>
        <div class="window-summary"><span>Measured against</span><strong>{seasonLabel(periodStart)}</strong></div>
      </div>
      {#if periodBlocker}<p class="validation">{periodBlocker}</p>{/if}
    {:else if ['soccer', 'cfb'].includes(activeSport) && comparisonMode === 'date_ranges'}
      <div class="window-grid">
        <fieldset>
          <legend>Starting point</legend>
          <label>Season<select bind:value={baseline}>
            {#each scopeSeasons as season}
              <option value={season}>{seasonLabel(season)}</option>
            {/each}
          </select></label>
          {#if comparisonMode === 'date_ranges'}
            <label>From date<input type="date" bind:value={baselineStartDate}/></label>
            <label>Through date<input type="date" bind:value={baselineEndDate}/></label>
          {/if}
        </fieldset>
        <span class="arrow"><Icon name="arrow-right" size={19}/></span>
        <fieldset>
          <legend>Compared to</legend>
          <label>Season<select bind:value={comparison}>
            {#each scopeSeasons as season}
              <option value={season}>{seasonLabel(season)}</option>
            {/each}
          </select></label>
          {#if comparisonMode === 'date_ranges'}
            <label>From date<input type="date" bind:value={comparisonStartDate}/></label>
            <label>Through date<input type="date" bind:value={comparisonEndDate}/></label>
          {/if}
        </fieldset>
      </div>
    {:else if activeSport === 'nba'}
      <div class="window-grid">
        <fieldset>
          <legend class:sr-only={comparisonMode === 'full_seasons'}>{comparisonMode === 'full_seasons' ? 'Range start' : 'Starting point'}</legend>
          <label>{comparisonMode === 'full_seasons' ? 'From season' : 'Season'}<select bind:value={baseline} on:change={() => {
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
          <legend class:sr-only={comparisonMode === 'full_seasons'}>{comparisonMode === 'full_seasons' ? 'Range end' : 'Compared to'}</legend>
          <label>{comparisonMode === 'full_seasons' ? 'Through season' : 'Season'}<select bind:value={comparison} disabled={comparisonMode === 'before_after_milestone'} on:change={() => {
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
        <div class="window-summary"><span>Before</span><strong>{baseline} · Weeks 1–{splitWeek - 1}</strong></div>
        <div class="window-summary"><span>After</span><strong>{baseline} · Weeks {splitWeek}–22</strong></div>
      </div>
    {:else}
      <div class="window-grid">
        <fieldset>
          <legend class:sr-only={comparisonMode === 'full_seasons'}>{comparisonMode === 'full_seasons' ? 'Range start' : 'Starting point'}</legend>
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
          <legend class:sr-only={comparisonMode === 'full_seasons'}>{comparisonMode === 'full_seasons' ? 'Range end' : 'Compared to'}</legend>
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
        <p class="range-summary">{`Includes every season from ${seasonLabel(baseline)} through ${seasonLabel(comparison)}: ${requiredSeasons.map(seasonLabel).join(', ')}.`}</p>
      {/if}
      {#if currentSeason != null && requiredSeasons.includes(currentSeason)}
        <p class="current-season-note">{seasonLabel(currentSeason)} is still being played. Results reflect only games in your latest download{activeSport === 'nfl'
          ? '; use matching week ranges to compare equivalent portions of past seasons' : ''}.</p>
      {/if}
      {#if !windowsDiffer}
        <p class="validation">{comparisonMode === 'full_seasons' ? 'Choose an ending season later than the starting season.' : 'Choose two different seasons or week ranges.'}</p>
      {/if}
      {#if windowsDiffer && missingRequiredSeasons.length}
        <p class="validation">{analysisOptions?.automatic_preparation ? 'Data will prepare automatically for' : 'Sync the missing seasons before running'}
          this range: {missingRequiredSeasons.join(', ')}. Coverage is verified before analysis.</p>
      {/if}
      {#if windowsDiffer && missingPlayerSeasons.length}
        <p class="validation">The selected player has no recorded data for season{missingPlayerSeasons.length === 1 ? '' : 's'}
          {missingPlayerSeasons.join(', ')}. Choose a continuous range from the available player seasons.</p>
      {/if}
    {/if}
  {:else}
    <p class="empty-state">{subjectType === 'player' && selectedPlayer
        ? 'No locally synced seasons overlap this player’s recorded career.'
        : `Sync at least one ${activeSport === 'nba' ? 'SportsDataverse NBA' : activeSport === 'soccer' ? 'Sports Dataverse soccer' : 'nflverse'} season to set up an analysis.`}</p>
  {/if}
</section>

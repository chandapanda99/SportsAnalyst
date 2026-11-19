<script lang="ts">
  import DownloadScope from './DownloadScope.svelte';
  import Icon from './Icon.svelte';
  import type {AnalysisOptions, DatasetManifest, DownloadSelection, SportOption, TeamOption} from './types';

  type PackageStatus = {state: string; label: string; detail?: string};

  export let activeSport: string;
  export let sports: SportOption[];
  export let selectedCompetition: string;
  export let analysisOptions: AnalysisOptions | null;
  export let setup: AnalysisOptions['data_setup'];
  export let datasets: DatasetManifest[];
  export let comparison: number;
  export let currentSeason: number | null;
  export let resolvedTeam: string;
  export let cfbConference: string;
  export let cfbConferenceLabel: string;
  export let cfbLoading: boolean;
  export let cfbError: string;
  export let cfbTeams: TeamOption[];
  export let syncSeasons: number[];
  export let syncDatasets: string[];
  export let downloadScope: DownloadSelection;
  export let customizeSources: boolean;
  export let syncComplete: boolean;
  export let busy: boolean;
  export let stage: string;
  export let workspaceLoading: boolean;
  export let workspaceLoadError: string;
  export let serviceOffline: boolean;
  export let requiredSources: string[];
  export let visibleSyncDatasets: string[];
  export let sourceGaps: string[];
  export let eligibleSyncDatasets: string[];
  export let allEligibleSyncDatasetsSelected: boolean;
  export let seasonLabel: (season: number) => string;
  export let datasetLabel: (dataset: string) => string;
  export let sourceRole: (source: string) => string;
  export let seasonPackageStatus: (season: number) => string;
  export let packageCoverage: (dataset: string, selectedSeasons?: number[]) => string;
  export let packageInstallStatus: (dataset: string, selectedSeasons?: number[], selectedTeam?: string) => PackageStatus | null;
  export let packageEligible: (dataset: string, selectedSeasons?: number[]) => boolean;
  export let focusSection: (id: string) => Promise<void>;
  export let refresh: () => Promise<void>;
  export let chooseQuickSetup: () => void;
  export let toggleSyncSeason: (season: number) => void;
  export let toggleSyncDataset: (dataset: string) => void;
  export let toggleAllSyncDatasets: () => void;
  export let syncData: () => Promise<void>;
  export let syncCFBConference: () => Promise<void>;
  export let clearDownloadedData: () => Promise<void>;
  export let backToAnalysis: () => Promise<void>;
</script>

<section id="data-setup" tabindex="-1" class="data-manager" class:quick-setup={!customizeSources} class:nba-data-manager={activeSport === 'nba'}
         aria-labelledby="data-setup-heading">
  <div class="onboarding">
    <div class="data-setup-header">
      <div class="sync-guidance">
        <h2 id="data-setup-heading">{setup?.label ?? 'Recommended data'}</h2><span>{setup?.description ?? 'Choose seasons and download their recorded plays to begin.'}</span>
        {#if activeSport === 'nba' && sports.find(sport => sport.value === 'nba')?.live_available}
          <span class="nba-additional-data-note">Additional NBA Stats data available. Optional sources can add detail to your downloaded datasets; availability depends on the selected source.</span>
        {/if}
      </div>
      {#if !workspaceLoading && analysisOptions}
        <div class="data-setup-actions">
          <div class="setup-mode">
            <button type="button" aria-pressed={!customizeSources} on:click={chooseQuickSetup}>Recommended setup</button>
            <button type="button" aria-expanded={customizeSources} on:click={() => customizeSources = !customizeSources}>Customize data sources</button>
          </div>
        </div>
      {/if}
    </div>
    {#if activeSport === 'cfb'}
      <div class="cfb-data-scope" aria-live="polite">
        <div>
          <strong>{resolvedTeam ? `Downloading for ${cfbTeams.find(option => option.value === resolvedTeam)?.label ?? resolvedTeam}` : 'Choose a school first'}</strong>
          <p>{resolvedTeam ? 'Downloads cover this school for the seasons and sources below, including its nonconference games.' : 'Choose a school above. Browsing a conference does not download its schools.'}</p>
        </div>
        {#if !resolvedTeam}
          <button type="button" on:click={() => focusSection('library-school-heading')}>Choose a school</button>
        {/if}
      </div>
    {/if}
    {#if activeSport !== 'cfb' && analysisOptions}
      {#key `${activeSport}:${selectedCompetition}`}
        <DownloadScope sport={activeSport} season={syncSeasons[0] ?? comparison}
          competition={activeSport === 'soccer' ? selectedCompetition : undefined}
          teams={analysisOptions.teams} disabled={busy} onchange={(selection) => downloadScope = selection}/>
      {/key}
    {/if}
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
        <span><strong>Data catalog unavailable</strong><small>{serviceOffline ? 'Seasons and sources appear once the analysis service is running.' : workspaceLoadError || 'The analysis service did not respond. Try loading the catalog again.'}</small></span>
        <button type="button" on:click={() => refresh()}>Retry</button>
      </div>
    {:else}
      {#if syncComplete}
        <div class="sync-success" role="status"><strong>Download finished</strong>
          <p>Your Data library is up to date. Check any missing sources below before running.</p>
          <button type="button" on:click={backToAnalysis}>Back to your analysis</button>
        </div>
      {/if}
      {#if sourceGaps.length}
        <div class="data-readiness-row"><p class="data-gaps">Needed for your current comparison: {sourceGaps.join('; ')}.</p></div>
      {/if}
      <div class="sync-fields">
        <fieldset class="season-picker">
          <legend>Seasons</legend>
          <div class="season-options" role="group" aria-label="Seasons to download">
            {#each analysisOptions?.syncable_seasons ?? [] as season}
              <label class:selected={syncSeasons.includes(season)}>
                <input type="checkbox" aria-label={`${season} season`} checked={syncSeasons.includes(season)}
                       on:change={() => toggleSyncSeason(season)}/>
                <strong>{seasonLabel(season)}{#if season === currentSeason}<em class="season-current">In progress</em>{/if}</strong>
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
            {#each visibleSyncDatasets as dataset}
              {@const installStatus = packageInstallStatus(dataset, syncSeasons, resolvedTeam)}
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
                {#if installStatus?.detail}<small class="coverage-detail">{installStatus.detail}</small>{/if}
                <small><span class="source-role"
                             class:required-source={requiredSources.includes(dataset)}>{sourceRole(dataset)}</span> · {packageCoverage(dataset, syncSeasons)}</small>
                {#if setup?.descriptions[dataset] && setup.descriptions[dataset].toLowerCase() !== datasetLabel(dataset).toLowerCase()}<small>{setup.descriptions[dataset]}</small>{/if}
                {#if activeSport === 'cfb'}
                  {#each datasets.filter(item => item.sport === 'cfb' && item.partition_key === `team:${resolvedTeam}` && item.dataset === dataset && syncSeasons.includes(item.season) && item.availability_message) as snapshot}
                    <small class="validation">{snapshot.season}: {snapshot.availability_message}</small>
                  {/each}
                {/if}</span></label>
            {/each}
          </div>
        </fieldset>
      </div>
      {#if currentSeason != null && syncSeasons.includes(currentSeason)}
        <p class="current-season-note">{seasonLabel(currentSeason)} is still in progress. Analyses use games in your latest download; refresh it as new
          results are published.{activeSport === 'nfl' ? ' For like-for-like comparisons, select matching week ranges.' : ''}</p>
      {/if}
      <button class="download-data-button"
              disabled={busy || !syncSeasons.length || !syncDatasets.length || (activeSport !== 'cfb' && !downloadScope.ready) || (activeSport === 'cfb' && (!resolvedTeam || cfbLoading || Boolean(cfbError)))}
              on:click={syncData}>
        {currentSeason != null && syncSeasons.includes(currentSeason) ? 'Download or refresh' : 'Download'} {syncDatasets.filter(source => visibleSyncDatasets.includes(source) && packageEligible(source)).length}
        sources for {syncSeasons.length} seasons
        {#if activeSport !== 'cfb' && downloadScope.kind !== 'league'} · {downloadScope.label}{/if}
        <Icon name="database-import" size={20}/>
      </button>
      {#if activeSport === 'cfb'}
        <div class="cfb-conference-download">
          <p><strong>Optional: a whole conference</strong><span>{cfbConference && !cfbLoading ? `${cfbConferenceLabel}, ${cfbTeams.length} schools. Uses the seasons and sources above; this is a larger download.` : 'Choose a conference above to download all of its schools. A team or player report does not need this.'}</span>
          </p>
          <button type="button"
                  disabled={busy || !cfbConference || !cfbTeams.length || cfbLoading || Boolean(cfbError) || !syncSeasons.length || !syncDatasets.length}
                  on:click={() => void syncCFBConference()}>Download entire conference
          </button>
        </div>
      {/if}
      {#if datasets.length}
        <div class="reset-data-zone">
          <p><strong>Clear downloaded data</strong><span>Removes every downloaded file for this {activeSport === 'soccer' ? 'competition' : 'sport'}. Saved reports stay.</span></p>
          <button type="button" class="reset-synced-data-button" disabled={busy} on:click={clearDownloadedData}>
            <Icon name="trash" size={16}/>
            {busy && stage === 'Clearing downloaded data' ? 'Clearing downloaded data…' : 'Clear downloaded data'}
          </button>
        </div>
      {/if}
    {/if}
  </div>
</section>

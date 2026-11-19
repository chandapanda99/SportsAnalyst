<script lang="ts">
  import Icon from './Icon.svelte';
  import TeamBadge from './TeamBadge.svelte';
  import {investigationTeamLogo, rootIdFor, savedOn, threadFor} from './reportThreads';
  import type {Capabilities, Investigation, InvestigationSummary, SportOption} from './types';

  type SavedReport = Investigation | InvestigationSummary;

  const filmRoomPreviewCount = 8;
  const minRailWidth = 240;

  export let activeSport: string;
  export let sportTabs: SportOption[];
  export let active: Investigation | null;
  export let history: InvestigationSummary[];
  export let rootHistory: InvestigationSummary[];
  export let playerNamesById: Map<string, string>;
  export let historyLoading: boolean;
  export let historyLoadError: string;
  export let deletingInvestigationId: string;
  /** True while the Data library is the page shown. */
  export let libraryOpen: boolean;
  export let mobileHistoryOpen: boolean;
  export let showFullFilmRoom: boolean;
  /** The desktop rail scrolls its list, so it lists every report; the stacked phone layout keeps the toggle. */
  export let railScrolls: boolean;
  export let railWidth: number;
  export let appShellElement: HTMLDivElement | null;
  export let capabilities: Capabilities | null;
  export let modelState: string;
  export let modelTitle: string;
  export let modelDetail: string;
  export let modelSettingsOpen: boolean;
  export let investigationSubject: (item: SavedReport, playerNames?: Map<string, string>) => string;
  export let investigationSubjectInitials: (item: SavedReport, playerNames?: Map<string, string>) => string;
  export let investigationWindow: (item: SavedReport) => string;
  export let loadHistory: () => Promise<void>;
  export let openInvestigation: (investigation: SavedReport | null) => Promise<void>;
  export let startNewAnalysis: () => void;
  export let openLibrary: () => Promise<void>;
  /** What is running in the background, shown at the top of the Film Room; null when nothing is. */
  export let running: {title: string; detail: string; progress: number} | null = null;
  export let progressShown = false;
  export let openProgress: () => Promise<void>;
  export let deleteInvestigation: (item: SavedReport) => Promise<void>;

  let resizingRail = false;

  function maxRailWidth() {
    return Math.min(window.innerWidth * 0.34, 416);
  }

  function resizeRailFromPointer(event: PointerEvent) {
    if (!resizingRail || !appShellElement) return;
    const left = appShellElement.getBoundingClientRect().left;
    railWidth = Math.max(minRailWidth, Math.min(maxRailWidth(), event.clientX - left));
  }

  function resizeRailFromKeyboard(event: KeyboardEvent) {
    const delta = event.key === 'ArrowRight' ? 16 : event.key === 'ArrowLeft' ? -16 : 0;
    if (delta) {
      railWidth = Math.max(minRailWidth, Math.min(maxRailWidth(), railWidth + delta));
      event.preventDefault();
    } else if (event.key === 'Home' || event.key === 'End') {
      railWidth = event.key === 'Home' ? minRailWidth : maxRailWidth();
      event.preventDefault();
    }
  }
</script>

<aside class="rail" class:mobile-history-open={mobileHistoryOpen}>
  <div class="brand"><img class="mark" src="/favicon.svg" alt="" aria-hidden="true"/>
    <div><strong>Open Sports</strong><span>Analyst</span></div>
  </div>
  <nav aria-label="Primary">
    <button class="sidebar-action new-investigation" class:active={!active && !libraryOpen && !progressShown} on:click={startNewAnalysis}>
      <span class="sidebar-action-icon"><Icon name="clipboard-plus" size={20}/></span>
      <span class="sidebar-action-label">New analysis</span>
    </button>
    <button class="sidebar-action data-library-button" class:active={libraryOpen && !progressShown} type="button" on:click={openLibrary}>
      <span class="sidebar-action-icon"><Icon name="database" size={20}/></span>
      <span class="sidebar-action-label">Data library</span>
    </button>
    <button class="mobile-history-toggle" type="button" aria-expanded={mobileHistoryOpen} on:click={() => mobileHistoryOpen = !mobileHistoryOpen}>Film Room
      ({rootHistory.length})
    </button>
    <div class="nav-label">
      <Icon name="history" size={15}/>
      {sportTabs.find(sport => sport.value === activeSport)?.label ?? activeSport.toUpperCase()} Film Room
    </div>
    {#if historyLoading}<p role="status"><span class="button-spinner" aria-hidden="true"></span> Loading the Film Room…</p>{/if}
    {#if historyLoadError}
      <div role="alert"><p>The Film Room couldn't load. {historyLoadError}</p>
        <button type="button" on:click={() => loadHistory()}>Retry</button>
      </div>
    {/if}
    {#if !historyLoading && !historyLoadError && !rootHistory.length}
      <p class="film-room-empty">No saved {activeSport === 'soccer' ? 'reports for this competition' : 'reports for this sport'} yet. Finished reports appear here.</p>
    {/if}
    <div class="film-room-list">
    {#if running}
      <div class="recent-report running-report">
        <button class="recent-report-link" class:active={progressShown} aria-current={progressShown ? 'page' : undefined} on:click={openProgress}>
          <span class="recent-subject-badge" aria-hidden="true"><span class="button-spinner"></span></span>
          <div><strong class="recent-subject-name">{running.title}</strong>
            {#if running.detail}<span class="recent-question">{running.detail}</span>{/if}
            <small>{Math.round(running.progress * 100)}% · open progress</small>
          </div>
        </button>
      </div>
    {/if}
    {#each showFullFilmRoom || railScrolls ? rootHistory : rootHistory.slice(0, filmRoomPreviewCount) as item}
      <div class="recent-report">
        <button class="recent-report-link" class:active={active && !progressShown ? rootIdFor(active, history) === item.run.investigation_id : false}
                on:click={() => openInvestigation(item)}>
          <TeamBadge logo={investigationTeamLogo(item)} label={investigationSubject(item, playerNamesById)}
                     initials={investigationSubjectInitials(item, playerNamesById)}/>
          <div><strong class="recent-subject-name">{investigationSubject(item, playerNamesById)}</strong>
            <span class="recent-question">{item.run.question}</span>
            <small>{#if savedOn(item)}<span class="recent-saved">{savedOn(item)} · </span>{/if}{investigationWindow(item)}</small>
            {#if threadFor(item, history).length > 1}<small class="thread-count">{threadFor(item, history).length - 1}
              follow-up{threadFor(item, history).length === 2 ? '' : 's'}</small>{/if}
          </div>
        </button>
        <button class="delete-report" type="button" aria-label={`Delete saved report: ${item.run.question}`} title="Delete saved report"
                disabled={deletingInvestigationId === item.run.investigation_id}
                on:click={() => deleteInvestigation(item)}>
          {#if deletingInvestigationId === item.run.investigation_id}<span class="button-spinner" aria-label="Deleting investigation"></span>{:else}
            <Icon name="trash" size={15}/>
          {/if}
        </button>
      </div>
    {/each}
    </div>
    {#if !railScrolls && rootHistory.length > filmRoomPreviewCount}
      <button class="film-room-more" type="button" aria-expanded={showFullFilmRoom} on:click={() => showFullFilmRoom = !showFullFilmRoom}>
        {showFullFilmRoom ? 'Show fewer' : `Show all ${rootHistory.length}`}
      </button>
    {/if}
  </nav>
  <button class="runtime" type="button" data-state={modelState} aria-haspopup="dialog" aria-expanded={modelSettingsOpen}
          aria-label={`AI model: ${modelTitle.replace(/…$/, '')}, ${modelDetail.replace(/…$/, '')}. ${modelState === 'unconfigured' || modelState === 'error' ? 'Set up the model connection' : 'Change model connection'}`}
          disabled={!capabilities} on:click={() => modelSettingsOpen = true}>
    <span class="runtime-icon" class:ready={modelState === 'ready'} class:error={modelState === 'error'} aria-hidden="true">
      {#if modelState === 'connecting'}<span class="button-spinner"></span>{:else}<Icon name="brain" size={18}/>{/if}
    </span>
    <span class="runtime-text">
      <strong>{modelTitle}</strong><span>{modelDetail}</span>
    </span>
    {#if modelState === 'unconfigured' || modelState === 'error'}<span class="runtime-action" aria-hidden="true">{modelState === 'error' ? 'Fix' : 'Set up'}</span>{/if}
  </button>
  <button class="rail-resizer" type="button"
          aria-label={`Resize navigation panel, currently ${Math.round(railWidth)} pixels wide. Use left and right arrow keys.`}
          on:pointerdown={(event) => {
            resizingRail = true;
            event.currentTarget.setPointerCapture(event.pointerId);
            resizeRailFromPointer(event);
            event.preventDefault();
          }}
          on:pointermove={resizeRailFromPointer}
          on:pointerup={(event) => {
            resizingRail = false;
            if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
          }}
          on:pointercancel={() => resizingRail = false}
          on:lostpointercapture={() => resizingRail = false}
          on:keydown={resizeRailFromKeyboard}></button>
</aside>

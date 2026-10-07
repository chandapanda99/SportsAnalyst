<script lang="ts">
  import type {Evidence, PlayVisualization} from './types';

  export let play: Evidence;
  export let onclose: () => void;

  type MatchEvent = NonNullable<PlayVisualization['soccer_timeline']>[number];
  type EventKind = 'goal' | 'card' | 'substitution' | 'shootout' | 'other';

  function minuteOf(clock: string): number | null {
    const value = clock.match(/(\d+)(?:\s*\+\s*(\d+))?/);
    return value ? Number(value[1]) + Number(value[2] ?? 0) / 1000 : null;
  }

  function kindOf(event: MatchEvent): EventKind {
    const type = event.type.toLowerCase();
    if (type.includes('shootout')) return 'shootout';
    if (event.scoring_play || type.includes('goal')) return 'goal';
    if (type.includes('card')) return 'card';
    if (type.includes('substitution') || type.includes('subbed')) return 'substitution';
    return 'other';
  }

  function normalizeEvents(source: MatchEvent[]): MatchEvent[] {
    const result: MatchEvent[] = [];
    for (const original of source) {
      const event = {...original};
      if (kindOf(event) === 'substitution') {
        const replacement = event.text.match(/(?:^|\.\s)([^.]+?) replaces ([^.]+)/i);
        event.player_in ||= replacement?.[1].trim();
        event.player_out ||= replacement?.[2].trim();
        // Deduplicate only explicit replacement pairs, never unrelated changes at the same minute.
        if (event.player_in && event.player_out && result.some(previous =>
            previous.clock === event.clock && previous.side === event.side
            && previous.player_in === event.player_in && previous.player_out === event.player_out)) continue;
      }
      result.push(event);
    }
    return result;
  }

  $: match = play.visualization;
  $: events = normalizeEvents(match?.soccer_timeline ?? [])
      .map((event, index) => ({event, index, minute: minuteOf(event.clock), kind: kindOf(event)}))
      .sort((a, b) => (a.minute ?? Number.POSITIVE_INFINITY) - (b.minute ?? Number.POSITIVE_INFINITY) || a.index - b.index);
  let selectedEventIndex = 0;
  let currentPlayId = play.evidence_id;
  $: if (play.evidence_id !== currentPlayId) {
    currentPlayId = play.evidence_id;
    selectedEventIndex = 0;
  }
  $: selectedEvent = events[selectedEventIndex] ?? events[0];
</script>

<section class="soccer-match-tablet" aria-label="Soccer match evidence">
  <header>
    <div>
      <small>RECORDED MATCH CONTEXT</small>
      <h3>{match?.home_team_name ?? 'Home'} vs {match?.away_team_name ?? 'Away'}</h3>
      <p>{match?.game_date ?? ''} · Match {play.game_id}</p>
    </div>
    <button type="button" aria-label="Close match detail" on:click={onclose}>×</button>
  </header>
  <div class="soccer-match-score">
    <span>{match?.home_team_name ?? 'Home'}</span>
    <strong>{match?.home_score ?? '–'} : {match?.away_score ?? '–'}</strong>
    <span>{match?.away_team_name ?? 'Away'}</span>
  </div>
  {#if match?.home_expected_goals != null || match?.away_expected_goals != null}
    <p class="soccer-match-xg">Expected goals (ESPN): {match?.home_expected_goals?.toFixed(2) ?? 'Unavailable'}
      : {match?.away_expected_goals?.toFixed(2) ?? 'Unavailable'}</p>
  {/if}
  <div class="match-context">
    {#if match?.competition_stage}<span>Stage: {match.competition_stage.replaceAll('-', ' ')}</span>{/if}
    {#if match?.match_status_detail}<span>{match.match_status_detail}</span>{/if}
    {#if match?.home_shootout_score != null && match?.away_shootout_score != null}
      <span>Penalty shootout: {match.home_shootout_score} : {match.away_shootout_score} (excluded from match goals)</span>
    {/if}
    {#if match?.match_notes}<span>{match.match_notes}</span>{/if}
  </div>
  <div class="timeline-heading">
    <div><h4>Match Timeline</h4>
      <p>Select a marker to read the recorded event.</p></div>
    <span>{events.length} recorded {events.length === 1 ? 'event' : 'events'}</span>
  </div>
  {#if events.length}
    <div class="timeline-labels" aria-hidden="true">
      <span>{match?.home_team_name ?? 'Home'}</span><span>MIN</span><span>{match?.away_team_name ?? 'Away'}</span>
    </div>
    <ol class="timeline" aria-label="Recorded match events in time order">
      <li class="timeline-endcap"><span>Kickoff · 0′</span></li>
      {#each events as item, index (item.index)}
        {#if item.minute !== null && item.minute >= 46 && (index === 0 || (events[index - 1].minute ?? -Infinity) < 46)}
          <li class="timeline-endcap"><span>Half Time · 45′</span></li>
        {/if}
        <li class:home={item.event.side === 'home'} class:away={item.event.side === 'away'} class:neutral={item.event.side !== 'home' && item.event.side !== 'away'}>
          <time>{item.event.clock || '—'}</time>
          <button type="button" class="event-marker" class:selected={selectedEvent?.index === item.index}
                  class:goal={item.kind === 'goal'} class:card={item.kind === 'card'}
                  class:red-card={item.kind === 'card' && item.event.type.toLowerCase().includes('red')}
                  aria-pressed={selectedEvent?.index === item.index}
                  aria-label={(item.event.clock || 'Unknown minute') + ' ' + (item.event.type || 'Event') + ' — ' + (item.event.side === 'home' ? (match?.home_team_name ?? 'Home') : item.event.side === 'away' ? (match?.away_team_name ?? 'Away') : 'Team not recorded')}
                  on:click={() => selectedEventIndex = index}>
            <span class="event-symbol" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                {#if item.kind === 'goal'}
                  <circle cx="12" cy="12" r="9"/><path d="m12 7 5 4-2 6H9l-2-6zM12 7V3m5 8 4-2m-6 8 2 3M9 17l-2 3m0-9L3 9"/>
                {:else if item.kind === 'substitution'}
                  <path d="M4 8h16m-5-5 5 5-5 5M20 16H4m5-5-5 5 5 5"/>
                {:else if item.kind === 'card'}
                  <rect x="6" y="3" width="12" height="18" rx="2"/>
                {:else if item.kind === 'shootout'}
                  <circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/>
                {:else}
                  <circle cx="12" cy="12" r="3" fill="currentColor"/>
                {/if}
              </svg>
            </span>
            <span class="event-type">
              {item.event.type || 'Event'}
              {#if item.kind === 'substitution' && (item.event.player_in || item.event.player_out)}
                <span class="replacement"><span>On: {item.event.player_in || 'Not recorded'}</span><span>Off: {item.event.player_out || 'Not recorded'}</span></span>
              {/if}
            </span>
          </button>
        </li>
      {/each}
      <li class="timeline-endcap"><span>End of match</span></li>
    </ol>
    {#if selectedEvent}
      <div class="event-detail" aria-live="polite">
        <div class="event-detail-heading">
          <strong>{selectedEvent.event.clock || 'Minute unavailable'} · {selectedEvent.event.type || 'Recorded Event'}</strong>
          <span>{selectedEvent.event.side === 'home' ? (match?.home_team_name ?? 'Home') : selectedEvent.event.side === 'away' ? (match?.away_team_name ?? 'Away') : 'Team not recorded'}</span>
        </div>
        {#if selectedEvent.kind === 'substitution'}
          <div class="substitution-detail">
            <p><strong>On</strong> {selectedEvent.event.player_in || 'Player not recorded'}</p>
            <p><strong>Off</strong> {selectedEvent.event.player_out || 'Player not recorded'}</p>
          </div>
        {/if}
        <p>{selectedEvent.event.text}</p>
      </div>
    {/if}
  {:else}
    <p class="soccer-match-empty">{match?.source_packages?.includes('key_events')
        ? 'NO KEY EVENTS recorded in this match summary.'
        : 'A detailed event timeline is UNAVAILABLE from the synced match data.'}</p>
  {/if}
  <small class="source-note">Events and scores reflect the recorded ESPN match feed. Event spacing is for readability, not proportional to elapsed time. No player
    positions or ball locations are inferred.</small>
</section>

<style>
  .soccer-match-tablet {
    --accent: var(--color-accent-primary);
    border: 1px solid var(--line);
    border-radius: 12px;
    background: var(--color-surface);
    padding: clamp(.9rem, 2vw, 1.4rem);
    margin-top: 1rem;
    min-width: 0
  }

  header {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: start
  }

  header small {
    letter-spacing: .1em;
    color: var(--accent)
  }

  header h3 {
    margin: .35rem 0;
    font-size: 1.2rem
  }

  header p {
    margin: 0;
    opacity: .75
  }

  header button {
    border: 1px solid var(--line);
    border-radius: 7px;
    background: transparent;
    color: inherit;
    font-size: 1.5rem;
    cursor: pointer;
    line-height: 1;
    padding: .15rem .5rem
  }

  .soccer-match-score {
    display: grid;
    grid-template-columns:minmax(0, 1fr) auto minmax(0, 1fr);
    gap: .7rem;
    align-items: center;
    text-align: center;
    padding: 1.25rem .5rem;
    margin: 1rem 0 .5rem;
    border-block: 1px solid var(--line)
  }

  .soccer-match-score span {
    min-width: 0;
    overflow-wrap: anywhere
  }

  .soccer-match-score strong {
    font-size: clamp(1.45rem, 4vw, 2rem);
    white-space: nowrap;
    font-variant-numeric: tabular-nums
  }

  .soccer-match-xg {
    text-align: center;
    font-variant-numeric: tabular-nums;
    color: var(--accent);
    margin: .65rem 0
  }

  .match-context {
    display: flex;
    gap: .35rem .8rem;
    flex-wrap: wrap;
    font-size: .82rem;
    opacity: .8
  }

  .timeline-heading {
    display: flex;
    justify-content: space-between;
    align-items: end;
    gap: 1rem;
    margin: 1.3rem 0 .8rem
  }

  .timeline-heading h4 {
    margin: 0;
    font-size: 1rem
  }

  .timeline-heading p {
    margin: .2rem 0 0;
    font-size: .8rem;
    opacity: .75
  }

  .timeline-heading > span {
    white-space: nowrap;
    font-size: .75rem;
    opacity: .7
  }

  .timeline-labels, .timeline li:not(.timeline-endcap) {
    display: grid;
    grid-template-columns:minmax(0, 1fr) 4.4rem minmax(0, 1fr);
    gap: .4rem;
    align-items: center
  }

  .timeline-labels {
    font-size: .72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .07em;
    color: var(--accent);
    text-align: center;
    padding: .4rem 0;
    border-block: 1px solid var(--line)
  }

  .timeline {
    position: relative;
    list-style: none;
    padding: 0;
    margin: 0;
    max-height: min(32rem, 65vh);
    overflow: auto;
    scrollbar-color: var(--line) transparent
  }

  .timeline::before {
    content: "";
    position: absolute;
    top: 1rem;
    bottom: 1rem;
    left: 50%;
    width: 2px;
    transform: translateX(-50%);
    background: var(--line)
  }

  .timeline li:not(.timeline-endcap) {
    position: relative;
    min-height: 3.45rem;
    padding: .36rem 0
  }

  .timeline time {
    grid-column: 2;
    grid-row: 1;
    position: relative;
    z-index: 1;
    justify-self: center;
    min-width: 3.3rem;
    padding: .25rem .3rem;
    text-align: center;
    border: 1px solid var(--line);
    border-radius: 999px;
    background: var(--color-surface);
    font-size: .78rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums
  }

  .timeline-endcap {
    position: relative;
    z-index: 1;
    display: flex;
    justify-content: center;
    padding: .55rem 0;
    color: var(--accent);
    font-size: .7rem;
    font-weight: 700;
    letter-spacing: .07em;
    text-transform: uppercase
  }

  .timeline-endcap span {
    background: var(--color-surface);
    padding: 0 .5rem
  }

  .timeline .home .event-marker {
    grid-column: 1;
    grid-row: 1;
    justify-self: end
  }

  .timeline .away .event-marker {
    grid-column: 3;
    grid-row: 1;
    justify-self: start
  }

  .timeline .neutral .event-marker {
    grid-column: 1/-1;
    grid-row: 2;
    justify-self: center
  }

  .timeline .neutral {
    padding-bottom: .6rem
  }

  .event-marker {
    display: inline-flex;
    align-items: center;
    gap: .4rem;
    min-width: 0;
    max-width: 100%;
    padding: .4rem .6rem;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: color-mix(in srgb, var(--accent) 8%, var(--color-surface));
    color: inherit;
    font: inherit;
    font-size: .8rem;
    cursor: pointer;
    text-align: left;
    transition: border-color .15s, background .15s, transform .15s
  }

  .event-marker:hover, .event-marker:focus-visible {
    border-color: var(--accent);
    transform: translateY(-1px)
  }

  .event-marker.selected {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 18%, var(--color-surface));
    box-shadow: 0 0 0 1px var(--accent)
  }

  .away .event-marker {
    background: color-mix(in srgb, #d9ad67 12%, var(--color-surface))
  }

  .away .event-marker.selected, .away .event-marker:hover, .away .event-marker:focus-visible {
    border-color: #d9ad67;
    box-shadow: 0 0 0 1px #d9ad67
  }

  .neutral .event-marker {
    border-style: dashed;
    opacity: .8
  }

  .event-symbol {
    flex: none;
    display: inline-grid;
    place-items: center;
    width: 1.45rem;
    height: 1.45rem;
    border-radius: 50%;
    background: var(--accent);
    color: #071a15;
    font-weight: 900;
    line-height: 1
  }

  .event-symbol svg {
    width: 1.1rem;
    height: 1.1rem;
  }

  .replacement {
    display: grid;
    gap: .2rem;
    margin-top: .3rem;
    font-size: .75rem;
  }

  .substitution-detail {
    display: flex;
    flex-wrap: wrap;
    gap: .5rem 1.5rem;
  }

  .substitution-detail strong {
    margin-right: .4rem;
  }

  .away .event-symbol {
    background: #d9ad67;
    color: #21160a
  }

  .card .event-symbol {
    border-radius: 3px;
    color: #2b1b08;
    background: #e9cb58
  }

  .red-card .event-symbol {
    color: #fff;
    background: #b63838
  }

  .neutral .event-symbol {
    color: #11202a;
    background: #9caeb0
  }

  .event-type {
    min-width: 0;
    overflow-wrap: anywhere;
    white-space: normal
  }

  .event-detail {
    margin-top: .8rem;
    border: 1px solid var(--line);
    border-left: 3px solid var(--accent);
    border-radius: 8px;
    background: color-mix(in srgb, var(--accent) 7%, var(--color-surface));
    padding: .85rem 1rem
  }

  .event-detail-heading {
    display: flex;
    justify-content: space-between;
    gap: .4rem 1rem;
    flex-wrap: wrap;
    font-size: .85rem
  }

  .event-detail-heading span {
    color: var(--accent)
  }

  .event-detail p {
    margin: .5rem 0 0;
    line-height: 1.5;
    overflow-wrap: anywhere
  }

  .soccer-match-empty {
    padding: 1rem;
    border: 1px dashed var(--line);
    border-radius: 8px;
    opacity: .8
  }

  .source-note {
    display: block;
    margin-top: 1rem;
    opacity: .7;
    line-height: 1.4
  }

  @media (max-width: 600px) {
    .timeline-labels, .timeline li:not(.timeline-endcap) {
      grid-template-columns:minmax(0, 1fr) 3.5rem minmax(0, 1fr);
      gap: .2rem
    }

    .event-marker {
      padding: .35rem
    }

    .event-symbol {
      width: 1.3rem;
      height: 1.3rem
    }

    .event-type {
      font-size: .72rem
    }

    .timeline time {
      min-width: 2.9rem;
      font-size: .7rem
    }

    .timeline-heading {
      align-items: start;
      flex-direction: column;
      gap: .3rem
    }
  }
</style>

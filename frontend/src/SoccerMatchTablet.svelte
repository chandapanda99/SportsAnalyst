<script lang="ts">
  import type {Evidence} from './types';

  export let play: Evidence;
  export let onclose: () => void;

  $: match = play.visualization;
  $: timeline = match?.soccer_timeline ?? [];
</script>

<section class="soccer-match-tablet" aria-label="Soccer match evidence">
  <header>
    <div><small>RECORDED MATCH CONTEXT</small><h3>{match?.home_team_name ?? 'Home'} vs {match?.away_team_name ?? 'Away'}</h3>
      <p>{match?.game_date ?? ''} · Match {play.game_id}</p></div>
    <button type="button" aria-label="Close match detail" on:click={onclose}>×</button>
  </header>
  <div class="soccer-match-score">
    <span>{match?.home_team_name ?? 'Home'}</span>
    <strong>{match?.home_score ?? '–'} : {match?.away_score ?? '–'}</strong>
    <span>{match?.away_team_name ?? 'Away'}</span>
  </div>
  {#if match?.home_expected_goals != null || match?.away_expected_goals != null}
    <p class="soccer-match-xg">Expected goals (ESPN): {match?.home_expected_goals?.toFixed(2) ?? 'Unavailable'} : {match?.away_expected_goals?.toFixed(2) ?? 'Unavailable'}</p>
  {/if}
  <p>{play.description}</p>
  {#if match?.competition_stage}<p>Stage: {match.competition_stage.replaceAll('-', ' ')}</p>{/if}
  {#if match?.match_status_detail}<p>{match.match_status_detail}</p>{/if}
  {#if match?.home_shootout_score != null && match?.away_shootout_score != null}
    <p>Penalty shootout: {match.home_shootout_score} : {match.away_shootout_score} (excluded from match goals)</p>
  {/if}
  {#if match?.match_notes}<p>{match.match_notes}</p>{/if}
  <h4>Recorded match events</h4>
  {#if timeline.length}
    <ol>
      {#each timeline as event}
        <li><time>{event.clock || '—'}</time><span><b>{event.type}</b> {event.text}</span></li>
      {/each}
    </ol>
  {:else}
    <p class="soccer-match-empty">{match?.source_packages?.includes('key_events')
      ? 'No key events were recorded in this match summary.'
      : 'A detailed event timeline is unavailable in the synced match data.'}</p>
  {/if}
  <small>Events and scores reflect the recorded ESPN match feed. No player positions or ball locations are inferred.</small>
</section>

<style>
  .soccer-match-tablet{border:1px solid var(--line);border-radius:12px;background:var(--color-surface);padding:1.25rem;margin-top:1rem}
  header{display:flex;justify-content:space-between;gap:1rem;align-items:start}
  header small{letter-spacing:.1em;color:var(--accent)}
  header h3{margin:.35rem 0;font-size:1.2rem}
  header p{margin:0;opacity:.7}
  header button{border:1px solid var(--line);border-radius:7px;background:transparent;color:inherit;font-size:1.5rem;cursor:pointer}
  .soccer-match-score{display:grid;grid-template-columns:1fr auto 1fr;gap:1rem;align-items:center;text-align:center;padding:1.5rem .5rem;margin:1rem 0;border-block:1px solid var(--line)}
  .soccer-match-score strong{font-size:2rem;white-space:nowrap}
  .soccer-match-xg{text-align:center;font-variant-numeric:tabular-nums;color:var(--accent)}
  h4{margin:1.2rem 0 .5rem}
  ol{padding:0;list-style:none;max-height:21rem;overflow:auto}
  li{display:grid;grid-template-columns:4rem 1fr;gap:.8rem;padding:.65rem 0;border-bottom:1px solid var(--line)}
  li time{font-variant-numeric:tabular-nums;font-weight:700}
  li b{display:block;font-size:.75rem;text-transform:uppercase;opacity:.7}
  .soccer-match-empty{opacity:.7}
</style>

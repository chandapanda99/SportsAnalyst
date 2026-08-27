<script lang="ts">
    import type {Evidence} from './types';
    import {teamChartDisplayPalette} from './teamPalettes';

    export let play: Evidence;
    export let onclose: () => void;

    $: visualization = play.visualization;
    $: shot = courtPoint(visualization?.shot_x, visualization?.shot_y);
    $: home = visualization?.home_team_abbreviation ?? 'Home';
    $: away = visualization?.away_team_abbreviation ?? 'Away';
    $: eventTeam = visualization?.team_abbreviation ?? play.team ?? '';
    $: teamPalette = teamChartDisplayPalette(eventTeam, 'nba');
    $: homePalette = teamChartDisplayPalette(home, 'nba');
    $: awayPalette = teamChartDisplayPalette(away, 'nba');

    function courtPoint(rawX?: number, rawY?: number) {
        if (rawX == null || rawY == null || !Number.isFinite(rawX) || !Number.isFinite(rawY)) return null;
        const x = rawX >= -25 && rawX <= 25 ? rawX + 25 : rawX >= 0 && rawX <= 50 ? rawX : rawX / 2;
        const y = rawY >= 0 && rawY <= 47 ? rawY : rawY * .47;
        return x >= 0 && x <= 50 && y >= 0 && y <= 47 ? {x, y} : null;
    }
</script>

<section class="tablet basketball" style={`--nba-primary:${teamPalette[0]};--nba-secondary:${teamPalette[1]}`}
         aria-label={`Basketball play for ${play.game_id}, event ${play.play_id}`}>
    <header>
        <div><span>NBA PLAY-BY-PLAY</span><h3>{play.game_id} · Event #{play.play_id}</h3></div>
        <button type="button" aria-label="Close basketball play" on:click={onclose}>×</button>
    </header>
    <div class="scorebar">
        <strong><span class="team-score" style={`--score-color:${awayPalette[0]}`}>{away} {visualization?.away_score ?? '—'}</span>
            <i>–</i><span class="team-score" style={`--score-color:${homePalette[0]}`}>{home} {visualization?.home_score ?? '—'}</span></strong>
        <span>{visualization?.period ? `Q${visualization.period}` : 'Period —'}</span>
        <span>{visualization?.clock ?? 'Clock —'}</span>
        <b>{visualization?.event_type ?? (visualization?.shooting_play ? 'Shot' : 'Recorded event')}</b>
    </div>
    <div class="body">
        <div class="court-wrap">
            <svg class="court" viewBox="0 0 50 47" role="img" aria-label={shot ? 'Half court with the recorded shot coordinate marked' : 'Half court; no shot coordinate was recorded'}>
                <rect x=".5" y=".5" width="49" height="46" rx=".8"/>
                <line x1="0" x2="50" y1="46.5" y2="46.5"/>
                <rect x="17" y="0" width="16" height="19"/>
                <circle cx="25" cy="19" r="6"/>
                <path d="M3 0 A22 22 0 0 0 47 0" transform="translate(0 5)"/>
                <path d="M3 0 L3 14 M47 0 L47 14"/>
                <line x1="22" x2="28" y1="4" y2="4" class="backboard"/>
                <circle cx="25" cy="5.25" r=".75" class="rim"/>
                {#if shot}
                    <g class:made={visualization?.scoring_play} class="shot" transform={`translate(${shot.x} ${shot.y})`}>
                        <circle r="1.45"/><path d="M-1 -1 L1 1 M1 -1 L-1 1"/>
                    </g>
                {/if}
            </svg>
            <small>{shot ? 'Marker uses the source play-by-play coordinate; no player trajectory is inferred.' : 'No shot coordinate was recorded for this event.'}</small>
        </div>
        <div class="event-card">
            <span>{visualization?.team_abbreviation ?? play.team}</span>
            <h4>{visualization?.player_name ?? 'Recorded NBA event'}</h4>
            <p>{play.description}</p>
            <dl>
                <div><dt>Shot value</dt><dd>{visualization?.shot_value ?? '—'}</dd></div>
                <div><dt>Result</dt><dd>{visualization?.shot_result ?? (visualization?.scoring_play ? 'Made / scoring' : 'Not recorded')}</dd></div>
                <div><dt>Distance</dt><dd>{visualization?.shot_distance != null ? `${visualization.shot_distance} ft` : '—'}</dd></div>
                <div><dt>Evidence value</dt><dd>{play.metric_value ?? play.epa ?? '—'}</dd></div>
            </dl>
            {#if visualization?.offense_player_ids?.length || visualization?.defense_player_ids?.length}
                <div class="lineups">
                    <div><strong>Offense</strong><span>{visualization.offense_player_ids?.join(' · ')}</span></div>
                    <div><strong>Defense</strong><span>{visualization.defense_player_ids?.join(' · ')}</span></div>
                </div>
            {/if}
        </div>
    </div>
    <footer>SportsDataverse source packages: {(visualization?.source_packages ?? ['play_by_play']).join(', ')}</footer>
</section>

<style>
    .tablet{border-top:3px solid var(--nba-primary);background:radial-gradient(circle at 100% 0,color-mix(in srgb,var(--nba-primary) 16%,transparent),transparent 24rem),linear-gradient(145deg,var(--color-surface-panel),var(--color-surface-low))}
    header,.scorebar{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 20px;border-bottom:1px solid var(--line)}
    header span,.event-card>span{font:10px var(--font-mono);letter-spacing:.12em;color:var(--nba-primary)}
    h3,h4{margin:4px 0 0} header button{width:32px;height:32px;border:1px solid var(--color-border-strong);border-radius:6px;background:var(--color-surface-control);color:var(--ink);font-size:22px;cursor:pointer}
    .scorebar{justify-content:flex-start;background:var(--color-surface-raised);font-size:13px}.scorebar strong{display:flex;align-items:center;gap:7px;margin-right:auto}.scorebar strong i{color:var(--color-text-tertiary);font-style:normal}.scorebar strong .team-score{color:var(--score-color)}.scorebar>span{color:var(--color-text-secondary)}.scorebar b{color:var(--nba-secondary)}
    .body{display:grid;grid-template-columns:minmax(300px,1.1fr) minmax(260px,.9fr);gap:20px;padding:20px}.court-wrap{display:grid;gap:8px}.court{width:100%;max-height:430px;background:#d7a765;border:1px solid #f2cf91}.court rect,.court line,.court circle,.court path{fill:none;stroke:#fff7e5;stroke-width:.35}.court .backboard{stroke-width:.65}.court .rim{stroke:#dd5b32;stroke-width:.55}.shot circle{fill:var(--nba-secondary);stroke:#fff;stroke-width:.35}.shot path{stroke:#fff;stroke-width:.45}.shot.made circle{fill:var(--nba-primary)}.court-wrap small,footer{color:var(--color-text-tertiary);font-size:10px}
    .event-card{padding:18px;border:1px solid color-mix(in srgb,var(--nba-primary) 48%,var(--line));background:var(--color-surface-raised)}.event-card p{color:var(--color-text-secondary);line-height:1.55}.event-card dl{display:grid;grid-template-columns:1fr 1fr;gap:8px}.event-card dl div{padding:9px;background:var(--color-surface-panel)}dt{color:var(--muted);font-size:10px;text-transform:uppercase}dd{margin:3px 0 0}.lineups{display:grid;gap:7px;margin-top:12px}.lineups div{display:grid;gap:3px;padding:8px;border:1px solid var(--line)}.lineups span{font:10px var(--font-mono);color:var(--color-text-secondary)}footer{padding:11px 20px;border-top:1px solid var(--line)}
    @media(max-width:760px){.body{grid-template-columns:1fr}.scorebar{flex-wrap:wrap}}
</style>

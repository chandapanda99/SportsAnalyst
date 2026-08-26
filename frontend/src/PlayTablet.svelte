<script lang="ts">
    import type {Evidence} from './types';
    import {buildPlaySchematic} from './playSchematic';
    import {teamChartDisplayPalette} from './teamPalettes';

    export let play: Evidence;
    export let onclose: () => void;

    $: palette = teamChartDisplayPalette(play.team ?? '');
    $: schematic = buildPlaySchematic(play.visualization);
    $: sourcePackages = play.visualization?.source_packages ?? ['play_by_play'];
    $: markerPrefix = `play-${play.evidence_id.replace(/[^a-zA-Z0-9]/g, '')}`;
    $: offensePlayers = playerRows(play.visualization?.offense_names, play.visualization?.offense_positions);
    $: defensePlayers = playerRows(play.visualization?.defense_names, play.visualization?.defense_positions);

    function sourceLabel(source: string) {
        return source === 'play_by_play' ? 'PBP' : source === 'participation' ? 'PARTICIPATION' : source === 'ftn_charting' ? 'FTN' : source.toUpperCase();
    }

    function pathColor(kind: string) {
        if (kind === 'return') return '#ff9d66';
        if (kind === 'after-catch') return palette[1];
        return palette[0];
    }

    function pathMarker(kind: string) {
        return `url(#${markerPrefix}-${kind})`;
    }

    function playerRows(names: string[] = [], positions: string[] = []) {
        return names.map((name, index) => ({name, position: positions[index] ?? '—'}));
    }

    function recordedFlag(value: boolean | null | undefined, yes: string, no = 'No') {
        return value == null ? 'Not recorded' : value ? yes : no;
    }
</script>

<section class="tablet" aria-label={`Play schematic for ${play.game_id}, play ${play.play_id}`}>
    <header>
        <div><span>PLAY-BY-PLAY SCHEMATIC</span>
            <h3>{play.game_id} · Play #{play.play_id}</h3></div>
        <div class="tablet-actions">
            <span>Recorded Play Context</span>
            <button type="button" aria-label="Close play schematic" on:click={onclose}>×</button>
        </div>
    </header>
    <div class="situation">
        <strong>{play.visualization?.down ? `${play.visualization.down}${play.visualization.down === 1 ? 'st' : play.visualization.down === 2 ? 'nd' : play.visualization.down === 3 ? 'rd' : 'th'} & ${play.visualization.yards_to_go ?? '?'}` : 'Situation unavailable'}</strong>
        <span>{play.visualization?.quarter ? `Q${play.visualization.quarter}` : 'Quarter —'}</span>
        <span>{play.visualization?.clock ?? 'Clock —'}</span>
        <span>{play.visualization?.possession_team ?? play.team}
            {play.visualization?.possession_score ?? '—'} – {play.visualization?.defensive_team ?? 'Opponent'}
            {play.visualization?.defensive_score ?? '—'}</span>
        <b>{play.epa?.toFixed(2)} EPA</b>
    </div>
    <div class="reconstruction-meta">
        <div><strong>{schematic.lineupMode === 'recorded' ? 'Recorded participants' : 'Formation-template lineup'}</strong>
            <span>{schematic.lineupMode === 'recorded' ? 'Player identities are recorded; spatial placement is reconstructed.' : 'Supporting participation data is unavailable; positions are inferred from the recorded play context.'}</span>
        </div>
        <div class="source-badges" aria-label="Sources used by this schematic">
            {#each sourcePackages as source}<span>{sourceLabel(source)}</span>{/each}
        </div>
    </div>
    <div class="field-wrap">
        <svg class="field" viewBox="0 0 120 53.3" role="img" aria-label="Reconstructed play showing lineup and ball movement">
            <defs>
                {#each ['pass', 'carry', 'after-catch', 'return'] as kind}
                    <marker id={`${markerPrefix}-${kind}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="3.5" markerHeight="3.5" orient="auto-start-reverse">
                        <path d="M 0 0 L 10 5 L 0 10 z" fill={pathColor(kind)}/>
                    </marker>
                {/each}
            </defs>
            <rect width="120" height="53.3" rx="1" class="turf"/>
            <rect x="0" width="10" height="53.3" class="endzone" style={`fill:${palette[1]}`}/>
            <rect x="110" width="10" height="53.3" class="endzone" style={`fill:${palette[0]}`}/>
            {#each Array.from({length: 11}, (_, index) => index) as marker}
                <line x1={10 + marker * 10} x2={10 + marker * 10} y1="0" y2="53.3" class="yard-line"/>
                {#if marker > 0 && marker < 10}
                    <text x={10 + marker * 10} y="5" class="yard-number">{marker <= 5 ? marker * 10 : (10 - marker) * 10}</text>
                    <text x={10 + marker * 10} y="50.2" class="yard-number bottom">{marker <= 5 ? marker * 10 : (10 - marker) * 10}</text>
                {/if}
            {/each}
            {#each [18, 35.3] as hashY}
                <line x1="10" x2="110" y1={hashY} y2={hashY} class="hash-line"/>
            {/each}
            <line x1={schematic.startX} x2={schematic.startX} y1="2" y2="51.3" class="scrimmage"/>
            {#if play.visualization?.yards_to_go != null}
                <line x1={schematic.lineToGainX} x2={schematic.lineToGainX} y1="2" y2="51.3" class="line-to-gain"/>
            {/if}
            {#each schematic.paths as segment}
                <path d={segment.d} class={`play-path ${segment.kind}`} style={`stroke:${pathColor(segment.kind)}`} marker-end={pathMarker(segment.kind)}/>
            {/each}
            {#each schematic.players as player}
                <g class={`field-player ${player.side} ${player.recorded ? 'recorded' : 'generic'}`} transform={`translate(${player.x} ${player.y})`}>
                    <circle r="1.65" style={player.side === 'offense' ? `fill:${palette[0]};stroke:${palette[1]}` : `fill:#d9e2e8;stroke:${palette[0]}`}/>
                    <text class="position-label" y=".12">{player.position.slice(0, 3)}</text>
                    <text class="name-label" y="3.1">{player.label}</text>
                    <title>{player.recorded ? `${player.name} · ${player.position}` : `${player.position} · template placement`}</title>
                </g>
            {/each}
            {#each schematic.markers as marker}
                <g class={`event-marker ${marker.kind}`} transform={`translate(${marker.x} ${marker.y})`}>
                    <circle r="1.05"/>
                    <rect x={-Math.max(4.2, marker.label.length * .62)} y="1.65" width={Math.max(8.4, marker.label.length * 1.24)} height="3.1" rx=".6"/>
                    <text y="3.82">{marker.label}</text>
                </g>
            {/each}
        </svg>
        <div class="field-legend">
            <span><i class="offense-key"></i>{play.visualization?.possession_team ?? play.team} offense</span>
            <span><i class="defense-key"></i>{play.visualization?.defensive_team ?? 'Defense'}</span>
            <span><i class="flight-key"></i>Ball flight</span>
            {#if schematic.paths.some(path => path.kind === 'after-catch')}<span><i class="yac-key"></i>After catch</span>{/if}
            {#if schematic.paths.some(path => path.kind === 'return')}<span><i class="return-key"></i>Turnover return</span>{/if}
        </div>
    </div>
    <div class="play-details">
        <p>{play.description}</p>
        <dl>
            <div>
                <dt>Formation <i>PBP</i></dt>
                <dd>{play.visualization?.formation ?? 'Not recorded'}{play.visualization?.shotgun ? ' · Shotgun' : ''}{play.visualization?.no_huddle ? ' · No huddle' : ''}</dd>
            </div>
            <div>
                <dt>Personnel <i>PART</i></dt>
                <dd>{play.visualization?.personnel ?? 'Offense not recorded'}<br/>{play.visualization?.defensive_personnel ?? 'Defense not recorded'}</dd>
            </div>
            <div>
                <dt>Alignment <i>FTN</i></dt>
                <dd>{play.visualization?.starting_hash ? `${play.visualization.starting_hash} hash` : 'Hash not recorded'} · {play.visualization?.qb_location ?? 'QB location unavailable'}{play.visualization?.offense_backfield_count != null ? ` · ${play.visualization.offense_backfield_count} backfield` : ''}</dd>
            </div>
            <div>
                <dt>Box & rush <i>PART/FTN</i></dt>
                <dd>{play.visualization?.defenders_in_box ?? play.visualization?.defense_box_count ?? '—'} in box · {play.visualization?.pass_rushers ?? '—'} rushers{play.visualization?.blitzers != null ? ` · ${play.visualization.blitzers} blitzers` : ''}</dd>
            </div>
            <div>
                <dt>Play design <i>PBP/FTN</i></dt>
                <dd>{[play.visualization?.motion && 'Motion', play.visualization?.play_action && 'Play action', play.visualization?.rpo && 'RPO', play.visualization?.screen && 'Screen', play.visualization?.trick_play && 'Trick'].filter(Boolean).join(' · ') || 'No charted design tags'}</dd>
            </div>
            <div>
                <dt>Pressure <i>PART/FTN</i></dt>
                <dd>{recordedFlag(play.visualization?.pressure, 'Pressured', 'Clean')}{play.visualization?.time_to_throw != null ? ` · ${play.visualization.time_to_throw.toFixed(2)}s TTT` : ''}{play.visualization?.qb_out_of_pocket ? ' · Out of pocket' : ''}{play.visualization?.qb_fault_sack ? ' · QB-fault sack' : ''}</dd>
            </div>
            <div>
                <dt>Coverage & read <i>PART/FTN</i></dt>
                <dd>{play.visualization?.coverage_type ?? play.visualization?.man_zone ?? 'Coverage not recorded'}{play.visualization?.read_thrown ? ` · ${play.visualization.read_thrown} read` : ''}</dd>
            </div>
            <div>
                <dt>Target context <i>PART/FTN</i></dt>
                <dd>{play.visualization?.route ?? 'Route not recorded'}{play.visualization?.catchable_ball != null ? ` · ${play.visualization.catchable_ball ? 'Catchable' : 'Uncatchable'}` : ''}{play.visualization?.contested_ball ? ' · Contested' : ''}{play.visualization?.receiver_drop ? ' · Drop' : ''}{play.visualization?.throw_away ? ' · Throwaway' : ''}</dd>
            </div>
            <div>
                <dt>Ball movement <i>PBP</i></dt>
                <dd>{play.visualization?.pass_length ?? play.visualization?.run_gap ?? 'Not recorded'} {play.visualization?.pass_location ?? play.visualization?.run_location ?? ''}{play.visualization?.air_yards != null ? ` · ${play.visualization.air_yards} air yd` : ''}{play.visualization?.yards_after_catch != null ? ` · ${play.visualization.yards_after_catch} YAC` : ''}</dd>
            </div>
            <div>
                <dt>Primary players <i>PBP</i></dt>
                <dd>{play.visualization?.passer && play.visualization?.receiver ? `${play.visualization.passer} → ${play.visualization.receiver}` : play.visualization?.rusher ?? 'Not recorded'}</dd>
            </div>
            <div>
                <dt>Result <i>PBP</i></dt>
                <dd>{play.visualization?.yards_gained ?? '—'} yards{play.visualization?.first_down ? ' · First down' : ''}{play.visualization?.touchdown ? ' · TD' : ''}{play.visualization?.turnover ? ' · Turnover' : ''}{play.visualization?.penalty ? ' · Penalty' : ''}</dd>
            </div>
            <div>
                <dt>Game impact <i>PBP</i></dt>
                <dd>{play.epa?.toFixed(2) ?? '—'} EPA{play.visualization?.win_probability_added != null ? ` · ${(play.visualization.win_probability_added * 100).toFixed(1)} WPA` : ''}{play.visualization?.win_probability != null ? ` · ${(play.visualization.win_probability * 100).toFixed(1)}% WP` : ''}</dd>
            </div>
        </dl>
        {#if offensePlayers.length || defensePlayers.length}
            <div class="on-field">
                <div class="on-field-heading"><strong>Recorded on-field personnel</strong><span>Participation package · placement above uses formation templates</span></div>
                <div class="lineup-columns">
                    <section><h4>{play.visualization?.possession_team ?? play.team} offense</h4>
                        <div>{#each offensePlayers as player}<span><b>{player.position}</b>{player.name}</span>{/each}</div>
                    </section>
                    <section><h4>{play.visualization?.defensive_team ?? 'Defense'}</h4>
                        <div>{#each defensePlayers as player}<span><b>{player.position}</b>{player.name}</span>{/each}</div>
                    </section>
                </div>
            </div>
        {/if}
        <small>The tablet progressively enhances play-by-play with locally available participation and FTN charting. Formation placement and ball curves are schematic reconstructions; they are not player-tracking coordinates or measured trajectories.</small>
    </div>
</section>

<style>
    .tablet {
        border-top: 1px solid var(--line);
        background: linear-gradient(145deg, var(--color-surface-panel), var(--color-surface-low));
    }

    header, .situation {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px
    }

    header {
        padding: 18px 20px;
        border-bottom: 1px solid var(--line)
    }

    header span {
        font: 11px var(--font-mono);
        letter-spacing: .12em;
        color: var(--color-text-tertiary)
    }

    header h3 {
        margin: 5px 0 0;
        font-size: 18px
    }

    .tablet-actions {
        display: flex;
        align-items: center;
        gap: 12px
    }

    button {
        border: 1px solid var(--color-border-strong);
        border-radius: 6px;
        background: var(--color-surface-control);
        color: var(--ink);
        cursor: pointer
    }

    .tablet-actions button {
        width: 32px;
        height: 32px;
        font-size: 22px;
        line-height: 1
    }

    .situation {
        padding: 11px 20px;
        background: var(--color-surface-raised);
        font-size: 13px
    }

    .situation span {
        color: var(--color-text-secondary)
    }

    .situation b {
        color: var(--mint)
    }

    .reconstruction-meta {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 18px;
        padding: 10px 20px 0
    }

    .reconstruction-meta > div:first-child {
        display: grid;
        gap: 2px
    }

    .reconstruction-meta strong {
        font-size: 12px
    }

    .reconstruction-meta > div:first-child span {
        color: var(--color-text-tertiary);
        font-size: 11px
    }

    .source-badges {
        display: flex;
        flex-wrap: wrap;
        justify-content: flex-end;
        gap: 5px
    }

    .source-badges span {
        padding: 3px 6px;
        border: 1px solid color-mix(in srgb, var(--mint) 35%, var(--line));
        border-radius: 3px;
        color: var(--mint);
        font: 8px var(--font-mono);
        letter-spacing: .06em
    }

    .field-wrap {
        padding: 18px 20px 10px
    }

    .field {
        display: block;
        width: 100%;
        max-height: 460px;
        border: 1px solid color-mix(in srgb, var(--mint) 24%, var(--line));
        background: #062c20
    }

    .turf {
        fill: rgb(90 230 135 / 0.5)
    }

    .endzone {
        opacity: .75
    }

    .yard-line {
        stroke: #dbe8ee;
        stroke-width: .2;
        opacity: .45
    }

    .yard-number {
        fill: rgb(237 244 247 / 58%);
        font: 3px var(--font-mono);
        text-anchor: middle;
        dominant-baseline: middle
    }

    .hash-line {
        stroke: #dbe8ee;
        stroke-width: .12;
        stroke-dasharray: .7 1;
        opacity: .45
    }

    .scrimmage {
        stroke: #0050f5;
        stroke-width: .35;
        stroke-dasharray: 1 1
    }

    .line-to-gain {
        stroke: #f5c451;
        stroke-width: .3;
        stroke-dasharray: .8 .7
    }

    .play-path {
        fill: none;
        stroke-width: .55;
        stroke-linecap: round;
        stroke-linejoin: round;
        stroke-dasharray: 1.2 1.15;
        vector-effect: non-scaling-stroke;
        animation: draw-path .8s ease-out both, travel-dashes 1.6s linear infinite
    }

    .play-path.after-catch {
        stroke-dasharray: 2 .85
    }

    .play-path.return {
        stroke-dasharray: .65 .85
    }

    .field-player {
        animation: settle-player .35s ease-out both
    }

    .field-player circle {
        stroke-width: .34;
        vector-effect: non-scaling-stroke
    }

    .field-player.generic circle {
        opacity: .74;
        stroke-dasharray: 1 1
    }

    .position-label {
        fill: #07121d;
        font: 1.15px var(--font-mono);
        font-weight: 800;
        text-anchor: middle;
        dominant-baseline: middle;
        pointer-events: none
    }

    .name-label {
        fill: #f4f8fa;
        paint-order: stroke;
        stroke: #071722;
        stroke-width: .65px;
        stroke-linejoin: round;
        font: 1.25px var(--font-sans);
        font-weight: 650;
        text-anchor: middle;
        pointer-events: none
    }

    .event-marker circle {
        fill: #081925;
        stroke: #f4f8fa;
        stroke-width: .35;
        vector-effect: non-scaling-stroke
    }

    .event-marker.turnover circle { fill: #ff754f }
    .event-marker.recovery circle { fill: #ffb35c }
    .event-marker.touchdown circle { fill: var(--mint) }
    .event-marker.catch circle { fill: #ecf3f6 }

    .event-marker rect {
        fill: rgb(4 19 30 / 92%);
        stroke: rgb(218 233 240 / 25%);
        stroke-width: .2
    }

    .event-marker text {
        fill: #f2f7f9;
        font: 1.15px var(--font-mono);
        text-anchor: middle
    }

    .field-legend {
        display: flex;
        flex-wrap: wrap;
        gap: 8px 16px;
        padding: 9px 2px 0;
        color: var(--color-text-tertiary);
        font: 9px var(--font-mono)
    }

    .field-legend span {
        display: inline-flex;
        align-items: center;
        gap: 6px
    }

    .field-legend i {
        display: inline-block;
        width: 16px;
        height: 0;
        border-top: 2px dashed currentColor
    }

    .field-legend .offense-key,
    .field-legend .defense-key {
        width: 7px;
        height: 7px;
        border: 1px solid currentColor;
        border-radius: 50%;
        background: color-mix(in srgb, var(--mint) 58%, transparent)
    }

    .field-legend .defense-key { background: #d9e2e8 }
    .field-legend .yac-key { color: #e7c56a; border-top-style: solid }
    .field-legend .return-key { color: #ff9d66 }
    .field-legend .flight-key { color: var(--mint) }

    @keyframes draw-path {
        from { opacity: 0; stroke-dashoffset: 12 }
        to { opacity: 1; stroke-dashoffset: 0 }
    }

    @keyframes travel-dashes {
        to { stroke-dashoffset: -8 }
    }

    @keyframes settle-player {
        from { opacity: 0 }
        to { opacity: 1 }
    }

    .play-details {
        padding: 15px 20px 20px;
        border-top: 1px solid var(--line)
    }

    .play-details p {
        margin: 0;
        color: var(--color-text-soft);
        line-height: 1.55
    }

    dl {
        display: grid;
        grid-template-columns:repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin: 14px 0
    }

    dl div {
        padding: 10px;
        background: var(--color-surface-raised)
    }

    dt {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        color: var(--muted);
        font-size: 11px;
        text-transform: uppercase
    }

    dt i {
        color: var(--mint);
        font: 8px var(--font-mono);
        font-style: normal;
        letter-spacing: .06em
    }

    dd {
        margin: 4px 0 0;
        color: var(--color-text-secondary);
        font-size: 13px;
        line-height: 1.45
    }

    .on-field {
        margin: 14px 0;
        border: 1px solid var(--line);
        background: var(--color-surface-raised)
    }

    .on-field-heading {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 18px;
        padding: 10px 12px;
        border-bottom: 1px solid var(--line)
    }

    .on-field-heading strong {
        font-size: 13px
    }

    .on-field-heading span {
        color: var(--color-text-tertiary);
        font: 9px var(--font-mono);
        letter-spacing: .04em
    }

    .lineup-columns {
        display: grid;
        grid-template-columns:1fr 1fr;
        gap: 0
    }

    .lineup-columns section {
        min-width: 0;
        padding: 11px 12px
    }

    .lineup-columns section + section {
        border-left: 1px solid var(--line)
    }

    .lineup-columns h4 {
        margin: 0 0 8px;
        color: var(--color-text-tertiary);
        font: 10px var(--font-mono);
        letter-spacing: .08em;
        text-transform: uppercase
    }

    .lineup-columns section > div {
        display: flex;
        flex-wrap: wrap;
        gap: 6px
    }

    .lineup-columns span {
        display: inline-flex;
        gap: 6px;
        align-items: center;
        padding: 5px 7px;
        border: 1px solid var(--color-border-strong);
        border-radius: 4px;
        color: var(--color-text-secondary);
        background: var(--color-surface-panel);
        font-size: 11px
    }

    .lineup-columns span b {
        color: var(--mint);
        font: 9px var(--font-mono)
    }

    .play-details small {
        color: var(--color-text-tertiary)
    }

    @media (max-width: 720px) {
        .situation {
            display: grid;
            grid-template-columns:1fr 1fr
        }

        dl {
            grid-template-columns:1fr 1fr
        }

        .on-field-heading {
            display: grid
        }

        .lineup-columns {
            grid-template-columns:1fr
        }

        .lineup-columns section + section {
            border-top: 1px solid var(--line);
            border-left: 0
        }

        .field-wrap {
            padding-inline: 12px
        }

        .reconstruction-meta {
            display: grid;
            padding-inline: 12px
        }

        .source-badges {
            justify-content: flex-start
        }
    }

    @media (prefers-reduced-motion: reduce) {
        .play-path, .field-player {
            animation: none
        }
    }
</style>

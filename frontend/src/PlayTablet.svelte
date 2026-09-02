<script lang="ts">
    import type {Evidence} from './types';
    import {
        buildPlaySchematic,
        describeHash,
        describeQbAlignment,
        FOOTBALL_FIELD_WIDTH,
        NFL_HASH_FROM_SIDELINE,
        OFFENSIVE_LINE_HALF_WIDTH,
        type SchematicPlayer
    } from './playSchematic';
    import {colorContrastRatio, NFL_TEAM_NAMES, teamChartPalette, teamLogoUrl} from './teamPalettes';

    export let play: Evidence;
    export let onclose: () => void;

    let focusedPlayerId: string | null = null;
    let focusedMarkerIndex: number | null = null;
    const fieldMidpoint = FOOTBALL_FIELD_WIDTH / 2;
    const fiveYardLines = Array.from({length: 19}, (_, index) => 15 + index * 5);
    const numberedYardLines = Array.from({length: 9}, (_, index) => 20 + index * 10);
    const oneYardTicks = Array.from({length: 99}, (_, index) => 11 + index).filter((yard) => yard % 5 !== 0);
    const hashRows = [NFL_HASH_FROM_SIDELINE, FOOTBALL_FIELD_WIDTH - NFL_HASH_FROM_SIDELINE];

    $: offenseTeam = play.visualization?.possession_team ?? play.team ?? '';
    $: defenseTeam = play.visualization?.defensive_team ?? '';
    $: homeTeam = play.visualization?.home_team_abbreviation ?? inferredHomeTeam(play.game_id) ?? offenseTeam;
    $: offensePalette = teamChartPalette(offenseTeam);
    $: defensePalette = teamChartPalette(defenseTeam);
    $: homePalette = teamChartPalette(homeTeam);
    $: homeTeamName = NFL_TEAM_NAMES[homeTeam.toUpperCase()] ?? homeTeam.toUpperCase();
    $: endzoneTextColor = colorContrastRatio(homePalette[0], homePalette[1]) >= 3
        ? homePalette[1]
        : colorContrastRatio(homePalette[0], '#F4F8FA') >= 4.5 ? '#F4F8FA' : '#07121D';
    $: homeLogo = teamLogoUrl(homeTeam);
    $: schematic = buildPlaySchematic(play.visualization);
    $: sourcePackages = play.visualization?.source_packages ?? ['play_by_play'];
    $: markerPrefix = `play-${play.evidence_id.replace(/[^a-zA-Z0-9]/g, '')}`;
    $: offensePlayers = playerRows(play.visualization?.offense_names, play.visualization?.offense_positions);
    $: defensePlayers = playerRows(play.visualization?.defense_names, play.visualization?.defense_positions);
    $: focusedPlayer = schematic.players.find(player => player.id === focusedPlayerId) ?? null;
    $: focusedMarker = focusedMarkerIndex == null ? null : schematic.markers[focusedMarkerIndex] ?? null;

    function sourceLabel(source: string) {
        return source === 'play_by_play' ? 'PBP' : source === 'participation' ? 'PARTICIPATION' : source === 'ftn_charting' ? 'FTN' : source.toUpperCase();
    }

    function inferredHomeTeam(gameId?: string) {
        const candidate = gameId?.split('_').at(-1)?.toUpperCase();
        return candidate && teamLogoUrl(candidate) ? candidate : null;
    }

    function pathColor(kind: string) {
        if (kind === 'return') return '#ff9d66';
        if (kind === 'after-catch') return offensePalette[1];
        return offensePalette[0];
    }

    function pathMarker(kind: string) {
        return `url(#${markerPrefix}-${kind})`;
    }

    function yardArrowPath(x: number, y: number) {
        const pointsLeft = x < 60;
        const innerEdge = pointsLeft ? x - 2.35 : x + 2.35;
        const tip = pointsLeft ? innerEdge - 1.05 : innerEdge + 1.05;
        return `M ${tip} ${y} L ${innerEdge} ${y - .78} L ${innerEdge} ${y + .78} Z`;
    }

    function playerRows(names: string[] = [], positions: string[] = []) {
        return names.map((name, index) => ({name, position: positions[index] ?? '—'}));
    }

    function playerPalette(side: 'offense' | 'defense') {
        return side === 'offense' ? offensePalette : defensePalette;
    }

    function markerTextColor(side: 'offense' | 'defense') {
        return colorContrastRatio(playerPalette(side)[0], '#F4F8FA') >= 4.5 ? '#F4F8FA' : '#07121D';
    }

    function recordedFlag(value: boolean | null | undefined, yes: string, no = 'No') {
        return value == null ? 'Not recorded' : value ? yes : no;
    }

    function tooltipLabel(player: SchematicPlayer) {
        const identity = player.recorded ? `${player.name} · ${player.position}` : `${player.position} · Identity not recorded`;
        const assignment = player.rushRole === 'blitzer' ? 'inferred blitzer'
            : player.rushRole === 'rusher' ? 'inferred rusher'
                : player.inBox ? 'inferred in box' : '';
        return [identity, assignment].filter(Boolean).join(' · ');
    }

    function tooltipWidth(player: SchematicPlayer) {
        return Math.min(48, Math.max(11, tooltipLabel(player).length * .6 + 1.4));
    }

    function tooltipX(player: SchematicPlayer) {
        const halfWidth = tooltipWidth(player) / 2;
        return Math.max(halfWidth + .8, Math.min(120 - halfWidth - .8, player.x));
    }

    function eventTooltipWidth(label: string) {
        return Math.min(44, Math.max(10, label.length * .62 + 1.6));
    }

    function eventTooltipX(marker: {label: string; x: number}) {
        const halfWidth = eventTooltipWidth(marker.label) / 2;
        return Math.max(halfWidth + .8, Math.min(120 - halfWidth - .8, marker.x));
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
        <div><strong>{schematic.lineupMode === 'recorded' ? 'Recorded participants' : schematic.lineupMode === 'hybrid' ? 'Recorded participants · completed formation' : 'Formation-template lineup'}</strong>
            <span>{schematic.context.formation} · {schematic.context.offensivePersonnel} offense · {schematic.context.defensivePersonnel} defense · {schematic.context.boxCount} in box{schematic.context.boxCountRecorded ? '' : ' (estimated)'} · {schematic.context.passRusherCount} rushers{schematic.context.passRusherCountRecorded ? '' : ' (estimated)'}</span>
        </div>
        <div class="source-badges" aria-label="Sources used by this schematic">
            {#each sourcePackages as source}<span>{sourceLabel(source)}</span>{/each}
        </div>
    </div>
    <div class="field-wrap">
        <svg class="field" viewBox={`0 0 120 ${FOOTBALL_FIELD_WIDTH}`} style={`--venue-primary:${homePalette[0]};--venue-secondary:${homePalette[1]};--venue-endzone-text:${endzoneTextColor}`} role="img" aria-label={`Reconstructed play on ${homeTeam}'s home field showing lineup and ball movement`}>
            <defs>
                <filter id={`${markerPrefix}-glow`} x="-60%" y="-60%" width="220%" height="220%" color-interpolation-filters="sRGB">
                    <feGaussianBlur stdDeviation="1.05" result="blur"/>
                    <feMerge><feMergeNode in="blur"/><feMergeNode in="blur"/></feMerge>
                </filter>
                {#each ['pass', 'carry', 'after-catch', 'return'] as kind}
                    <marker id={`${markerPrefix}-${kind}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="3.5" markerHeight="3.5" orient="auto-start-reverse">
                        <path d="M 0 0 L 10 5 L 0 10 z" fill={pathColor(kind)}/>
                    </marker>
                {/each}
            </defs>
            <rect width="120" height={FOOTBALL_FIELD_WIDTH} rx="1" class="turf"/>
            <rect x="0" width="10" height={FOOTBALL_FIELD_WIDTH} class="endzone"/>
            <rect x="110" width="10" height={FOOTBALL_FIELD_WIDTH} class="endzone"/>
            <rect x=".35" y=".35" width="119.3" height={FOOTBALL_FIELD_WIDTH - .7} class="field-boundary"/>
            <text class="endzone-name" x="5" y={fieldMidpoint} textLength="42" lengthAdjust="spacingAndGlyphs" transform={`rotate(90 5 ${fieldMidpoint})`} aria-hidden="true">{homeTeamName}</text>
            <text class="endzone-name" x="115" y={fieldMidpoint} textLength="42" lengthAdjust="spacingAndGlyphs" transform={`rotate(-90 115 ${fieldMidpoint})`} aria-hidden="true">{homeTeamName}</text>
            <line x1="10" x2="10" y1=".35" y2={FOOTBALL_FIELD_WIDTH - .35} class="goal-line"/>
            <line x1="110" x2="110" y1=".35" y2={FOOTBALL_FIELD_WIDTH - .35} class="goal-line"/>
            <g class="midfield-brand" aria-label={`${homeTeam} midfield logo`}>
                <circle cx="60" cy={fieldMidpoint} r="7.2"/>
                <text x="60" y={fieldMidpoint + .5}>{homeTeam}</text>
                {#if homeLogo}<image href={homeLogo} x="54" y={fieldMidpoint - 6} width="12" height="12" preserveAspectRatio="xMidYMid meet"/>{/if}
            </g>
            {#each fiveYardLines as x}
                <line x1={x} x2={x} y1=".35" y2={FOOTBALL_FIELD_WIDTH - .35} class:major-yard-line={(x - 10) % 10 === 0} class="yard-line"/>
            {/each}
            {#each oneYardTicks as x}
                <line x1={x} x2={x} y1=".45" y2="1.18" class="sideline-tick"/>
                <line x1={x} x2={x} y1={FOOTBALL_FIELD_WIDTH - 1.18} y2={FOOTBALL_FIELD_WIDTH - .45} class="sideline-tick"/>
                {#each hashRows as hashY}
                    <line x1={x} x2={x} y1={hashY - 1 / 3} y2={hashY + 1 / 3} class="inbound-hash"/>
                {/each}
            {/each}
            {#each numberedYardLines as x, marker}
                {@const yardNumber = marker < 5 ? (marker + 1) * 10 : (9 - marker) * 10}
                <text x={x} y="11.8" class="yard-number top" transform={`rotate(180 ${x} 11.8)`}>{yardNumber}</text>
                <text x={x} y={FOOTBALL_FIELD_WIDTH - 11.8} class="yard-number bottom">{yardNumber}</text>
                {#if yardNumber !== 50}
                    <path d={yardArrowPath(x, 11.8)} class="yard-direction top" data-yard-number={yardNumber}/>
                    <path d={yardArrowPath(x, FOOTBALL_FIELD_WIDTH - 11.8)} class="yard-direction bottom" data-yard-number={yardNumber}/>
                {/if}
            {/each}
            <rect
                x={schematic.startX - .25}
                y={schematic.hashY - OFFENSIVE_LINE_HALF_WIDTH}
                width="6.5"
                height={OFFENSIVE_LINE_HALF_WIDTH * 2}
                class="box-area"
                aria-label={`Reconstructed tackle box containing ${schematic.context.boxCount} defenders`}
            />
            <line x1={schematic.startX} x2={schematic.startX} y1="1.4" y2={FOOTBALL_FIELD_WIDTH - 1.4} class="scrimmage"/>
            {#if play.visualization?.yards_to_go != null}
                <line x1={schematic.lineToGainX} x2={schematic.lineToGainX} y1="1.4" y2={FOOTBALL_FIELD_WIDTH - 1.4} class="line-to-gain"/>
            {/if}
            {#each schematic.paths as segment}
                <path d={segment.d} class={`play-path-glow ${segment.kind}`} style={`stroke:${pathColor(segment.kind)}`} filter={`url(#${markerPrefix}-glow)`}/>
                <path d={segment.d} class={`play-path ${segment.kind}`} style={`stroke:${pathColor(segment.kind)}`} marker-end={pathMarker(segment.kind)}/>
            {/each}
            {#each schematic.players as player}
                <g class={`field-player ${player.side} ${player.recorded ? 'recorded resolved' : 'generic inferred'} ${player.inBox ? 'in-box' : ''} ${player.rushRole ?? ''}`} transform={`translate(${player.x} ${player.y})`} role="img" aria-label={tooltipLabel(player)} on:mouseenter={() => focusedPlayerId = player.id} on:mouseleave={() => focusedPlayerId = null}>
                    {#if player.rushRole}<circle class={`rush-ring ${player.rushRole}`} r="1.86"/>{/if}
                    <circle r="1.42" style={`fill:${playerPalette(player.side)[0]};stroke:${playerPalette(player.side)[1]}`}/>
                    <text class="position-label" y=".12" style={`fill:${markerTextColor(player.side)}`}>{player.position.slice(0, 3)}</text>
                </g>
            {/each}
            {#each schematic.markers as marker, markerIndex}
                <g class={`event-marker ${marker.kind}`} transform={`translate(${marker.x} ${marker.y})`}
                   role="button" tabindex="0" aria-label={marker.label}
                   on:mouseenter={() => focusedMarkerIndex = markerIndex} on:mouseleave={() => focusedMarkerIndex = null}
                   on:focus={() => focusedMarkerIndex = markerIndex} on:blur={() => focusedMarkerIndex = null}>
                    <circle r=".9"/>
                </g>
            {/each}
            {#if focusedPlayer}
                <g class="player-tooltip visible" transform={`translate(${tooltipX(focusedPlayer)} ${focusedPlayer.y})`} aria-hidden="true">
                    <rect x={-tooltipWidth(focusedPlayer) / 2} y={focusedPlayer.y < 7 ? 2.25 : -5.45} width={tooltipWidth(focusedPlayer)} height="3.2" rx=".55"/>
                    <text class="name-label" y={focusedPlayer.y < 7 ? 4.42 : -3.28}>{tooltipLabel(focusedPlayer)}</text>
                </g>
            {/if}
            {#if focusedMarker}
                <g class="event-tooltip visible" transform={`translate(${eventTooltipX(focusedMarker)} ${focusedMarker.y})`} aria-hidden="true">
                    <rect x={-eventTooltipWidth(focusedMarker.label) / 2} y={focusedMarker.y < 7 ? 2.1 : -5.25} width={eventTooltipWidth(focusedMarker.label)} height="3.05" rx=".52"/>
                    <text y={focusedMarker.y < 7 ? 4.18 : -3.18}>{focusedMarker.label}</text>
                </g>
            {/if}
        </svg>
        <div class="field-legend">
            <span><i class="offense-key" style={`background:${offensePalette[0]};border-color:${offensePalette[1]}`}></i>{play.visualization?.possession_team ?? play.team} offense</span>
            <span><i class="defense-key" style={`background:${defensePalette[0]};border-color:${defensePalette[1]}`}></i>{play.visualization?.defensive_team ?? 'Defense'}</span>
            <span><i class="box-key"></i>Reconstructed box</span>
            <span><i class="flight-key"></i>Ball flight</span>
            {#if schematic.players.some(player => player.rushRole === 'rusher')}<span><i class="rush-key"></i>Inferred rusher</span>{/if}
            {#if schematic.players.some(player => player.rushRole === 'blitzer')}<span><i class="blitz-key"></i>Inferred blitzer</span>{/if}
            {#if schematic.paths.some(path => path.kind === 'after-catch')}<span><i class="yac-key"></i>After catch</span>{/if}
            {#if schematic.paths.some(path => path.kind === 'return')}<span><i class="return-key"></i>Turnover return</span>{/if}
        </div>
    </div>
    <div class="play-details">
        <p>{play.description}</p>
        <dl>
            <div>
                <dt>Formation <i>PBP</i></dt>
                <dd>{schematic.context.formation}{play.visualization?.no_huddle ? ' · No huddle' : ''}</dd>
            </div>
            <div>
                <dt>Personnel <i>PART</i></dt>
                <dd>Offense: {schematic.context.offensivePersonnel}<br/>Defense: {schematic.context.defensivePersonnel}</dd>
            </div>
            <div>
                <dt>Alignment <i>FTN</i></dt>
                <dd>{describeHash(play.visualization?.starting_hash)} · {describeQbAlignment(play.visualization ?? {})}{play.visualization?.offense_backfield_count != null ? ` · ${play.visualization.offense_backfield_count} in backfield` : ''}</dd>
            </div>
            <div>
                <dt>Box & rush <i>PART/FTN</i></dt>
                <dd>{schematic.context.boxCount} in box{schematic.context.boxCountRecorded ? '' : ' (estimated)'} · {schematic.context.passRusherCount} rushers{schematic.context.passRusherCountRecorded ? '' : ' (estimated)'} · {schematic.context.blitzerCount} blitzers{schematic.context.blitzerCountRecorded ? '' : ' (estimated)'}</dd>
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
                <dd>{schematic.context.coverage}{play.visualization?.read_thrown ? ` · ${play.visualization.read_thrown} read` : ''}</dd>
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
                <div class="on-field-heading"><strong>Recorded on-field personnel</strong><span>Identities are recorded; placement uses personnel, formation, box, rush, and coverage constraints</span></div>
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
        <small>The tablet uses recorded identities and football-context constraints wherever the local packages provide them. Exact player coordinates, individual rusher/blitzer assignments, and ball curves remain inferred because these sources do not provide tracking coordinates or assignment identities.</small>
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
        height: auto;
        aspect-ratio: 120 / 53.333;
        border: 1px solid color-mix(in srgb, var(--mint) 24%, var(--line));
        background: transparent
    }

    .turf {
        fill: rgb(90 230 135 / 0.5)
    }

    .endzone {
        fill: var(--venue-primary);
        opacity: .9
    }

    .endzone-name {
        fill: var(--venue-endzone-text);
        font: 800 4.2px var(--font-sans);
        letter-spacing: .08em;
        text-anchor: middle;
        dominant-baseline: middle;
        paint-order: stroke;
        stroke: rgb(0 0 0 / 22%);
        stroke-width: .16;
        pointer-events: none
    }

    .goal-line {
        stroke: var(--venue-secondary);
        stroke-width: .7;
        opacity: .95
    }

    .field-boundary {
        fill: none;
        stroke: #f4f7f8;
        stroke-width: .42;
        opacity: .9
    }

    .midfield-brand circle {
        fill: color-mix(in srgb, var(--venue-primary) 22%, rgb(3 40 27 / 68%));
        stroke: var(--venue-secondary);
        stroke-width: .32;
        opacity: .82
    }

    .midfield-brand text {
        fill: var(--venue-secondary);
        font: 700 2.25px var(--font-mono);
        text-anchor: middle;
        dominant-baseline: middle;
        opacity: .3
    }

    .midfield-brand image {
        opacity: .72;
        filter: drop-shadow(0 .45px .55px rgb(0 0 0 / 45%))
    }

    .yard-line {
        stroke: #dbe8ee;
        stroke-width: .13;
        opacity: .38
    }

    .yard-line.major-yard-line {
        stroke-width: .24;
        opacity: .66
    }

    .yard-number {
        fill: rgb(244 248 250 / 72%);
        font: 600 2.75px var(--font-sans);
        text-anchor: middle;
        dominant-baseline: middle
    }

    .inbound-hash,
    .sideline-tick {
        stroke: #dbe8ee;
        stroke-width: .2;
        opacity: .72
    }

    .sideline-tick {
        stroke-width: .16;
        opacity: .58
    }

    .yard-direction {
        fill: rgb(244 248 250 / 65%)
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

    .box-area {
        fill: rgb(245 196 81 / 4%);
        stroke: rgb(245 196 81 / 44%);
        stroke-width: .2;
        stroke-dasharray: .55 .45;
        pointer-events: none
    }

    .play-path,
    .play-path-glow {
        fill: none;
        stroke-linecap: round;
        stroke-linejoin: round;
        stroke-dasharray: 1.2 1.15;
    }

    .play-path {
        stroke-width: .68;
        animation: draw-path .8s ease-out both, travel-dashes 1.6s linear infinite
    }

    .play-path-glow {
        stroke-width: 1.65;
        pointer-events: none;
        animation: path-breathe 2.35s ease-in-out infinite, travel-dashes 1.6s linear infinite
    }

    .play-path.after-catch,
    .play-path-glow.after-catch {
        stroke-dasharray: 2 .85
    }

    .play-path.return,
    .play-path-glow.return {
        stroke-dasharray: .65 .85
    }

    .field-player {
        cursor: help;
        outline: none;
        animation: settle-player .35s ease-out both
    }

    .field-player circle {
        stroke-width: .34;
        vector-effect: non-scaling-stroke
    }

    .field-player.inferred circle:not(.rush-ring) {
        opacity: .74;
        stroke-dasharray: 1 1
    }

    .field-player .rush-ring {
        fill: none;
        stroke: #f5c451;
        stroke-width: .34;
        stroke-dasharray: none;
        opacity: .95;
        filter: drop-shadow(0 0 .55px rgb(245 196 81 / 75%));
        pointer-events: none
    }

    .field-player .rush-ring.blitzer {
        stroke: #ff8b5d;
        stroke-dasharray: .7 .38;
        filter: drop-shadow(0 0 .65px rgb(255 139 93 / 82%))
    }

    .position-label {
        fill: #07121d;
        font: 1.02px var(--font-mono);
        font-weight: 800;
        text-anchor: middle;
        dominant-baseline: middle;
        pointer-events: none
    }

    .player-tooltip {
        opacity: 0;
        pointer-events: none;
        transition: opacity .14s ease-out
    }

    .player-tooltip.visible {
        opacity: 1;
        filter: drop-shadow(0 .8px 1.6px rgb(0 0 0 / 72%))
    }

    .player-tooltip rect {
        fill: rgb(4 18 29 / 96%);
        stroke: rgb(228 240 245 / 38%);
        stroke-width: .2
    }

    .name-label {
        fill: #f4f8fa;
        font: 1.05px var(--font-sans);
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

    .event-marker {
        cursor: help;
        outline: none
    }

    .event-marker:focus circle {
        stroke: var(--mint);
        stroke-width: .55
    }

    .event-marker.turnover circle { fill: #ff754f }
    .event-marker.recovery circle { fill: #ffb35c }
    .event-marker.touchdown circle { fill: var(--mint) }
    .event-marker.catch circle { fill: #ecf3f6 }

    .event-tooltip {
        opacity: 0;
        pointer-events: none;
        transition: opacity .14s ease-out
    }

    .event-tooltip.visible {
        opacity: 1;
        filter: drop-shadow(0 .7px 1.35px rgb(0 0 0 / 72%))
    }

    .event-tooltip rect {
        fill: rgb(4 19 30 / 92%);
        stroke: rgb(218 233 240 / 25%);
        stroke-width: .2
    }

    .event-tooltip text {
        fill: #f2f7f9;
        font: 1px var(--font-mono);
        font-weight: 600;
        text-anchor: middle;
        pointer-events: none
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
    .field-legend .box-key { color: #f5c451; border-top-style: dashed }
    .field-legend .rush-key { color: #f5c451; border-top-style: solid }
    .field-legend .blitz-key { color: #ff8b5d; border-top-style: dotted }

    @keyframes draw-path {
        from { opacity: 0; stroke-dashoffset: 12 }
        to { opacity: 1; stroke-dashoffset: 0 }
    }

    @keyframes travel-dashes {
        to { stroke-dashoffset: -8 }
    }

    @keyframes path-breathe {
        0%, 100% { opacity: .18; stroke-width: 1.25 }
        50% { opacity: .58; stroke-width: 1.9 }
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
        .play-path, .play-path-glow, .field-player {
            animation: none
        }

        .play-path-glow { opacity: .32 }
    }
</style>

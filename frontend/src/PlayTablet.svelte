<script lang="ts">
    import type {Evidence} from './types';
import FootballField from './FootballField.svelte';
import FootballTablet from './FootballTablet.svelte';
import FootballTooltip from './FootballTooltip.svelte';
    import {
        buildPlaySchematic,
        describeHash,
        describeQbAlignment,
        FOOTBALL_FIELD_WIDTH,
        OFFENSIVE_LINE_HALF_WIDTH,
        type SchematicPlayer
    } from './playSchematic';
    import {colorContrastRatio, NFL_TEAM_NAMES, teamChartPalette, teamLogoUrl} from './teamPalettes';

    export let play: Evidence;
    export let onclose: () => void;

    let focusedPlayerId: string | null = null;
    let focusedMarkerIndex: number | null = null;

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

<FootballTablet label={`Play schematic for ${play.game_id}, play ${play.play_id}`}>
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
        <FootballField venueName={homeTeamName} venueAbbreviation={homeTeam} venueLogo={homeLogo} primary={homePalette[0]} secondary={homePalette[1]} textColor={endzoneTextColor} label={`Reconstructed play on ${homeTeam}'s home field showing lineup and ball movement`}>
            <defs slot="defs">
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
                <FootballTooltip label={tooltipLabel(focusedPlayer)} x={tooltipX(focusedPlayer)} y={focusedPlayer.y} width={tooltipWidth(focusedPlayer)}/>
            {/if}
            {#if focusedMarker}
                <FootballTooltip label={focusedMarker.label} x={eventTooltipX(focusedMarker)} y={focusedMarker.y} width={eventTooltipWidth(focusedMarker.label)} event/>
            {/if}
        </FootballField>
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
</FootballTablet>

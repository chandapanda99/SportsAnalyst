<script lang="ts">
import type {Evidence} from "./types";
import {buildPlaySchematic, FOOTBALL_FIELD_WIDTH, NFL_HASH_FROM_SIDELINE, OFFENSIVE_LINE_HALF_WIDTH, type SchematicPlayer} from "./playSchematic";
import {colorContrastRatio} from "./teamPalettes";
import FootballField from "./FootballField.svelte";
import FootballTooltip from "./FootballTooltip.svelte";
import SchematicViewport from './SchematicViewport.svelte';
export let play: Evidence;
export let homeTeamName: string; export let homeTeam: string; export let homeLogo: string | null;
export let homePalette: readonly string[]; export let offensePalette: readonly string[]; export let defensePalette: readonly string[]; export let endzoneTextColor: string;
export let hashFromSideline=NFL_HASH_FROM_SIDELINE;
export let fieldLabel="Football schematic"; export let illustrative=false;
export let movementLabel = '';
export let showPlayers=true; export let showMovement=true; export let showFieldPosition=true;
let focusedPlayerId: string | null=null; let focusedMarkerIndex: number | null=null;
let selectedLabel = '';
let selectedKey = '';
function selectMarker(key: string, label: string) {selectedKey = key; selectedLabel = label;}
$: schematic=buildPlaySchematic(play.visualization, hashFromSideline);
$: markerPrefix="schematic-"+play.evidence_id.replace(/[^a-zA-Z0-9]/g,"");
$: focusedPlayer=showPlayers ? schematic.players.find(player=>player.id===focusedPlayerId) : null;
$: focusedMarker=showMovement && focusedMarkerIndex!=null ? schematic.markers[focusedMarkerIndex] : null;
$: markerOptions = [
    ...(showPlayers ? schematic.players.map(player => ({id: player.id, label: tooltipLabel(player)})) : []),
    ...(showMovement ? schematic.markers.map((marker, index) => ({id: `event-${index}`, label: eventLabel(marker.label)})) : []),
];
$: if (play.evidence_id) { focusedPlayerId=null; focusedMarkerIndex=null; selectedLabel=''; selectedKey=''; }
function eventLabel(label: string) {return illustrative ? label+" · illustrative location" : label;}
    function pathColor(kind: string) {
        if (kind === 'return') return '#ff9d66';
        if (kind === 'after-catch') return offensePalette[1];
        return offensePalette[0];
    }

    function pathMarker(kind: string) {
        return `url(#${markerPrefix}-${kind})`;
    }

    function playerPalette(side: 'offense' | 'defense') {
        return side === 'offense' ? offensePalette : defensePalette;
    }

    function markerTextColor(side: 'offense' | 'defense') {
        return colorContrastRatio(playerPalette(side)[0], '#F4F8FA') >= 4.5 ? '#F4F8FA' : '#07121D';
    }

    function tooltipLabel(player: SchematicPlayer) {
        const identity = player.projected ? `${player.name} · ${player.position} · Projected starter, not confirmed on this play`
            : player.recorded ? `${player.name} · ${player.position}` : `${player.position} · Identity not recorded`;
        const assignment = player.rushRole === 'blitzer' ? 'inferred blitzer'
            : player.rushRole === 'rusher' ? 'inferred rusher'
                : player.inBox ? 'inferred in box' : '';
        return [identity, assignment, illustrative ? "illustrative placement" : ""].filter(Boolean).join(' · ');
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
    <div class="field-wrap">
        <SchematicViewport label="field" focusX={schematic.startX / 120 * 100} focusY={schematic.hashY / FOOTBALL_FIELD_WIDTH * 100} selection={selectedLabel} markers={markerOptions} selectedMarker={selectedKey} onselect={(id) => selectMarker(id, markerOptions.find(marker => marker.id === id)?.label ?? '')} onclear={() => {selectedLabel = ''; selectedKey = '';}}>
        <FootballField venueName={homeTeamName} venueAbbreviation={homeTeam} venueLogo={homeLogo} primary={homePalette[0]} secondary={homePalette[1]} textColor={endzoneTextColor} hashFromSideline={hashFromSideline} label={fieldLabel}>
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
            {#if showPlayers}
            <rect
                x={schematic.startX - .25}
                y={schematic.hashY - OFFENSIVE_LINE_HALF_WIDTH}
                width="6.5"
                height={OFFENSIVE_LINE_HALF_WIDTH * 2}
                class="box-area"
                aria-label={`Reconstructed tackle box containing ${schematic.context.boxCount} defenders`}
            />
            {/if}
            {#if showFieldPosition}
            <line x1={schematic.startX} x2={schematic.startX} y1="1.4" y2={FOOTBALL_FIELD_WIDTH - 1.4} class="scrimmage"/>
            {#if play.visualization?.yards_to_go != null}
                <line x1={schematic.lineToGainX} x2={schematic.lineToGainX} y1="1.4" y2={FOOTBALL_FIELD_WIDTH - 1.4} class="line-to-gain"/>
            {/if}
            {/if}
            {#if showMovement}
            {#each schematic.paths as segment}
                <path d={segment.d} class={`play-path-glow ${segment.kind}`} style={`stroke:${pathColor(segment.kind)}`} filter={`url(#${markerPrefix}-glow)`}/>
                <path d={segment.d} class={`play-path ${segment.kind}`} style={`stroke:${pathColor(segment.kind)}`} marker-end={pathMarker(segment.kind)}/>
            {/each}
            {/if}
            {#if showPlayers}
            {#each schematic.players as player}
                <g class={`field-player ${player.side} ${player.projected ? 'projected inferred' : player.recorded ? 'recorded resolved' : 'generic inferred'} ${player.inBox ? 'in-box' : ''} ${player.rushRole ?? ''}`} class:selected={selectedKey === player.id} transform={`translate(${player.x} ${player.y})`} role="button" tabindex="0" aria-label={tooltipLabel(player)} aria-pressed={selectedKey === player.id} on:click={() => selectMarker(player.id, tooltipLabel(player))} on:focus={() => focusedPlayerId = player.id} on:blur={() => focusedPlayerId = null} on:keydown={(event) => {if (['Enter', ' '].includes(event.key)) {event.preventDefault(); focusedPlayerId = player.id; selectMarker(player.id, tooltipLabel(player));}}} on:mouseenter={() => focusedPlayerId = player.id} on:mouseleave={() => focusedPlayerId = null}>
                    {#if player.rushRole}<circle class={`rush-ring ${player.rushRole}`} r="1.86"/>{/if}
                    <circle r="1.42" style={`fill:${playerPalette(player.side)[0]};stroke:${playerPalette(player.side)[1]}`}/>
                    <text class="position-label" y=".12" style={`fill:${markerTextColor(player.side)}`}>{player.position.slice(0, 3)}</text>
                </g>
            {/each}
            {/if}
            {#if showMovement}
            {#each schematic.markers as marker, markerIndex}
                <g class={`event-marker ${marker.kind}`} transform={`translate(${marker.x} ${marker.y})`}
                   role="button" tabindex="0" aria-label={eventLabel(marker.label)}
                   aria-pressed={selectedKey === `event-${markerIndex}`} class:selected={selectedKey === `event-${markerIndex}`}
                   on:click={() => selectMarker(`event-${markerIndex}`, eventLabel(marker.label))}
                   on:keydown={(event) => {if (['Enter', ' '].includes(event.key)) {event.preventDefault(); selectMarker(`event-${markerIndex}`, eventLabel(marker.label));}}}
                   on:mouseenter={() => focusedMarkerIndex = markerIndex} on:mouseleave={() => focusedMarkerIndex = null}
                   on:focus={() => focusedMarkerIndex = markerIndex} on:blur={() => focusedMarkerIndex = null}>
                    <circle r=".9"/>
                </g>
            {/each}
            {/if}
            {#if focusedPlayer}
                <FootballTooltip label={tooltipLabel(focusedPlayer)} x={tooltipX(focusedPlayer)} y={focusedPlayer.y} width={tooltipWidth(focusedPlayer)}/>
            {/if}
            {#if focusedMarker}
                <FootballTooltip label={eventLabel(focusedMarker.label)} x={eventTooltipX(focusedMarker)} y={focusedMarker.y} width={eventTooltipWidth(focusedMarker.label)} event/>
            {/if}
        </FootballField>
        </SchematicViewport>
        <div class="field-legend">
            <span><i class="offense-key" style={`background:${offensePalette[0]};border-color:${offensePalette[1]}`}></i>{play.visualization?.possession_team ?? play.team} offense</span>
            <span><i class="defense-key" style={`background:${defensePalette[0]};border-color:${defensePalette[1]}`}></i>{play.visualization?.defensive_team ?? 'Defense'}</span>
            {#if showPlayers}<span><i class="box-key"></i>Reconstructed box</span>{/if}
            {#if showMovement}<span><i class="flight-key"></i>{movementLabel || (illustrative ? "Illustrative movement (net yards)" : "Ball flight")}</span>{/if}
            {#if showPlayers && schematic.players.some(player => player.rushRole === 'rusher')}<span><i class="rush-key"></i>Inferred rusher</span>{/if}
            {#if showPlayers && schematic.players.some(player => player.rushRole === 'blitzer')}<span><i class="blitz-key"></i>Inferred blitzer</span>{/if}
            {#if showMovement && schematic.paths.some(path => path.kind === 'after-catch')}<span><i class="yac-key"></i>After catch</span>{/if}
            {#if showMovement && schematic.paths.some(path => path.kind === 'return')}<span><i class="return-key"></i>Turnover return</span>{/if}
        </div>
    </div>


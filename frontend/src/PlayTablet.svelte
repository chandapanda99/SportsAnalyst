<script lang="ts">
    import type {Evidence} from './types';
    import FootballSchematic from './FootballSchematic.svelte';
    import FootballTablet from './FootballTablet.svelte';

    import {
        buildPlaySchematic,
        describeHash,
        describeQbAlignment
    } from './playSchematic';
    import {colorContrastRatio, NFL_TEAM_NAMES, teamChartPalette, teamLogoUrl} from './teamPalettes';

    export let play: Evidence;
    export let onclose: () => void;

    $: offenseTeam = play.visualization?.possession_team ?? play.team ?? '';
    $: defenseTeam = play.visualization?.defensive_team ?? '';
    $: homeTeam = play.visualization?.home_team_abbreviation ?? inferredHomeTeam(play.game_id) ?? offenseTeam;
    $: offensePalette = teamChartPalette(offenseTeam, 'nfl', play.season);
    $: defensePalette = teamChartPalette(defenseTeam, 'nfl', play.season);
    $: homePalette = teamChartPalette(homeTeam, 'nfl', play.season);
    $: homeTeamName = NFL_TEAM_NAMES[homeTeam.toUpperCase()] ?? homeTeam.toUpperCase();
    $: endzoneTextColor = colorContrastRatio(homePalette[0], homePalette[1]) >= 3
        ? homePalette[1]
        : colorContrastRatio(homePalette[0], '#F4F8FA') >= 4.5 ? '#F4F8FA' : '#07121D';
    $: homeLogo = teamLogoUrl(homeTeam, 'nfl', play.season);
    $: schematic = buildPlaySchematic(play.visualization);
    $: sourcePackages = play.visualization?.source_packages ?? ['play_by_play'];
    $: offensePlayers = playerRows(play.visualization?.offense_names, play.visualization?.offense_positions);
    $: defensePlayers = playerRows(play.visualization?.defense_names, play.visualization?.defense_positions);

    function sourceLabel(source: string) {
        return source === 'play_by_play' ? 'PBP' : source === 'participation' ? 'PARTICIPATION' : source === 'ftn_charting' ? 'FTN' : source.toUpperCase();
    }

    function inferredHomeTeam(gameId?: string) {
        const candidate = gameId?.split('_').at(-1)?.toUpperCase();
        return candidate && teamLogoUrl(candidate) ? candidate : null;
    }

    function playerRows(names: string[] = [], positions: string[] = []) {
        return names.map((name, index) => ({name, position: positions[index] ?? '—'}));
    }

    function recordedFlag(value: boolean | null | undefined, yes: string, no = 'No') {
        return value == null ? 'Not recorded' : value ? yes : no;
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
    <FootballSchematic {play} {homeTeamName} {homeTeam} {homeLogo} {homePalette} {offensePalette} {defensePalette} {endzoneTextColor} fieldLabel={`Reconstructed play on ${homeTeam}'s home field showing lineup and ball movement`}/>
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

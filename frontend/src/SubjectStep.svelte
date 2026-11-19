<script lang="ts">
  import type {ComponentProps} from 'svelte';
  import CFBDiscovery from './CFBDiscovery.svelte';
  import Icon from './Icon.svelte';
  import PlayerPortrait from './PlayerPortrait.svelte';
  import SubjectSearch from './SubjectSearch.svelte';
  import type {PlayerOption, TeamOption} from './types';

  type CFBSelection = Parameters<ComponentProps<typeof CFBDiscovery>['onchange']>[0];

  /** The step number shown on the card, such as "2". */
  export let step: string;
  export let activeSport: string;
  export let busy: boolean;
  export let subjectType: 'team' | 'player';
  export let headToHead: boolean;
  export let team: string;
  export let teamInput: string;
  export let teamFilter: string;
  export let teamComboboxOpen: boolean;
  export let activeTeamIndex: number;
  export let filteredTeams: TeamOption[];
  export let resolvedTeam: string;
  export let players: PlayerOption[];
  export let playersLoading: boolean;
  export let playerLoadError: string;
  export let playerSearching: boolean;
  export let playerInput: string;
  export let playerFilter: string;
  export let playerComboboxOpen: boolean;
  export let activePlayerIndex: number;
  export let filteredPlayers: PlayerOption[];
  export let selectedPlayerId: string;
  export let selectedPlayer: PlayerOption | null;
  export let playerTeamId: string;
  export let resolvedSubject: string;
  export let cfbBrowseSeason: number;
  export let cfbSubdivision: string;
  export let cfbConference: string;
  export let cfbHistoryLoading: boolean;
  export let compareOptions: Array<{value: string; label: string; detail?: string}>;
  export let compareSubjectId: string;
  export let compareCfbSchool: string;
  export let comparePlayersLoading: boolean;
  export let cfbSelectionChanged: (selection: CFBSelection) => void;
  export let compareCfbChanged: (selection: CFBSelection) => void;
  export let openTeamCombobox: (event: FocusEvent) => void;
  export let updateTeamFilter: () => void;
  export let handleTeamKeydown: (event: KeyboardEvent) => void;
  export let selectTeam: (option: TeamOption) => void;
  export let openPlayerCombobox: (event: FocusEvent) => void;
  export let updatePlayerFilter: () => void;
  export let handlePlayerKeydown: (event: KeyboardEvent) => void;
  export let selectPlayer: (player: PlayerOption) => Promise<void>;
  export let loadPlayers: () => Promise<void>;
  export let searchPlayers: (query: string) => void;
  export let playerTeamLabel: (team: string) => string;
  /** Asks for the subject again after Edit and rerun could not fill it in. */
  export let editNotice = '';
</script>

<section class="scope-card" class:cfb-subject-card={activeSport === 'cfb'} aria-labelledby="scope-heading">
  <div class="scope-heading">
    <div><span class="eyebrow step-label"><b class="step-number">{step}</b>Subject</span>
      <h3 id="scope-heading" tabindex="-1">{headToHead ? 'Who do you want to compare?' : 'Who do you want to understand?'}</h3></div>
  </div>
  {#if editNotice}<p class="validation" role="status">{editNotice}</p>{/if}
  {#if activeSport === 'cfb'}
    <CFBDiscovery initialSeason={cfbBrowseSeason} initialSubdivision={cfbSubdivision}
                  initialConference={cfbConference} initialTeam={team} disabled={busy} onchange={cfbSelectionChanged}/>
    {#if cfbHistoryLoading}<p role="status">Verifying this player’s seasons and transfer history…</p>{/if}
  {/if}
  {#if activeSport === 'cfb' && subjectType === 'player' && !resolvedTeam}
    <p class="section-help">Choose a school above to see its players.</p>
  {/if}
  <div class="scope-controls">
    {#if subjectType === 'player'}
      <div class="team-control">
        <label for="sport-player">Player</label>
        <div class="team-combobox">
          <input id="sport-player" role="combobox" bind:value={playerInput} aria-label="Player"
                 aria-expanded={playerComboboxOpen}
                 aria-busy={playersLoading} disabled={activeSport === 'cfb' && !resolvedTeam}
                 aria-controls="sport-player-options"
                 aria-autocomplete="list"
                 aria-activedescendant={playerComboboxOpen && filteredPlayers[activePlayerIndex] ? `player-option-${filteredPlayers[activePlayerIndex].player_id}` : undefined}
                 aria-invalid={Boolean(playerInput && !selectedPlayerId)} autocomplete="off" placeholder="Search players…"
                 on:focus={openPlayerCombobox}
                 on:input={updatePlayerFilter} on:keydown={handlePlayerKeydown} on:blur={() => playerComboboxOpen = false}/>
          <button class="combobox-toggle" type="button" aria-label={`Show ${activeSport.toUpperCase()} players`}
                  disabled={activeSport === 'cfb' && !resolvedTeam} tabindex="-1"
                  on:mousedown|preventDefault={() => playerComboboxOpen = !playerComboboxOpen}>
            {#if playersLoading}<span class="button-spinner" aria-hidden="true"></span>{:else}
              <Icon name="chevron-down" size={17}/>
            {/if}
          </button>
          {#if playerComboboxOpen}
            <div class="team-options" id="sport-player-options" role="listbox" aria-label={`${activeSport.toUpperCase()} players`}>
              {#if playersLoading}
                <div class="combobox-loading" role="status"><span class="button-spinner" aria-hidden="true"></span>
                  <span>Loading {activeSport.toUpperCase()} players…</span></div>
              {:else if playerLoadError}
                <div class="combobox-error"><span>{playerLoadError}</span>
                  <button type="button" on:mousedown|preventDefault={() => loadPlayers()}>Retry</button>
                </div>
              {:else}
                {#if activeSport === 'cfb' && players.some(player => player.discovery_source === 'recorded_game_participants')}
                  <div class="combobox-loading" role="status">Recorded offensive game participants · not a complete roster.</div>
                {/if}
                {#if activeSport === 'cfb' && players.some(player => player.discovery_source === 'partial_recorded_roster')}
                  <div class="combobox-loading" role="status">Recorded roster players · season roster coverage is incomplete.</div>
                {/if}
                {#each filteredPlayers as player, index}
                  <button id={`player-option-${player.player_id}`} type="button" role="option"
                          aria-selected={selectedPlayerId === player.player_id}
                          class:active={index === activePlayerIndex} on:mousedown|preventDefault={() => selectPlayer(player)}
                          on:mouseenter={() => activePlayerIndex = index}>
                    <span><PlayerPortrait id={player.player_id} sport={activeSport}
                                          name={player.name}/>{player.name}{player.positions.length ? ` · ${player.positions.join('/')}` : ''}</span>
                    <b>{player.teams.map(team => playerTeamLabel(team)).join('/')}</b>
                  </button>
                {:else}
                  <div class="no-team-results">{playerSearching ? 'Searching all players…' : `No players match “${playerFilter}”`}</div>
                {/each}
              {/if}
            </div>
          {/if}
        </div>
        {#if playerInput && !selectedPlayerId && !playersLoading}<small class="validation">Choose a player from the list.</small>{/if}
      </div>
      {#if selectedPlayer?.teams.length}
        <label>Team stint <select bind:value={playerTeamId}>
          <option value="">All teams in window</option>
          {#each selectedPlayer.teams as playerTeam}
            <option value={playerTeam}>{playerTeam}</option>
          {/each}
        </select></label>
      {/if}
    {:else if activeSport !== 'cfb'}
      <div class="team-control">
        <label for="sport-team">Team</label>
        <div class="team-combobox">
          <input id="sport-team" role="combobox" bind:value={teamInput} aria-label={`${activeSport.toUpperCase()} team`}
                 aria-expanded={teamComboboxOpen}
                 aria-controls="sport-team-options"
                 aria-autocomplete="list"
                 aria-activedescendant={teamComboboxOpen && filteredTeams[activeTeamIndex] ? `team-option-${filteredTeams[activeTeamIndex].value}` : undefined}
                 aria-invalid={Boolean(teamInput && !resolvedTeam)} autocomplete="off" placeholder="Search teams…"
                 on:focus={openTeamCombobox}
                 on:input={updateTeamFilter} on:keydown={handleTeamKeydown} on:blur={() => teamComboboxOpen = false}/>
          <button class="combobox-toggle" type="button" aria-label={`Show ${activeSport.toUpperCase()} teams`} tabindex="-1"
                  on:mousedown|preventDefault={() => teamComboboxOpen = !teamComboboxOpen}>
            <Icon name="chevron-down" size={17}/>
          </button>
          {#if teamComboboxOpen}
            <div class="team-options" id="sport-team-options" role="listbox" aria-label={`${activeSport.toUpperCase()} teams`}>
              {#each filteredTeams as option, index}
                <button id={`team-option-${option.value}`} type="button" role="option" aria-selected={team === option.value}
                        class:active={index === activeTeamIndex} on:mousedown|preventDefault={() => selectTeam(option)}
                        on:mouseenter={() => activeTeamIndex = index}>
                  <span>{option.label}</span><b>{option.value}</b>
                </button>
              {:else}
                <div class="no-team-results">No teams match “{teamFilter}”</div>
              {/each}
            </div>
          {/if}
        </div>
        {#if teamInput && !resolvedTeam}<small class="validation">Choose a team from the list.</small>{/if}
      </div>
    {/if}
  </div>
  {#if headToHead}
    <div class="compare-subject">
      <span class="versus" aria-hidden="true">vs</span>
      {#if activeSport === 'cfb'}
        <p class="section-help">Browse to the {subjectType === 'player' ? 'school of the player' : 'school'} to compare with.</p>
        <CFBDiscovery initialSeason={cfbBrowseSeason} initialSubdivision={cfbSubdivision} initialConference={cfbConference}
                      disabled={busy} onchange={compareCfbChanged}/>
        {#if subjectType === 'team' && compareCfbSchool && compareCfbSchool === resolvedTeam}
          <p class="validation">Choose a different school from the first one.</p>
        {/if}
      {/if}
      {#if activeSport !== 'cfb' || subjectType === 'player'}
        <div class="scope-controls">
          <SubjectSearch id="compare-subject" label="Compare with" options={compareOptions} value={compareSubjectId}
                         placeholder={subjectType === 'player' ? 'Search players…' : 'Search teams…'}
                         emptyMessage={activeSport === 'cfb' ? comparePlayersLoading ? 'Loading players…'
                             : compareCfbSchool ? 'No other players found at this school' : 'Choose a school above first'
                             : subjectType === 'player' ? 'No other players with data in every chosen season' : 'No other teams'}
                         onsearch={subjectType === 'player' && activeSport !== 'cfb' ? searchPlayers : undefined}
                         searching={playerSearching || comparePlayersLoading}
                         onselect={(value) => compareSubjectId = value}/>
        </div>
      {/if}
      {#if !resolvedSubject}<p class="section-help">Choose the first {subjectType} above, then who to compare with.</p>{/if}
    </div>
  {/if}
</section>

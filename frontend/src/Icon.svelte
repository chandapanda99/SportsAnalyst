<script lang="ts">
    type IconName =
        | 'arrow-right'
        | 'brain'
        | 'chevron-down'
        | 'click'
        | 'clipboard-plus'
        | 'database'
        | 'database-import'
        | 'file-download'
        | 'history'
        | 'play-card'
        | 'player-play'
        | 'refresh'
        | 'search'
        | 'send'
        | 'sparkles'
        | 'sports-analyst'
        | 'trash'
        | 'wand';

    export let name: IconName;
    export let size = 18;
</script>

<svg class="ui-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
     stroke-width={name === 'player-play' ? 1.5 : name === 'sports-analyst' ? 1.75 : 2}
     stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    {#if name === 'clipboard-plus'}
        <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"></path>
        <path d="M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-2a2 2 0 0 1-2-2M10 14h4m-2-2v4"></path>
    {:else if name === 'trash'}
        <path d="M4 7h16M10 11v6m4-6v6M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-12M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3"></path>
    {:else if name === 'database'}
        <path d="M4 6a8 3 0 1 0 16 0A8 3 0 1 0 4 6m0 0v6a8 3 0 0 0 16 0V6M4 12v6a8 3 0 0 0 16 0v-6"></path>
    {:else if name === 'chevron-down'}
        <path d="m6 9 6 6 6-6"></path>
    {:else if name === 'database-import'}
        <path
            d="M4 6c0 1.657 3.582 3 8 3s8-1.343 8-3-3.582-3-8-3-8 1.343-8 3m0 0v6c0 1.657 3.582 3 8 3 .856 0 1.68-.05 2.454-.144M20 12V6M4 12v6c0 1.657 3.582 3 8 3 .171 0 .341-.002.51-.006M19 22v-6m3 3-3-3-3 3"></path>
    {:else if name === 'arrow-right'}
        <path d="M5 12h14m-6 6 6-6-6-6"></path>
    {:else if name === 'sparkles'}
        <path
            d="M16 18a2 2 0 0 1 2 2 2 2 0 0 1 2-2 2 2 0 0 1-2-2 2 2 0 0 1-2 2m0-12a2 2 0 0 1 2 2 2 2 0 0 1 2-2 2 2 0 0 1-2-2 2 2 0 0 1-2 2M9 18a6 6 0 0 1 6-6 6 6 0 0 1-6-6 6 6 0 0 1-6 6 6 6 0 0 1 6 6"></path>
    {:else if name === 'wand'}
        <path
            d="m6 21 15-15-3-3L3 18l3 3m9-15 3 3M9 3a2 2 0 0 0 2 2 2 2 0 0 0-2 2 2 2 0 0 0-2-2 2 2 0 0 0 2-2m10 10a2 2 0 0 0 2 2 2 2 0 0 0-2 2 2 2 0 0 0-2-2 2 2 0 0 0 2-2"></path>
    {:else if name === 'refresh'}
        <path d="M20 11A8.1 8.1 0 0 0 4.5 9M4 5v4h4m-4 4a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4"></path>
    {:else if name === 'play-card'}
        <path d="M19 5v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2M8 6h.01M16 18h.01M12 16l-3-4 3-4 3 4-3 4"></path>
    {:else if name === 'player-play'}
        <path d="M7 4v16l13-8-13-8"></path>
    {:else if name === 'file-download'}
        <path d="M14 3v4a1 1 0 0 0 1 1h4M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2m-5-4v-6m-2.5 3.5L12 17l2.5-2.5"></path>
    {:else if name === 'search'}
        <path d="M3 10a7 7 0 1 0 14 0 7 7 0 1 0-14 0m18 11-6-6"></path>
    {:else if name === 'click'}
        <path d="M3 12h3m6-9v3M7.8 7.8 5.6 5.6m10.6 2.2 2.2-2.2M7.8 16.2l-2.2 2.2M12 12l9 3-4 2-2 4-3-9"></path>
    {:else if name === 'send'}
        <path d="M10 14 21 3m0 0-6.5 18a.55.55 0 0 1-1 0L10 14l-7-3.5a.55.55 0 0 1 0-1L21 3"></path>
    {:else if name === 'brain'}
        <path
            d="M15.5 13a3.5 3.5 0 0 0-3.5 3.5v1a3.5 3.5 0 0 0 7 0v-1.8M8.5 13a3.5 3.5 0 0 1 3.5 3.5v1a3.5 3.5 0 0 1-7 0v-1.8M17.5 16a3.5 3.5 0 0 0 0-7H17m2 .3V6.5a3.5 3.5 0 0 0-7 0M6.5 16a3.5 3.5 0 0 1 0-7H7M5 9.3V6.5a3.5 3.5 0 0 1 7 0v10"></path>
    {:else if name === 'sports-analyst'}
        <circle cx="12" cy="6.5" r="3"></circle>
        <path d="M5 21v-2a6 6 0 0 1 6-6h2a6 6 0 0 1 6 6v2M8.5 13.6 12 18l3.5-4.4M9.8 13.1 12 15.7l2.2-2.6M12 15.7V21"></path>
        <path d="m11 18 1-1 1 1-1 2-1-2"></path>
    {:else if name === 'history'}
        <path d="M12 8v4l2 2M3.05 11a9 9 0 1 1 .5 4m-.5 5v-5h5"></path>
    {/if}
</svg>
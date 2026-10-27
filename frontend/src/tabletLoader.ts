/** Lazy imports keep the loading preview paintable before tablet code evaluates. */
export async function loadTablet(sport: string) {
  if (sport === 'cfb') return {kind: 'cfb' as const, component: (await import('./CFBGameTablet.svelte')).default};
  if (sport === 'nba') return {kind: 'nba' as const, component: (await import('./BasketballPlayTablet.svelte')).default};
  if (sport === 'soccer') return {kind: 'soccer' as const, component: (await import('./SoccerMatchTablet.svelte')).default};
  return {kind: 'nfl' as const, component: (await import('./NFLGameTablet.svelte')).default};
}

export function paintTabletPlaceholder() {
  return new Promise<void>(resolve => {
    if (typeof requestAnimationFrame === 'undefined') {setTimeout(resolve, 0); return;}
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  });
}

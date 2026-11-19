import {tick} from 'svelte';

/** Keeps a just-opened panel on screen and moves focus to it; its trigger can be far above it. */
export async function revealPanel(panel: () => HTMLElement | null, block: ScrollLogicalPosition) {
  await tick();
  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  panel()?.scrollIntoView?.({block, behavior: reduceMotion ? 'auto' : 'smooth'});
  panel()?.focus({preventScroll: true});
}

<script lang="ts">
  import {onMount} from 'svelte';

  export let title: string;
  export let message: string;
  export let ondismiss: () => void;

  let timer: ReturnType<typeof setTimeout> | undefined;
  let remaining = 8000;
  let started = 0;
  let hovering = false;
  let focused = false;

  function resume() {
    if (hovering || focused || timer !== undefined) return;
    started = Date.now();
    timer = setTimeout(ondismiss, remaining);
  }

  function pause() {
    if (timer === undefined) return;
    clearTimeout(timer);
    timer = undefined;
    remaining = Math.max(0, remaining - (Date.now() - started));
  }

  onMount(() => {
    resume();
    return () => clearTimeout(timer);
  });
</script>

<section class="completion-toast" aria-label={title}
  on:pointerenter={() => { hovering = true; pause(); }}
  on:pointerleave={() => { hovering = false; resume(); }}
  on:focusin={() => { focused = true; pause(); }}
  on:focusout={(event) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      focused = false;
      resume();
    }
  }}>
  <span class="completion-icon" aria-hidden="true">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>
    </svg>
  </span>
  <div class="completion-copy"><strong>{title}</strong><p>{message}</p></div>
  <button type="button" class="completion-dismiss" aria-label={'Dismiss ' + title + ' notification'} on:click={ondismiss}>×</button>
</section>

<style>
  .completion-toast {
    display: flex;
    align-items: flex-start;
    gap: .8rem;
    padding: 1rem;
    border: 1px solid var(--color-border-strong);
    border-left: 3px solid var(--color-accent-primary);
    border-radius: .75rem;
    background: var(--color-surface-panel);
    color: var(--color-text-primary);
    box-shadow: 0 12px 36px rgb(0 0 0 / 32%);
    pointer-events: auto;
    animation: toast-arrive .2s ease-out both;
  }
  .completion-icon {
    display: grid;
    place-items: center;
    width: 2rem;
    height: 2rem;
    flex: none;
    color: var(--color-accent-primary);
    border-radius: 50%;
    background: color-mix(in srgb, var(--color-accent-primary) 12%, transparent);
  }
  .completion-icon svg { width: 1.4rem; height: 1.4rem; }
  .completion-copy { min-width: 0; flex: 1; }
  strong { display: block; font-size: .95rem; line-height: 1.4; }
  p { margin: .25rem 0 0; color: var(--color-text-secondary); font-size: .82rem; line-height: 1.5; overflow-wrap: anywhere; }
  .completion-dismiss {
    display: grid;
    place-items: center;
    width: 1.7rem;
    height: 1.7rem;
    padding: 0;
    flex: none;
    border: 0;
    border-radius: .35rem;
    background: transparent;
    color: var(--color-text-secondary);
    font-size: 1.35rem;
    cursor: pointer;
  }
  .completion-dismiss:hover { color: var(--color-text-primary); background: var(--color-surface-control); }
  .completion-dismiss:focus-visible { outline: 2px solid var(--color-accent-primary); outline-offset: 2px; }
  @keyframes toast-arrive { from { opacity: 0; transform: translateY(.6rem); } to { opacity: 1; transform: translateY(0); } }
  @media (prefers-reduced-motion: reduce) { .completion-toast { animation: none; } }
</style>

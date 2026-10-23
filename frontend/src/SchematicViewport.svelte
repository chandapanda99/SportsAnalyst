<script lang="ts">
  import {onDestroy, tick} from 'svelte';
  export let label = 'schematic';
  export let focusX = 50;
  export let focusY = 50;
  export let selection = '';
  export let onclear: () => void = () => {};
  export let markers: {id: string; label: string}[] = [];
  export let selectedMarker = '';
  export let onselect: (id: string) => void = () => {};
  let expanded = false;
  let zoom = 1;
  let viewport: HTMLDivElement;
  let root: HTMLDivElement;
  let expandButton: HTMLButtonElement;
  let closeButton: HTMLButtonElement;
  let previousOverflow = '';
  const pointers = new Map<number, {x: number; y: number}>();
  let distance = 0;
  let dragged = false;

  async function expand() {
    previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    expanded = true;
    await tick();
    closeButton.focus();
  }
  async function close() {
    expanded = false;
    zoom = 1;
    pointers.clear();
    document.body.style.overflow = previousOverflow;
    await tick();
    expandButton?.focus();
  }
  async function scale(value: number, x = .5, y = .5) {
    const old = zoom;
    const anchorX = viewport.scrollLeft + viewport.clientWidth * x;
    const anchorY = viewport.scrollTop + viewport.clientHeight * y;
    zoom = Math.min(4, Math.max(1, value));
    await tick();
    viewport.scrollLeft = anchorX * zoom / old - viewport.clientWidth * x;
    viewport.scrollTop = anchorY * zoom / old - viewport.clientHeight * y;
  }
  async function focusPlay() {
    await scale(2);
    viewport.scrollLeft = viewport.scrollWidth * focusX / 100 - viewport.clientWidth / 2;
    viewport.scrollTop = viewport.scrollHeight * focusY / 100 - viewport.clientHeight / 2;
  }
  function keydown(event: KeyboardEvent) {
    if (!expanded) return;
    if (event.key === 'Escape') {event.preventDefault(); void close();}
    if (event.key === 'Tab') {
      const controls = Array.from(root.querySelectorAll<HTMLElement>('button:not(:disabled), select:not(:disabled), input:not(:disabled), [tabindex="0"]'));
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus();}
      else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
    }
  }
  function pointerDown(event: PointerEvent) {
    if (!expanded || event.pointerType !== 'touch') return;
    if (!pointers.size) dragged = false;
    pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
    distance = 0;
  }
  function pointerMove(event: PointerEvent) {
    const previous = pointers.get(event.pointerId);
    if (!expanded || !previous) return;
    if (Math.hypot(previous.x - event.clientX, previous.y - event.clientY) > 3 || pointers.size > 1) dragged = true;
    pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
    if (pointers.size === 2) {
      const [a, b] = Array.from(pointers.values());
      const next = Math.hypot(a.x - b.x, a.y - b.y);
      if (distance > 0) {
        const bounds = viewport.getBoundingClientRect();
        void scale(zoom * next / distance, ((a.x + b.x) / 2 - bounds.left) / bounds.width,
          ((a.y + b.y) / 2 - bounds.top) / bounds.height);
      }
      distance = next;
    } else {
      viewport.scrollLeft += previous.x - event.clientX;
      viewport.scrollTop += previous.y - event.clientY;
    }
  }
  function pointerUp(event: PointerEvent) {pointers.delete(event.pointerId); distance = 0;}
  onDestroy(() => {if (expanded) document.body.style.overflow = previousOverflow;});
</script>

<svelte:window on:keydown={keydown} on:pointermove={pointerMove} on:pointerup={pointerUp} on:pointercancel={pointerUp}/>
<div bind:this={root} class="schematic-viewer" class:expanded role={expanded ? 'dialog' : 'region'} aria-modal={expanded ? 'true' : undefined} aria-label={label}>
  <div class="viewer-controls">
    {#if expanded}
      <button bind:this={closeButton} type="button" on:click={close}>Close expanded view</button>
      <button type="button" aria-label="Zoom out" disabled={zoom <= 1} on:click={() => scale(zoom - .5)}>−</button>
      <output aria-label="Zoom level">{Math.round(zoom * 100)}%</output>
      <button type="button" aria-label="Zoom in" disabled={zoom >= 4} on:click={() => scale(zoom + .5)}>+</button>
      <button type="button" on:click={focusPlay}>Focus play</button>
      <button type="button" on:click={() => scale(1)}>Full view</button>
    {:else}
      <button bind:this={expandButton} type="button" on:click={expand}>Expand {label}</button>
    {/if}
  </div>
  {#if markers.length}
    <label class="marker-picker">Player or event details
      <select value={selectedMarker} on:change={(event) => onselect(event.currentTarget.value)}>
        <option value="">Choose a marker</option>{#each markers as marker}<option value={marker.id}>{marker.label}</option>{/each}
      </select>
    </label>
  {/if}
  {#if expanded}<p class="viewer-help">Swipe to pan; pinch or use the buttons to zoom. Tap a marker for details.</p>{/if}
  <!-- Keyboard focus permits arrow-key scrolling; click capture only suppresses clicks after a drag. -->
  <!-- svelte-ignore a11y_no_noninteractive_tabindex a11y_click_events_have_key_events a11y_no_noninteractive_element_interactions -->
  <div bind:this={viewport} class="schematic-scroll" role="region" aria-label="Scrollable schematic" tabindex="0" on:pointerdown={pointerDown} on:click|capture={(event) => {if (expanded && dragged) {event.preventDefault(); event.stopPropagation(); dragged = false;}}}>
    <div class="schematic-canvas" style={`width:${zoom * 100}%`}><slot/></div>
  </div>
  {#if selection}
    <div class="marker-details" role="status"><p>{selection}</p><button type="button" aria-label="Clear marker selection" on:click={onclear}>Clear selection</button></div>
  {/if}
</div>

<style>
  .schematic-viewer {min-width:0; max-width:100%;}
  .viewer-controls {display:flex; flex-wrap:wrap; align-items:center; gap:.5rem; padding:.5rem 0;}
  .marker-picker {display:flex; flex-wrap:wrap; align-items:center; gap:.5rem; margin:.5rem 0; font-size:.9rem;}
  select {min-width:0; max-width:100%; flex:1 1 14rem; min-height:44px; font:inherit; font-size:16px; color:var(--color-text-primary,#edf7ff); background:var(--color-surface-control,#102336);}
  button {min-width:44px; min-height:44px; padding:.5rem .75rem; border:1px solid var(--line,#315063); border-radius:.4rem; background:var(--color-surface-control,#102336); color:var(--color-text-primary,#edf7ff); cursor:pointer; font:inherit;}
  button:disabled {opacity:.45; cursor:default;}
  .schematic-scroll {overflow:auto; max-width:100%;}
  .schematic-canvas {min-width:100%;}
  .marker-details {display:flex; flex-wrap:wrap; align-items:center; gap:.5rem; padding:.75rem; border:1px solid var(--mint,#7be4cd); background:var(--color-surface-panel,#071724);}
  .marker-details p {flex:1 1 15rem; margin:0; overflow-wrap:anywhere;}
  .expanded {position:fixed; inset:0; z-index:1000; background:var(--color-surface-panel,#071724); padding: max(.75rem, env(safe-area-inset-top)) max(.75rem, env(safe-area-inset-right)) max(.75rem, env(safe-area-inset-bottom)) max(.75rem, env(safe-area-inset-left)); display:flex; flex-direction:column; box-sizing:border-box;}
  .expanded .schematic-scroll {flex:1; min-height:0; touch-action:none; overscroll-behavior:contain;}
  .expanded .schematic-canvas :global(svg) {display:block; width:100%; height:auto; max-height:none;}
  .viewer-help {font-size:.85rem; margin:.25rem 0 .75rem;}
</style>

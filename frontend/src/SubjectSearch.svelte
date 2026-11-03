<script lang="ts">
  import Icon from './Icon.svelte';

  type Option = {value: string; label: string; detail?: string};
  export let id: string;
  export let label: string;
  export let options: Option[] = [];
  export let value = '';
  export let placeholder = 'Search…';
  export let emptyMessage = 'No matches';
  export let onselect: (value: string) => void = () => {};
  export let onsearch: ((text: string) => void) | undefined = undefined;
  export let searching = false;
  let text = '';
  let filter = '';
  let open = false;
  let active = 0;

  $: selected = options.find(option => option.value === value);
  // Show the chosen option's name whenever the list is closed, including after a reset from outside.
  $: if (!open) text = selected?.label ?? (value ? text : filter);
  $: matches = options.filter(option => !filter.trim() || `${option.label} ${option.value} ${option.detail ?? ''}`
      .toLowerCase().includes(filter.trim().toLowerCase())).slice(0, 50);

  function choose(option: Option) {
    filter = '';
    open = false;
    onselect(option.value);
  }

  function keydown(event: KeyboardEvent) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) open = true;
      else if (matches.length) active = (active + (event.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length;
    } else if (event.key === 'Enter' && open && matches[active]) {
      event.preventDefault();
      choose(matches[active]);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      open = false;
    }
  }
</script>

<div class="team-control">
  <label for={id}>{label}</label>
  <div class="team-combobox">
    <input {id} role="combobox" bind:value={text} aria-expanded={open} aria-controls={`${id}-options`} aria-autocomplete="list"
           aria-activedescendant={open && matches[active] ? `${id}-option-${matches[active].value}` : undefined}
           aria-invalid={Boolean(text && !selected)} autocomplete="off" {placeholder}
           on:focus={() => { open = true; active = 0; }} on:blur={() => open = false} on:keydown={keydown}
           on:input={() => { filter = text; active = 0; open = true; if (value) onselect(''); onsearch?.(text); }}/>
    <button class="combobox-toggle" type="button" aria-label={`Show ${label.toLowerCase()} options`} tabindex="-1"
            on:mousedown|preventDefault={() => open = !open}>
      <Icon name="chevron-down" size={17}/>
    </button>
    {#if open}
      <div class="team-options" id={`${id}-options`} role="listbox" aria-label={label}>
        {#each matches as option, index}
          <button id={`${id}-option-${option.value}`} type="button" role="option" aria-selected={option.value === value}
                  class:active={index === active} on:mousedown|preventDefault={() => choose(option)} on:mouseenter={() => active = index}>
            <span>{option.label}</span>{#if option.detail}<b>{option.detail}</b>{/if}
          </button>
        {:else}
          <div class="no-team-results">{searching ? 'Searching…' : emptyMessage}</div>
        {/each}
      </div>
    {/if}
  </div>
  {#if text && !selected}<small class="validation">Choose an option from the list.</small>{/if}
</div>

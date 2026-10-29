<script lang="ts">
  export interface SummaryRow {
    metric: string; category: string; availablePeriods: number;
    cells: {period: string; status: string; entries: {value: string; sample?: number; context?: string; evidence_id: string}[]}[];
  }
  let {rows, periods, sampleLabel = 'Sample'}: {rows: SummaryRow[]; periods: string[]; sampleLabel?: string} = $props();
</script>

<div class="comparison-matrix" role="region" aria-label="Selected-season comparison">
  <table>
    <thead><tr><th scope="col">{rows.some(row => row.category) ? 'Category / metric' : 'Metric'}</th>
      {#each periods as period}<th scope="col">{period}</th>{/each}</tr></thead>
    <tbody>{#each rows as row}<tr>
      <th scope="row">{row.category || row.metric}{#if row.category}<small>{row.metric}</small>{/if}</th>
      {#each row.cells as cell}<td>
        {#if cell.entries.length}
          {#each cell.entries as entry}<div title={entry.context}><strong>{entry.value}</strong>
            {#if entry.sample !== undefined}<small>{sampleLabel}: {entry.sample.toLocaleString()}</small>{/if}</div>{/each}
        {:else}<span class="missing" title="No registered measurement for this period. This is not zero or proof that source data is unavailable.">
          <span aria-hidden="true">—</span><small>No measurement</small></span>{/if}
      </td>{/each}
    </tr>{/each}</tbody>
  </table>
</div>

<style>
  .comparison-matrix {overflow-x:auto; margin:.75rem 0; border:1px solid var(--line); border-radius:.4rem;}
  table {width:100%; border-collapse:collapse; font-size:.88rem;}
  th,td {padding:.7rem .85rem; border-bottom:1px solid var(--line); vertical-align:top;}
  thead th {background:var(--color-surface-control); white-space:nowrap;}
  th {text-align:left; color:var(--color-text-primary);}
  td,thead th:not(:first-child) {text-align:right; font-variant-numeric:tabular-nums;}
  td {min-width:7rem;}
  td div + div {margin-top:.5rem;}
  small {display:block; margin-top:.2rem; font-size:.75rem; color:var(--color-text-secondary); font-weight:400;}
  .missing {color:var(--color-text-secondary);}
  tbody tr:last-child :is(th,td) {border-bottom:0;}
</style>

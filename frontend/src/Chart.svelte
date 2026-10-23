<script lang="ts">
    import {applyTeamChartPalette, teamLogoUrl} from './teamPalettes';
    import TeamBadge from './TeamBadge.svelte';
    import SchematicViewport from './SchematicViewport.svelte';
    import {comparisonRows, filterMetric} from './chartRows';
    import {loadChartRenderer} from './chartRenderer';

    interface Props {
        specification: Record<string, unknown>;
        team: string;
        sport?: string;
        season?: number;
    }

    let {specification, team, sport = 'nfl', season}: Props = $props();
    let target: HTMLDivElement;
    let renderError = $state('');
    let metric = $state('');
    let showChart = $state(false);
    let chartWidth = $state(0);
    let rows = $derived(comparisonRows(specification));
    let visibleRows = $derived(rows.filter(row => !metric || row.metric === metric));
    $effect(() => {specification; metric = '';});
    let metricMetadata = $derived(
        (specification.usermeta as {chartKind?: string; metricRowCount?: number} | undefined)?.chartKind === 'metric-rows'
            ? specification.usermeta as {metricRowCount?: number; seriesCount?: number}
            : null
    );
    let metricRowCount = $derived(Number(metricMetadata?.metricRowCount ?? 0));

    $effect(() => {
        const themedSpecification = applyTeamChartPalette(filterMetric(specification, metric), team, sport, season);
        // Vega's concatenated plots do not reliably resolve a hidden container's
        // width. Give each metric plot a measured width, including after expand.
        if (Array.isArray(themedSpecification.vconcat)) {
            themedSpecification.vconcat = themedSpecification.vconcat.map(plot => ({...plot, width: Math.max(120, chartWidth - 64)}));
        }
        let cancelled = false;
        let resizeFrame = 0;
        let view: {finalize: () => void; resize: () => {runAsync: () => Promise<unknown>}} | undefined;
        const resizeObserver = typeof ResizeObserver === 'undefined'
            ? undefined
            : new ResizeObserver(() => {
                cancelAnimationFrame(resizeFrame);
                resizeFrame = requestAnimationFrame(() => {
                    const width = Math.round(target.clientWidth);
                    if (width > 0 && width !== chartWidth) chartWidth = width;
                    else void view?.resize().runAsync();
                });
            });
        resizeObserver?.observe(target);

        async function renderChart() {
            const values = (themedSpecification.data as {values?: unknown[]} | undefined)?.values;
            if (Array.isArray(values) && values.length === 0) {
                renderError = 'No chartable values were produced for this analysis.';
                return;
            }
            renderError = '';
            try {
                const embed = await loadChartRenderer();
                if (cancelled) return;
                const result = await embed(target, themedSpecification, {
                    actions: false,
                    theme: 'dark',
                    renderer: 'svg'
                });

                if (cancelled) {
                    result.view.finalize();
                    return;
                }

                view = result.view;
            } catch (problem) {
                if (!cancelled) renderError = `Unable to render chart: ${problem instanceof Error ? problem.message : String(problem)}`;
            }
        }

        void renderChart();

        return () => {
            cancelled = true;
            cancelAnimationFrame(resizeFrame);
            resizeObserver?.disconnect();
            view?.finalize();
        };
    });
</script>
{#if team}<div class="chart-team"><TeamBadge logo={teamLogoUrl(team, sport, season)} label={team} initials={team.slice(0, 2)}/><span>{team} · Team-colored comparison</span></div>{/if}
{#if rows.length}
    <label class="metric-filter">Show metric
        <select bind:value={metric}><option value="">All metrics</option>{#each rows as row}<option value={row.metric}>{row.metric}</option>{/each}</select>
    </label>
    <div class="mobile-metric-values" aria-label="Exact metric comparison">
        {#each visibleRows as row}
            <section><h4>{row.metric}</h4><dl>{#each row.entries as entry}<div><dt>{entry.series}</dt><dd>{entry.value}</dd></div>{/each}</dl>
                {#if row.change !== null}<p>First to last change: {row.change}</p>{/if}
            </section>
        {/each}
        <small>Changes are numeric differences, not a judgment of improvement. pp = percentage points.</small>
    </div>
{/if}
{#if rows.length}<button class="chart-toggle" type="button" aria-expanded={showChart} onclick={() => showChart = !showChart}>{showChart ? 'Hide comparison chart' : 'Show comparison chart'}</button>{/if}
<div class="chart-visual" class:compact={rows.length > 0 && !showChart}>
<SchematicViewport label="chart">
<div class="chart" class:has-error={renderError} class:metric-rows={metricRowCount > 0} bind:this={target}>
    {#if renderError}<p class="chart-error">{renderError}</p>{/if}
</div>
</SchematicViewport>
</div>

<style>
    .chart-team {display:flex; align-items:center; gap:.6rem; padding:.5rem 0; color:var(--color-text-secondary); font-size:.85rem;}
    .metric-filter {display:flex; flex-wrap:wrap; gap:.5rem; align-items:center; margin:.5rem 0;}
    select {max-width:100%; min-height:44px; background:var(--color-surface-control); color:var(--color-text-primary); padding:.5rem;}
    .mobile-metric-values {display:none;}
    .chart-toggle {display:none; min-height:44px; padding:.5rem; color:var(--color-text-primary); background:var(--color-surface-control); border:1px solid var(--line);}
    .chart-visual {min-width:0;}
    @media (max-width:650px) {
        .chart-toggle {display:block;}
        .compact {display:none;}
        .mobile-metric-values {display:grid; gap:.75rem;}
        section {padding:.75rem; border:1px solid var(--line); border-radius:.4rem;}
        h4 {margin:0 0 .5rem;}
        dl {margin:0; display:grid; gap:.5rem;}
        dl div {display:flex; flex-wrap:wrap; justify-content:space-between; gap:.5rem;}
        dt {color:var(--color-text-secondary); overflow-wrap:anywhere;}
        dd {margin:0; font-variant-numeric:tabular-nums; font-weight:600;}
        p,small {font-size:.85rem; overflow-wrap:anywhere;}
        .chart {justify-content:flex-start; overflow:auto;}
    }
</style>

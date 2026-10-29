<script lang="ts">
    import {applyTeamChartPalette, chartSeriesStyles, teamLogoUrl} from './teamPalettes';
    import {branding} from './sportsBranding';
    import TeamBadge from './TeamBadge.svelte';
    import SchematicViewport from './SchematicViewport.svelte';
    import {chartComparisonKind, chartGuidance, comparisonRows, filterMetric} from './chartRows';
    import {loadChartRenderer} from './chartRenderer';
    import ComparisonMatrix, {type SummaryRow} from './ComparisonMatrix.svelte';

    interface Props {
        specification: Record<string, unknown>;
        team: string;
        sport?: string;
        season?: number;
    }

    let {specification, team, sport = 'nfl', season}: Props = $props();
    let target = $state<HTMLDivElement>();
    let renderError = $state('');
    let metric = $state('');
    let showChart = $state(false);
    let matrix = $derived((specification.usermeta as {comparisonSummary?: SummaryRow[]})?.comparisonSummary ?? []);
    let matrixMode = $derived((specification.usermeta as {displayMode?: string})?.displayMode === 'matrix');
    let periods = $derived((specification.usermeta as {expectedPeriods?: string[]})?.expectedPeriods ?? []);
    let missingPeriods = $derived((specification.usermeta as {missingPeriods?: string[]})?.missingPeriods ?? []);
    let hasPlot = $derived(((filterMetric(specification, metric).vconcat as unknown[] | undefined)?.length ?? 0) > 0);
    let chartWidth = $state(0);
    let rows = $derived(comparisonRows(specification));
    let visibleRows = $derived(rows.filter(row => !metric || row.metric === metric));
    let series = $derived(chartSeriesStyles(specification, team, sport, season));
    let grouped = $derived(chartComparisonKind(specification) === 'grouped-observations');
    let anonymousCategories = $derived(grouped && !(specification.usermeta as {colorField?: string})?.colorField);
    let teamName = $derived(branding(team, sport, season).name ?? (/^\d+$/.test(team) ? 'Team Colors' : team));
    const symbolPaths: Record<string, string> = {
        square: 'M3 3H13V13H3Z', diamond: 'M8 1L15 8L8 15L1 8Z',
        'triangle-up': 'M8 1L15 14H1Z', 'triangle-down': 'M1 2H15L8 15Z',
        cross: 'M5 1H11V5H15V11H11V15H5V11H1V5H5Z'
    };
    $effect(() => {specification; metric = (specification.usermeta as {defaultMetric?: string})?.defaultMetric ?? ''; showChart = false;});
    let metricMetadata = $derived(
        (specification.usermeta as {chartKind?: string; metricRowCount?: number} | undefined)?.chartKind === 'metric-rows'
            ? specification.usermeta as {metricRowCount?: number; seriesCount?: number}
            : null
    );
    let metricRowCount = $derived(Number(metricMetadata?.metricRowCount ?? 0));

    $effect(() => {
        if (matrixMode && (!showChart || !hasPlot)) return;
        const host = target;
        if (!host) return;
        const themedSpecification = applyTeamChartPalette(filterMetric(specification, metric), team, sport, season);
        // Vega's concatenated plots do not reliably resolve a hidden container's
        // width. Give each metric plot a measured width, including after expand.
        if (Array.isArray(themedSpecification.vconcat)) {
            themedSpecification.vconcat = themedSpecification.vconcat.map(plot => {
                const categoryRows = (specification.usermeta as {categoryLayout?: string})?.categoryLayout === 'rows';
                const width = Math.max(120, (chartWidth || 640) - (categoryRows ? 240 : 72));
                const values = (plot.data as {values?: unknown[]} | undefined)?.values ?? [];
                return {...plot, width, layer: plot.layer?.map((layer: Record<string, unknown>) => {
                    const mark = layer.mark as {type?: string} | undefined;
                    // Keep labels from colliding on narrow or densely populated plots.
                    // Every point retains its hover target and exact-values entry.
                    return !categoryRows && mark?.type === 'text' && values.length > Math.max(3, Math.floor(width / 76))
                        ? {...layer, mark: {...mark, opacity: 0}} : layer;
                })};
            });
        }
        let cancelled = false;
        let resizeFrame = 0;
        let view: {finalize: () => void; resize: () => {runAsync: () => Promise<unknown>}} | undefined;
        const resizeObserver = typeof ResizeObserver === 'undefined'
            ? undefined
            : new ResizeObserver(() => {
                cancelAnimationFrame(resizeFrame);
                resizeFrame = requestAnimationFrame(() => {
                    const width = Math.round(host.clientWidth);
                    if (width > 0 && width !== chartWidth) chartWidth = width;
                    else void view?.resize().runAsync();
                });
            });
        resizeObserver?.observe(host);

        async function renderChart() {
            const values = (themedSpecification.data as {values?: unknown[]} | undefined)?.values;
            if (Array.isArray(values) && values.length === 0) {
                renderError = 'No chartable values were produced for this analysis.';
                return;
            }
            renderError = '';
            try {
                const embed = await loadChartRenderer();
                if (cancelled || !host) return;
                const result = await embed(host, themedSpecification, {
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
{#if team}<div class="chart-team"><TeamBadge logo={teamLogoUrl(team, sport, season)} label={teamName} initials={teamName.slice(0, 2)}/><span>{teamName}</span></div>{/if}
{#if rows.length}
    <p class="chart-guidance">{chartGuidance(specification)}</p>
    {#if !matrixMode || showChart}<div class="series-key" aria-label={anonymousCategories ? 'Recorded categories legend'
        : (specification.usermeta as {colorTitle?: string})?.colorTitle === 'Seasons'
            || chartComparisonKind(specification) === 'season-trend' ? 'Seasons legend' : 'Periods legend'}>
        {#each anonymousCategories ? series.slice(0, 1) : series as item}
            <span>
                <svg viewBox="0 0 16 16" aria-hidden="true" style:color={item.color}>
                    {#if item.shape === 'circle'}<circle cx="8" cy="8" r="5" fill="currentColor"/>
                    {:else}<path d={symbolPaths[item.shape]} fill="currentColor"/>{/if}
                </svg>
                {anonymousCategories ? 'Recorded categories' : item.label}
            </span>
        {/each}
    </div>{/if}
    {#if rows.length > 1}<label class="metric-filter">Show metric
        <select bind:value={metric}><option value="">All metrics</option>{#each rows as row}<option value={row.metric}>{row.metric}</option>{/each}</select>
    </label>{/if}
    {#if missingPeriods.length}<p class="coverage-note">This view has no calculated values for {missingPeriods.join(', ')}. Check the overall season summary and coverage details.</p>{/if}
    {#if matrixMode}<ComparisonMatrix rows={matrix.filter(row => !metric || row.metric === metric)} {periods}
        sampleLabel={(specification.usermeta as {sampleLabel?: string})?.sampleLabel ?? 'Sample'}/>{/if}
    {#if !matrixMode}<details class="metric-values">
        <summary>View Exact Values</summary>
        <div class="value-rows" aria-label="Exact metric comparison">
        {#each visibleRows as row}
            <section><h4>{row.metric}</h4><dl>{#each row.entries as entry}<div><dt>{entry.series}
                {#if entry.context}<small>{entry.context}</small>{/if}
                {#if entry.sample !== undefined}<small>Sample: {entry.sample.toLocaleString()}</small>{/if}
            </dt><dd>{entry.value}</dd></div>{/each}</dl>
                {#if row.change !== null}<p>First to last change: {row.change}</p>{/if}
            </section>
        {/each}
        {#if !grouped && chartComparisonKind(specification) !== 'monthly-trend'}<small>Changes are numeric differences, not a judgment of improvement. pp = percentage points.</small>{/if}
        </div>
    </details>{/if}
{/if}
{#if matrixMode}
  {#if hasPlot}<button class="matrix-plot-toggle" type="button" aria-expanded={showChart} onclick={() => showChart = !showChart}>{showChart ? 'Hide plot' : 'Explore comparable measurements'}</button>
  {:else}<p class="coverage-note">A comparison plot requires at least two comparable periods. Available values are shown above.</p>{/if}
{:else if rows.length}<button class="chart-toggle" type="button" aria-expanded={showChart} onclick={() => showChart = !showChart}>{showChart ? 'Hide comparison chart' : 'Show comparison chart'}</button>{/if}
{#if !matrixMode || (showChart && hasPlot)}
<div class="chart-visual" class:compact={rows.length > 0 && !showChart}>
<SchematicViewport label="chart">
<div class="chart" class:has-error={renderError} class:metric-rows={metricRowCount > 0} bind:this={target}>
    {#if renderError}<p class="chart-error">{renderError}</p>{/if}
</div>
</SchematicViewport>
</div>
{/if}

<style>
    .chart-team {display:flex; align-items:center; gap:.6rem; padding:.5rem 0; color:var(--color-text-secondary); font-size:.85rem;}
    .chart-guidance {font-size:.85rem; line-height:1.6; color:var(--color-text-secondary); margin:.25rem 0 .75rem;}
    .series-key {display:flex; flex-wrap:wrap; gap:.6rem 1.25rem; border:1px solid var(--line); border-radius:.4rem; padding:.65rem .8rem;}
    .series-key span {display:flex; align-items:center; gap:.45rem; font-size:.85rem; font-weight:600;}
    .series-key svg {width:1rem; height:1rem; flex:none;}
    .metric-filter {display:flex; flex-wrap:wrap; gap:.5rem; align-items:center; margin:.5rem 0;}
    select {max-width:100%; width:min(100%, 24rem); min-width:0; min-height:44px; background:var(--color-surface-control); color:var(--color-text-primary); padding:.5rem; border:1px solid var(--line); border-radius:.35rem;}
    .metric-values {margin:.75rem 0;}
    summary {width:fit-content; cursor:pointer; padding:.6rem 0; font-weight:600; font-size:.85rem;}
    .value-rows {display:grid; gap:.75rem; margin:.5rem 0;}
    section {padding:.85rem; border:1px solid var(--line); border-radius:.4rem; min-width:0;}
    h4 {margin:0 0 .5rem;}
    dl {margin:0; display:grid; gap:.5rem;}
    dl div {display:flex; justify-content:space-between; gap:1rem; padding:.35rem 0; border-bottom:1px solid var(--line);}
    dt {color:var(--color-text-secondary); overflow-wrap:anywhere;}
    dt small {display:block; margin-top:.25rem;}
    dd {margin:0; flex:none; font-variant-numeric:tabular-nums; font-weight:600;}
    section p,small {font-size:.85rem; line-height:1.5; overflow-wrap:anywhere;}
    .chart-toggle {display:none; min-height:44px; padding:.5rem; color:var(--color-text-primary); background:var(--color-surface-control); border:1px solid var(--line);}
    .chart-visual {min-width:0;}
    .coverage-note {font-size:.85rem; color:var(--color-text-secondary); line-height:1.5;}
    .matrix-plot-toggle {min-height:44px; padding:.55rem .8rem; background:var(--color-surface-control);
      color:var(--color-text-primary); border:1px solid var(--line); border-radius:.35rem; margin-bottom:.75rem;}
    @media (max-width:650px) {
        .chart-toggle {display:block;}
        .compact {display:none;}
        dl div {gap:.5rem;}
        .chart {justify-content:flex-start; overflow:auto;}
    }
</style>

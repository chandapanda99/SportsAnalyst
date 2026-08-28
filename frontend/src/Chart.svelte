<script lang="ts">
    import {applyTeamChartPalette} from './teamPalettes';

    interface Props {
        specification: Record<string, unknown>;
        team: string;
        sport?: string;
    }

    let {specification, team, sport = 'nfl'}: Props = $props();
    let target: HTMLDivElement;
    let renderError = $state('');

    $effect(() => {
        const themedSpecification = applyTeamChartPalette(specification, team, sport);
        let cancelled = false;
        let resizeFrame = 0;
        let view: {finalize: () => void; resize: () => {runAsync: () => Promise<unknown>}} | undefined;
        const resizeObserver = typeof ResizeObserver === 'undefined'
            ? undefined
            : new ResizeObserver(() => {
                cancelAnimationFrame(resizeFrame);
                resizeFrame = requestAnimationFrame(() => void view?.resize().runAsync());
            });

        async function renderChart() {
            const values = (themedSpecification.data as {values?: unknown[]} | undefined)?.values;
            if (Array.isArray(values) && values.length === 0) {
                renderError = 'No chartable values were produced for this analysis.';
                return;
            }
            renderError = '';
            try {
                const {default: embed} = await import('vega-embed');
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
                resizeObserver?.observe(target);
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
<div class="chart" class:has-error={renderError} bind:this={target}>
    {#if renderError}<p class="chart-error">{renderError}</p>{/if}
</div>

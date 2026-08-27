<script lang="ts">
    import {applyTeamChartPalette} from './teamPalettes';

    interface Props {
        specification: Record<string, unknown>;
        team: string;
        sport?: string;
    }

    let {specification, team, sport = 'nfl'}: Props = $props();
    let target: HTMLDivElement;

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
<div class="chart" bind:this={target}></div>

<script lang="ts">
    import {applyTeamChartPalette} from './teamPalettes';

    interface Props {
        specification: Record<string, unknown>;
        team: string;
    }

    let {specification, team}: Props = $props();
    let target: HTMLDivElement;

    $effect(() => {
        const themedSpecification = applyTeamChartPalette(specification, team);
        let cancelled = false;
        let view: {finalize: () => void; resize: () => {runAsync: () => Promise<unknown>}} | undefined;
        const resizeObserver = typeof ResizeObserver === 'undefined'
            ? undefined
            : new ResizeObserver(() => {
                void view?.resize().runAsync();
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
            resizeObserver?.disconnect();
            view?.finalize();
        };
    });
</script>
<div class="chart" bind:this={target}></div>

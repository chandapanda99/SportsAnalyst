<script lang="ts">
    import {onMount} from 'svelte';
    import type {DotLottie as DotLottiePlayer} from '@lottiefiles/dotlottie-web';
    import dotLottieWasmUrl from '@lottiefiles/dotlottie-web/dotlottie-player.wasm?url';

    let canvas: HTMLCanvasElement;
    let failed = false;

    onMount(() => {
        let player: DotLottiePlayer | null = null;
        let disposed = false;
        const reducedMotion = typeof window.matchMedia === 'function'
            ? window.matchMedia('(prefers-reduced-motion: reduce)')
            : null;

        const showFallback = () => {
            failed = true;
            player?.destroy();
            player = null;
        };

        const syncMotionPreference = () => {
            if (!player) return;
            if (reducedMotion?.matches) {
                player.pause();
                player.setFrame(0);
            } else {
                player.play();
            }
        };

        void import('@lottiefiles/dotlottie-web')
            .then(({DotLottie}) => {
                if (disposed) return;
                DotLottie.setWasmUrl(dotLottieWasmUrl);
                player = new DotLottie({
                    canvas,
                    src: '/basketball_player.lottie',
                    autoplay: !reducedMotion?.matches,
                    loop: true,
                    layout: {fit: 'contain', align: [0.5, 0.5]},
                    renderConfig: {autoResize: true, freezeOnOffscreen: true}
                });
                player.addEventListener('loadError', showFallback);
                player.addEventListener('renderError', showFallback);
                player.addEventListener('load', syncMotionPreference);
            })
            .catch(showFallback);

        reducedMotion?.addEventListener('change', syncMotionPreference);
        return () => {
            disposed = true;
            reducedMotion?.removeEventListener('change', syncMotionPreference);
            player?.destroy();
        };
    });
</script>

<div class="basketball-animation">
    {#if failed}
        <img src="/open-sports-analyst-loader.svg" alt=""/>
    {:else}
        <canvas bind:this={canvas}></canvas>
    {/if}
</div>

<style>
    .basketball-animation {
        position: absolute;
        inset: 34px 12px 34px;
        display: grid;
        place-items: center;
        min-width: 0;
        min-height: 0;
    }

    canvas,
    img {
        display: block;
        width: 100%;
        height: 100%;
        object-fit: contain;
    }
</style>

<script lang="ts">
  import {onMount} from 'svelte';

  const contacts = [
    {side: 0, y: 155}, {side: 1, y: 90},
    {side: 0, y: 90}, {side: 1, y: 155}
  ];
  const clamp = (value: number) => Math.max(0, Math.min(1, value));
  const smooth = (value: number) => { const t = clamp(value); return t * t * (3 - 2 * t); };
  const mix = (from: number, to: number, t: number) => from + (to - from) * t;
  let seconds = 0;

  function frameAt(time: number) {
    // Each exchange has a windup, ground pass, first touch, and a short reset.
    const phase = Math.floor(time / 3) % 4;
    const beat = time % 3;
    const sender = contacts[phase];
    const receiver = contacts[(phase + 1) % 4];
    const previous = contacts[(phase + 3) % 4];
    const travel = clamp((beat - .55) / 1.55);
    const run = smooth((beat - .65) / 1.3);
    const running = beat > .65 && beat < 1.95;
    const stride = Math.sin((beat - .65) * Math.PI * 6);
    const players = [0, 1].map(side => {
      const sending = side === sender.side;
      const moving = !sending && running && previous.y !== receiver.y;
      const direction = side === 0 ? 1 : -1;
      const footY = sending ? sender.y : mix(previous.y, receiver.y, run);
      const gait = moving ? stride : 0;
      const bob = moving ? -Math.abs(Math.cos((beat - .65) * Math.PI * 6)) * 1.8 : 0;
      let reach = 0;
      if (sending) {
        if (beat < .3) reach = -smooth(beat / .3) * 9;
        else if (beat < .55) reach = mix(-9, 5, smooth((beat - .3) / .25));
        else if (beat < .72) reach = mix(5, 10, smooth((beat - .55) / .17));
        else reach = mix(10, 0, smooth((beat - .72) / .38));
      } else if (beat > 1.8) {
        // Extend the instep to meet the ball, then soften the knee on contact.
        reach = beat < 2.1 ? smooth((beat - 1.8) / .3) * 5
          : mix(5, 0, smooth((beat - 2.1) / .3));
      }
      const legs = [-1, 1].map(leg => {
        const active = leg === direction;
        const swing = gait * leg;
        const footX = leg * (active ? 17 + reach : 12) + swing * 5;
        const footY = 27 - Math.max(0, swing) * 7;
        return {leg, kneeX: leg * 10 + swing * 3, kneeY: 19 - Math.max(0, swing) * 3, footX, footY};
      });
      return {side, x: side === 0 ? 96 : 344, y: footY - 27, bob, gait, legs,
        touch: !sending ? Math.max(0, 1 - Math.abs(beat - 2.1) / .3) : 0};
    });
    return {
      players,
      ballX: mix(sender.side === 0 ? 126 : 314, receiver.side === 0 ? 126 : 314, travel),
      ballY: mix(sender.y, receiver.y, travel),
      rotation: (phase % 2 === 0 ? 1 : -1) * travel * 540,
      startX: sender.side === 0 ? 126 : 314, startY: sender.y,
      endX: receiver.side === 0 ? 126 : 314, endY: receiver.y
    };
  }

  $: frame = frameAt(seconds);

  onMount(() => {
    const preference = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    let request = 0;
    let started = 0;
    const animate = (now: number) => {
      if (!started) started = now;
      seconds = ((now - started) / 1000) % 12;
      request = requestAnimationFrame(animate);
    };
    const updateMotion = () => {
      cancelAnimationFrame(request);
      started = 0;
      seconds = 0;
      if (!preference?.matches) request = requestAnimationFrame(animate);
    };
    updateMotion();
    preference?.addEventListener('change', updateMotion);
    return () => {
      cancelAnimationFrame(request);
      preference?.removeEventListener('change', updateMotion);
    };
  });
</script>

<div class="soccer-animation">
  <svg class="soccer-loading-scene" viewBox="0 0 440 210" fill="none" aria-hidden="true" focusable="false">
    <g class="pitch" stroke="currentColor" stroke-width="1.5">
      <rect x="26" y="18" width="388" height="174" rx="3"/>
      <path d="M220 18v174M26 55h51v100H26M414 55h-51v100h51M26 78h21v54H26M414 78h-21v54h21"/>
      <circle cx="220" cy="105" r="29"/>
      <circle cx="220" cy="105" r="2" fill="currentColor" stroke="none"/>
      <path d="M77 81a30 30 0 0 1 0 48M363 81a30 30 0 0 0 0 48"/>
    </g>
    <path class="pass-line" d={'M' + frame.startX + ' ' + frame.startY + 'L' + frame.endX + ' ' + frame.endY}
      stroke="currentColor" stroke-width="1.5" stroke-dasharray="3 8" stroke-linecap="round"/>
    {#each frame.players as player (player.side)}
      <g transform={'translate(' + player.x + ' ' + player.y + ')'}>
        <ellipse cy="29" rx="23" ry="4" fill="#000" opacity=".18"/>
        <circle cy="15" r="31" stroke="currentColor" stroke-width="1.5" opacity={player.touch * .5}/>
        {#each player.legs as leg (leg.leg)}
          <path d={'M' + (leg.leg * 7) + ' 11L' + leg.kneeX + ' ' + leg.kneeY + 'L' + leg.footX + ' ' + leg.footY}
            stroke="#dbe5d9" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
          <path d={'M' + (leg.footX - 3) + ' ' + leg.footY + 'L' + (leg.footX + 3) + ' ' + leg.footY}
            stroke="#10251b" stroke-width="6" stroke-linecap="round"/>
        {/each}
        <g transform={'translate(0 ' + player.bob + ')'}>
          {#each [-1, 1] as arm}
            <path d={'M' + (arm * 16) + ' -18L' + (arm * 23 - player.gait * arm * 3) + ' -8L' + (arm * 26 - player.gait * arm * 6) + ' ' + (-2 + player.gait * arm * 5)}
              stroke={player.side === 0 ? '#d0b69c' : '#b58c6e'} stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
          {/each}
          <path d="m-10-25-12 7 5 10 6-3-2 21h26L11-11l6 3 5-10-12-7"
            fill={player.side === 0 ? 'currentColor' : '#dbe5d9'} stroke={player.side === 0 ? '#d6e9d1' : 'currentColor'}
            stroke-width="1.5" stroke-linejoin="round"/>
          <path d="M-13 9h26v9H-13" fill="#163e28"/>
          <circle cy="-33" r="9" fill={player.side === 0 ? '#d0b69c' : '#b58c6e'}/>
          <path d="M-9-34a9 9 0 0 1 18 0l-3-4H-5" fill="#223328"/>
          <text x="0" y="2" text-anchor="middle" fill="#173623" font-size="13" font-weight="700">{player.side + 1}</text>
        </g>
      </g>
    {/each}
    <g transform={'translate(' + frame.ballX + ' ' + frame.ballY + ')'}>
      <ellipse cy="9" rx="8" ry="2.5" fill="#000" opacity=".2"/>
      <g transform={'rotate(' + frame.rotation + ')'}>
        <circle r="8" fill="#f1f3e9" stroke="#163226" stroke-width="1"/>
        <path d="m0-4 4 3-1.5 4h-5L-4-1ZM-5-6l1 3-3 2m12-5-1 3 3 2M-6 6l3-3m9 3L3 3M0-8v4"
          fill="#263b30" stroke="#263b30" stroke-width="1" stroke-linejoin="round"/>
      </g>
    </g>
  </svg>
</div>

<style>
  .soccer-animation {
    position: absolute;
    inset: 35px 12px 35px;
    display: grid;
    place-items: center;
    color: var(--accent);
    min-width: 0;
    min-height: 0;
  }
  svg { display: block; width: 100%; height: 100%; }
  .pitch { opacity: .28; }
  .pass-line { opacity: .28; }
</style>

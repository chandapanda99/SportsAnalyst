<script lang="ts">
import {FOOTBALL_FIELD_WIDTH, NFL_HASH_FROM_SIDELINE} from "./playSchematic";
export let venueName=""; export let venueAbbreviation=""; export let venueLogo: string | null=null;
export let primary="#142c3d"; export let secondary="#edf7ff"; export let textColor="#edf7ff";
export let hashFromSideline=NFL_HASH_FROM_SIDELINE; export let label="Football field";
const fieldMidpoint=FOOTBALL_FIELD_WIDTH/2;
const fiveYardLines=Array.from({length:19},(_,i)=>15+i*5);
const numberedYardLines=Array.from({length:9},(_,i)=>20+i*10);
const oneYardTicks=Array.from({length:99},(_,i)=>11+i).filter(y=>y%5!==0);
$: hashRows=[hashFromSideline,FOOTBALL_FIELD_WIDTH-hashFromSideline];
    function yardArrowPath(x: number, y: number) {
        const pointsLeft = x < 60;
        const innerEdge = pointsLeft ? x - 2.35 : x + 2.35;
        const tip = pointsLeft ? innerEdge - 1.05 : innerEdge + 1.05;
        return `M ${tip} ${y} L ${innerEdge} ${y - .78} L ${innerEdge} ${y + .78} Z`;
    }

</script>
<svg class="field" viewBox={`0 0 120 ${FOOTBALL_FIELD_WIDTH}`} style={`--venue-primary:${primary};--venue-secondary:${secondary};--venue-endzone-text:${textColor}`} role="img" aria-label={label}>
<slot name="defs"/>
            <rect width="120" height={FOOTBALL_FIELD_WIDTH} rx="1" class="turf"/>
            <rect x="0" width="10" height={FOOTBALL_FIELD_WIDTH} class="endzone"/>
            <rect x="110" width="10" height={FOOTBALL_FIELD_WIDTH} class="endzone"/>
            <rect x=".35" y=".35" width="119.3" height={FOOTBALL_FIELD_WIDTH - .7} class="field-boundary"/>
            <text class="endzone-name" x="5" y={fieldMidpoint} textLength="42" lengthAdjust="spacingAndGlyphs" transform={`rotate(90 5 ${fieldMidpoint})`} aria-hidden="true">{venueName}</text>
            <text class="endzone-name" x="115" y={fieldMidpoint} textLength="42" lengthAdjust="spacingAndGlyphs" transform={`rotate(-90 115 ${fieldMidpoint})`} aria-hidden="true">{venueName}</text>
            <line x1="10" x2="10" y1=".35" y2={FOOTBALL_FIELD_WIDTH - .35} class="goal-line"/>
            <line x1="110" x2="110" y1=".35" y2={FOOTBALL_FIELD_WIDTH - .35} class="goal-line"/>
            <g class="midfield-brand" aria-label={`${venueAbbreviation} midfield logo`}>
                <circle cx="60" cy={fieldMidpoint} r="7.2"/>
                <text x="60" y={fieldMidpoint + .5}>{venueAbbreviation}</text>
                {#if venueLogo}<image href={venueLogo} x="54" y={fieldMidpoint - 6} width="12" height="12" preserveAspectRatio="xMidYMid meet"/>{/if}
            </g>
            {#each fiveYardLines as x}
                <line x1={x} x2={x} y1=".35" y2={FOOTBALL_FIELD_WIDTH - .35} class:major-yard-line={(x - 10) % 10 === 0} class="yard-line"/>
            {/each}
            {#each oneYardTicks as x}
                <line x1={x} x2={x} y1=".45" y2="1.18" class="sideline-tick"/>
                <line x1={x} x2={x} y1={FOOTBALL_FIELD_WIDTH - 1.18} y2={FOOTBALL_FIELD_WIDTH - .45} class="sideline-tick"/>
                {#each hashRows as hashY}
                    <line x1={x} x2={x} y1={hashY - 1 / 3} y2={hashY + 1 / 3} class="inbound-hash"/>
                {/each}
            {/each}
            {#each numberedYardLines as x, marker}
                {@const yardNumber = marker < 5 ? (marker + 1) * 10 : (9 - marker) * 10}
                <text x={x} y="11.8" class="yard-number top" transform={`rotate(180 ${x} 11.8)`}>{yardNumber}</text>
                <text x={x} y={FOOTBALL_FIELD_WIDTH - 11.8} class="yard-number bottom">{yardNumber}</text>
                {#if yardNumber !== 50}
                    <path d={yardArrowPath(x, 11.8)} class="yard-direction top" data-yard-number={yardNumber}/>
                    <path d={yardArrowPath(x, FOOTBALL_FIELD_WIDTH - 11.8)} class="yard-direction bottom" data-yard-number={yardNumber}/>
                {/if}
            {/each}
<slot/>
</svg>


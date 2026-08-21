export type TeamChartPalette = readonly [primary: string, secondary: string];

// Reference: NFL Colors (Community), Figma node 44:26.
// Values use this application's canonical nflverse team abbreviations.
export const TEAM_CHART_PALETTES: Record<string, TeamChartPalette> = {
    ARI: ['#97233F', '#FFB612'],
    ATL: ['#A71930', '#A5ACAF'],
    BAL: ['#241773', '#9E7C0C'],
    BUF: ['#00338D', '#C60C30'],
    CAR: ['#0085CA', '#BFC0BF'],
    CHI: ['#0B162A', '#E64100'],
    CIN: ['#FB4F14', '#A5ACAF'],
    CLE: ['#311D00', '#FF3C00'],
    DAL: ['#041E42', '#869397'],
    DEN: ['#FB4F14', '#002244'],
    DET: ['#0076B6', '#B0B7BC'],
    GB: ['#203731', '#FFB612'],
    HOU: ['#03202F', '#A71930'],
    IND: ['#002C5F', '#A2AAAD'],
    JAX: ['#00A5B5', '#D7A22A'],
    KC: ['#E31837', '#FFB81C'],
    LV: ['#A5ACAF', '#FFFFFF'],
    LAC: ['#0080C6', '#FFC20E'],
    LA: ['#003594', '#FFD100'],
    MIA: ['#008E97', '#FC4C02'],
    MIN: ['#4F2683', '#FFC62F'],
    NE: ['#002244', '#C60C30'],
    NO: ['#D3BC8D', '#101820'],
    NYG: ['#0B2265', '#A71930'],
    NYJ: ['#125740', '#FFFFFF'],
    PHI: ['#004C54', '#A5ACAF'],
    PIT: ['#FFB612', '#A5ACAF'],
    SF: ['#AA0000', '#B3995D'],
    SEA: ['#002244', '#69BE28'],
    TB: ['#D50A0A', '#FF7900'],
    TEN: ['#0C2340', '#4B92DB'],
    WAS: ['#5A1414', '#FFB612']
};

export const DEFAULT_CHART_PALETTE: TeamChartPalette = ['#6F9FD1', '#78DCCA'];
export const CHART_SURFACE_COLOR = '#091521';
const CHART_CONTRAST_TARGET = 3;
const CHART_OUTLINE_COLOR = '#DBE8EE';
const CHART_LABEL_COLOR = '#A8B7C1';
const CHART_GRID_COLOR = '#31506A';

export function teamChartPalette(team: string): TeamChartPalette {
    return TEAM_CHART_PALETTES[team.toUpperCase()] ?? DEFAULT_CHART_PALETTE;
}

function rgb(hex: string): [number, number, number] {
    const value = Number.parseInt(hex.slice(1), 16);
    return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

function luminance(hex: string): number {
    const channels = rgb(hex).map((channel) => {
        const normalized = channel / 255;
        return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

export function colorContrastRatio(first: string, second: string): number {
    const [lighter, darker] = [luminance(first), luminance(second)].sort((left, right) => right - left);
    return (lighter + 0.05) / (darker + 0.05);
}

function mixWithWhite(hex: string, amount: number): string {
    const channels = rgb(hex).map((channel) => Math.round(channel + (255 - channel) * amount));
    return `#${channels.map((channel) => channel.toString(16).padStart(2, '0')).join('').toUpperCase()}`;
}

function mixColors(first: string, second: string, amount: number): string {
    const start = rgb(first);
    const end = rgb(second);
    const channels = start.map((channel, index) => Math.round(channel + (end[index] - channel) * amount));
    return `#${channels.map((channel) => channel.toString(16).padStart(2, '0')).join('').toUpperCase()}`;
}

function accessibleChartColor(color: string): string {
    if (colorContrastRatio(color, CHART_SURFACE_COLOR) >= CHART_CONTRAST_TARGET) return color;
    for (let amount = 0.08; amount <= 0.8; amount += 0.04) {
        const candidate = mixWithWhite(color, amount);
        if (colorContrastRatio(candidate, CHART_SURFACE_COLOR) >= CHART_CONTRAST_TARGET) return candidate;
    }
    return CHART_OUTLINE_COLOR;
}

export function teamChartDisplayPalette(team: string): TeamChartPalette {
    const [primary, secondary] = teamChartPalette(team);
    return [accessibleChartColor(primary), accessibleChartColor(secondary)];
}

export function teamChartSeriesPalette(team: string, count: number): string[] {
    const [primary, secondary] = teamChartDisplayPalette(team);
    if (count <= 2) return [primary, secondary];
    return Array.from({length: count}, (_, index) =>
        accessibleChartColor(mixColors(primary, secondary, index / (count - 1)))
    );
}

function polishAxis(channel: string, definition: Record<string, unknown>): Record<string, unknown> {
    const field = definition.field;
    const titles: Record<string, string | null> = {
        metric: null,
        value: null,
        week: 'Week',
        epa: 'EPA / dropback'
    };
    const axis = (definition.axis as Record<string, unknown> | undefined) ?? {};
    return {
        ...definition,
        axis: {
            ...axis,
            title: 'title' in axis ? axis.title : typeof field === 'string' && field in titles ? titles[field] : undefined,
            labelColor: CHART_LABEL_COLOR,
            labelFontSize: 12,
            labelPadding: 8,
            titleColor: CHART_OUTLINE_COLOR,
            titleFontSize: 13,
            titleFontWeight: 600,
            titlePadding: 12,
            grid: channel === 'y',
            gridColor: CHART_GRID_COLOR,
            gridOpacity: 0.42,
            gridWidth: 0.7,
            domainColor: CHART_GRID_COLOR,
            domainOpacity: 0.8,
            tickColor: CHART_GRID_COLOR,
            tickOpacity: 0.8
        }
    };
}

export function applyTeamChartPalette(specification: Record<string, unknown>, team: string): Record<string, unknown> {
    const themed = structuredClone(specification);
    const encoding = themed.encoding as Record<string, unknown> | undefined;
    for (const channel of ['x', 'y']) {
        const definition = encoding?.[channel];
        if (definition && typeof definition === 'object') {
            encoding![channel] = polishAxis(channel, definition as Record<string, unknown>);
        }
    }
    const color = encoding?.color as Record<string, unknown> | undefined;
    if (color) {
        const colorField = color.field;
        const values = (themed.data as {values?: Array<Record<string, unknown>>} | undefined)?.values ?? [];
        const seriesCount = typeof colorField === 'string'
            ? new Set(values.map((value) => value[colorField])).size
            : 0;
        encoding!.color = {
            ...color,
            scale: {
                ...((color.scale as Record<string, unknown> | undefined) ?? {}),
                range: teamChartSeriesPalette(team, Math.max(2, seriesCount))
            },
            legend: {
                ...((color.legend as Record<string, unknown> | undefined) ?? {}),
                title: null,
                orient: 'top',
                direction: 'horizontal',
                columns: 2,
                labelColor: CHART_LABEL_COLOR,
                labelFontSize: 12,
                labelPadding: 5,
                symbolSize: 86,
                symbolStrokeWidth: 2
            }
        };
    }

    const mark = themed.mark as Record<string, unknown> | string | undefined;
    const markType = typeof mark === 'string' ? mark : mark?.type;
    const common = {
        ...themed,
        width: themed.width ?? 'container',
        height: themed.height ?? 'container',
        autosize: {
            type: 'fit',
            contains: 'padding',
            resize: true,
            ...((themed.autosize as Record<string, unknown> | undefined) ?? {})
        },
        background: 'transparent',
        config: {
            ...((themed.config as Record<string, unknown> | undefined) ?? {}),
            font: 'Manrope',
            view: {stroke: null},
            axis: {
                labelFont: 'Manrope',
                labelFontWeight: 500,
                titleFont: 'Manrope',
                titleFontWeight: 600
            },
            legend: {
                labelFont: 'Manrope',
                labelFontWeight: 500,
                titleFont: 'Manrope',
                titleFontWeight: 600
            },
            text: {font: 'Manrope', fontWeight: 500},
            title: {font: 'Manrope', fontWeight: 600}
        }
    };

    if (markType === 'bar') {
        return {
            ...common,
            mark: {
                ...(typeof mark === 'object' ? mark : {}),
                type: 'bar',
                stroke: CHART_OUTLINE_COLOR,
                strokeOpacity: 0.3,
                strokeWidth: 0.65
            }
        };
    }

    if (markType !== 'line' || !encoding || !color || typeof color.field !== 'string') return common;

    const seriesEncoding = {
        ...encoding,
        strokeDash: {
            field: color.field,
            type: 'nominal',
            scale: {range: [[1, 0], [7, 4]]},
            legend: null
        },
        shape: {
            field: color.field,
            type: 'nominal',
            scale: {range: ['circle', 'diamond']},
            legend: null
        }
    };
    const {shape: _shape, ...haloSeriesEncoding} = seriesEncoding;
    const haloEncoding = {...haloSeriesEncoding, color: {value: CHART_OUTLINE_COLOR}};
    const layerContainer: Record<string, unknown> = {...common};
    delete layerContainer.mark;
    delete layerContainer.encoding;
    const xField = (encoding.x as Record<string, unknown> | undefined)?.field;
    const yField = (encoding.y as Record<string, unknown> | undefined)?.field;
    const values = (themed.data as {values?: Array<Record<string, unknown>>} | undefined)?.values;
    const endpointLayers: Array<Record<string, unknown>> = [];
    if (xField === 'season' && typeof yField === 'string' && values && values.length > 1) {
        const ordered = [...values].sort((left, right) => Number(left.season) - Number(right.season));
        const endpoints = [ordered[0], ordered.at(-1)!];
        const endpointColors = [...teamChartDisplayPalette(team)];
        endpoints.forEach((endpoint, index) => {
            const value = Number(endpoint[yField]);
            const endpointData = {
                ...endpoint,
                endpointLabel: `${endpoint.season} · ${value >= 0 ? '+' : ''}${value.toFixed(3)}`
            };
            const endpointEncoding = {
                x: encoding.x,
                y: encoding.y,
                tooltip: encoding.tooltip
            };
            endpointLayers.push(
                {
                    data: {values: [endpointData]},
                    mark: {
                        type: 'point', filled: true, size: 120, color: endpointColors[index],
                        stroke: CHART_OUTLINE_COLOR, strokeWidth: 1.2
                    },
                    encoding: endpointEncoding
                },
                {
                    data: {values: [endpointData]},
                    mark: {
                        type: 'text', align: index === 0 ? 'left' : 'right', baseline: 'bottom',
                        dx: index === 0 ? 9 : -9, dy: -8, fontSize: 12, fontWeight: 600, color: endpointColors[index]
                    },
                    encoding: {...endpointEncoding, text: {field: 'endpointLabel', type: 'nominal'}}
                }
            );
        });
    }
    return {
        ...layerContainer,
        layer: [
            {
                mark: {type: 'line', strokeWidth: 3.6, strokeOpacity: 0.3},
                encoding: haloEncoding
            },
            {
                mark: {
                    ...(typeof mark === 'object' ? mark : {}),
                    type: 'line',
                    strokeWidth: 2.4,
                    point: {filled: true, size: 36, stroke: CHART_OUTLINE_COLOR, strokeOpacity: 0.75, strokeWidth: 0.8}
                },
                encoding: seriesEncoding
            },
            ...endpointLayers
        ]
    };
}

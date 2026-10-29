import {branding} from './sportsBranding';
import {chartComparisonKind, chartSeriesLabels} from './chartRows';
export type TeamChartPalette = readonly [primary: string, secondary: string];

// Reference: NFL Colors (Community), Figma node 44:26.
// Values use this application's canonical nflverse team abbreviations.
export const NFL_TEAM_CHART_PALETTES: Record<string, TeamChartPalette> = {
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

export const NFL_TEAM_NAMES: Record<string, string> = {
    ARI: 'CARDINALS', ATL: 'FALCONS', BAL: 'RAVENS', BUF: 'BILLS', CAR: 'PANTHERS', CHI: 'BEARS',
    CIN: 'BENGALS', CLE: 'BROWNS', DAL: 'COWBOYS', DEN: 'BRONCOS', DET: 'LIONS', GB: 'PACKERS',
    HOU: 'TEXANS', IND: 'COLTS', JAX: 'JAGUARS', KC: 'CHIEFS', LV: 'RAIDERS', LAC: 'CHARGERS',
    LA: 'RAMS', MIA: 'DOLPHINS', MIN: 'VIKINGS', NE: 'PATRIOTS', NO: 'SAINTS', NYG: 'GIANTS',
    NYJ: 'JETS', PHI: 'EAGLES', PIT: 'STEELERS', SF: '49ERS', SEA: 'SEAHAWKS', TB: 'BUCCANEERS',
    TEN: 'TITANS', WAS: 'COMMANDERS'
};

// Reference: NBA Colors (Community), Figma page 0:1.
// Primary and secondary follow the first two palette cards after each team's logo card.
export const NBA_TEAM_CHART_PALETTES: Record<string, TeamChartPalette> = {
    ATL: ['#E03A3E', '#F9A01B'],
    BOS: ['#007A33', '#BA9653'],
    BKN: ['#000000', '#FFFFFF'],
    CHA: ['#1D1160', '#00788C'],
    CHI: ['#CE1141', '#000000'],
    CLE: ['#860038', '#041E42'],
    DAL: ['#00538C', '#002B5E'],
    DEN: ['#0E2240', '#FEC524'],
    DET: ['#C8102E', '#1D42BA'],
    GSW: ['#1D428A', '#FFC72C'],
    HOU: ['#CE1141', '#000000'],
    IND: ['#002D62', '#FDBB30'],
    LAC: ['#C8102E', '#1D428A'],
    LAL: ['#552583', '#FDB927'],
    MEM: ['#5D76A9', '#12173F'],
    MIA: ['#98002E', '#F9A01B'],
    MIL: ['#00471B', '#EEE1C6'],
    MIN: ['#0C2340', '#236192'],
    NOP: ['#0C2340', '#C8102E'],
    NYK: ['#006BB6', '#F58426'],
    OKC: ['#007AC1', '#EF3B24'],
    ORL: ['#0077C0', '#C4CED4'],
    PHI: ['#006BB6', '#ED174C'],
    PHX: ['#1D1160', '#E56020'],
    POR: ['#E03A3E', '#000000'],
    SAC: ['#5A2D81', '#63727A'],
    SAS: ['#C4CED4', '#000000'],
    TOR: ['#CE1141', '#000000'],
    UTA: ['#002B5C', '#00471B'],
    WSH: ['#002B5C', '#E31837']
};

// Retained for callers that import the original NFL-only constant.
export const TEAM_CHART_PALETTES = NFL_TEAM_CHART_PALETTES;
const NBA_TEAM_ALIASES: Record<string, string> = {GS: 'GSW', NO: 'NOP', NY: 'NYK', SA: 'SAS', UTAH: 'UTA'};
const NFL_ESPN_LOGO_IDS: Record<string, string> = {LA: 'lar', WAS: 'wsh'};
const NBA_ESPN_LOGO_IDS: Record<string, string> = {GSW: 'gs', NOP: 'no', NYK: 'ny', SAS: 'sa', UTA: 'utah'};
export const DEFAULT_CHART_PALETTE: TeamChartPalette = ['#6F9FD1', '#78DCCA'];
export const CHART_SURFACE_COLOR = '#091521';
const CHART_CONTRAST_TARGET = 4.5;
const CHART_OUTLINE_COLOR = '#DBE8EE';
const CHART_LABEL_COLOR = '#C5D4DF';
const CHART_GRID_COLOR = '#31506A';
const METRIC_PLOT_HEIGHT = 130;
const METRIC_CHART_SPACING = 32;
const CHART_FONT = 'Manrope, Inter, ui-sans-serif, system-ui, sans-serif';

export function teamChartPalette(team: string, sport = 'nfl', season?: number, fallback: TeamChartPalette = DEFAULT_CHART_PALETTE): TeamChartPalette {
    const supplied = branding(team, sport.toLowerCase(), season).colors;
    if (supplied) return supplied;
    if (!['nfl', 'nba'].includes(sport.toLowerCase())) return fallback;
    const normalized = team.toUpperCase();
    if (sport.toLowerCase() === 'nba') {
        return NBA_TEAM_CHART_PALETTES[NBA_TEAM_ALIASES[normalized] ?? normalized] ?? DEFAULT_CHART_PALETTE;
    }
    return NFL_TEAM_CHART_PALETTES[normalized] ?? DEFAULT_CHART_PALETTE;
}

export function teamLogoUrl(team: string, sport = 'nfl', season?: number): string | null {
    const supplied = branding(team, sport.toLowerCase(), season).logo;
    if (supplied) return supplied;
    sport = sport.toLowerCase();
    if (sport === 'cfb' || sport === 'soccer') {
        const id = team.trim();
        if (!/^[1-9]\d*$/.test(id)) return null;
        return `https://a.espncdn.com/i/teamlogos/${sport === 'cfb' ? 'ncaa' : 'soccer'}/500/${id}.png`;
    }
    if (sport !== 'nfl' && sport !== 'nba') return null;
    const normalizedSport = sport.toLowerCase() === 'nba' ? 'nba' : 'nfl';
    const normalized = team.trim().toUpperCase();
    const canonical = normalizedSport === 'nba' ? (NBA_TEAM_ALIASES[normalized] ?? normalized) : normalized;
    const palettes = normalizedSport === 'nba' ? NBA_TEAM_CHART_PALETTES : NFL_TEAM_CHART_PALETTES;
    if (!(canonical in palettes)) return null;
    const logoId = normalizedSport === 'nba'
        ? (NBA_ESPN_LOGO_IDS[canonical] ?? canonical.toLowerCase())
        : (NFL_ESPN_LOGO_IDS[canonical] ?? canonical.toLowerCase());
    return `https://a.espncdn.com/i/teamlogos/${normalizedSport}/500/${logoId}.png`;
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

function accessibleChartColor(color: string): string {
    if (colorContrastRatio(color, CHART_SURFACE_COLOR) >= CHART_CONTRAST_TARGET) return color;
    for (let amount = 0.08; amount <= 0.8; amount += 0.04) {
        const candidate = mixWithWhite(color, amount);
        if (colorContrastRatio(candidate, CHART_SURFACE_COLOR) >= CHART_CONTRAST_TARGET) return candidate;
    }
    return CHART_OUTLINE_COLOR;
}

export function teamChartDisplayPalette(team: string, sport = 'nfl', season?: number): TeamChartPalette {
    const [primary, secondary] = teamChartPalette(team, sport, season);
    return [accessibleChartColor(primary), accessibleChartColor(secondary)];
}

export function teamChartSeriesPalette(team: string, count: number, sport = 'nfl', season?: number): string[] {
    const [primary, secondary] = teamChartDisplayPalette(team, sport, season);
    const colors: string[] = [];
    for (const color of [primary, secondary, '#A9C9F4', '#DBB3E7', '#B4D8B5', '#E8C69F', '#79D5DD', '#F3A8B4']) {
        // Interpolating brand colors created muddy, nearly identical middle seasons.
        if (colors.every(existing => Math.hypot(...rgb(existing).map((channel, i) => channel - rgb(color)[i])) > 70)) colors.push(color);
    }
    return Array.from({length: Math.max(2, count)}, (_, i) => colors[i % colors.length]);
}

export function chartSeriesStyles(spec: Record<string, unknown>, team: string, sport = 'nfl', season?: number) {
    const labels = chartSeriesLabels(spec);
    const grouped = chartComparisonKind(spec) === 'grouped-observations' && !(spec.usermeta as {colorField?: string})?.colorField;
    const colors = teamChartSeriesPalette(team, labels.length, sport, season);
    const shapes = ['circle', 'square', 'diamond', 'triangle-up', 'cross', 'triangle-down'];
    return labels.map((label, i) => ({label, color: colors[grouped ? 0 : i], shape: shapes[grouped ? 0 : i % shapes.length]}));
}

function polishAxis(channel: string, definition: Record<string, unknown>): Record<string, unknown> {
    if (definition.axis === null) return definition;
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
            grid: 'grid' in axis ? axis.grid : channel === 'y',
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

export function applyTeamChartPalette(specification: Record<string, unknown>, team: string, sport = 'nfl', season?: number): Record<string, unknown> {
    const themed = structuredClone(specification);
    const usermeta = themed.usermeta as Record<string, unknown> | undefined;
    const categoryRows = usermeta?.categoryLayout === 'rows';
    if (usermeta?.chartKind === 'metric-rows') {
        const seriesField = typeof usermeta.colorField === 'string' ? usermeta.colorField : typeof usermeta.seriesField === 'string' ? usermeta.seriesField : undefined;
        const seriesStyles = chartSeriesStyles(specification, team, sport, season);
        const domain = seriesStyles.map(series => series.label);
        const palette = seriesStyles.map(series => series.color);

        const polishNestedSpec = (node: Record<string, unknown>) => {
            // Also repair older saved specifications without modifying their evidence.
            const nodeValues = (node.data as {values?: Array<Record<string, unknown>>} | undefined)?.values;
            nodeValues?.forEach(row => {
                if (typeof row.display_value === 'string') row.display_value = row.display_value.replace(/^\+/, '');
            });
            const height = node.height;
            if (!categoryRows && (typeof height === 'number' || height && typeof height === 'object' && !Array.isArray(height) && 'step' in height)) {
                node.height = METRIC_PLOT_HEIGHT;
            }
            const nestedEncoding = node.encoding as Record<string, unknown> | undefined;
            const horizontal = nestedEncoding?.x as Record<string, unknown> | undefined;
            const vertical = nestedEncoding?.y as Record<string, unknown> | undefined;
            if (horizontal?.field === 'value' && vertical && vertical.field === seriesField) {
                nestedEncoding!.x = {
                    ...vertical,
                    type: 'ordinal',
                    axis: {
                        ...((vertical.axis as Record<string, unknown> | undefined) ?? {}),
                        title: null,
                        ticks: false,
                        domain: false,
                        grid: false,
                        labelAngle: 0
                    }
                };
                nestedEncoding!.y = {
                    ...horizontal,
                    scale: {...((horizontal.scale as Record<string, unknown> | undefined) ?? {}), zero: false, nice: true},
                    axis: {
                        ...((horizontal.axis as Record<string, unknown> | undefined) ?? {}),
                        title: null,
                        tickCount: 4,
                        grid: true
                    }
                };
            }
            const mark = node.mark as Record<string, unknown> | undefined;
            if (mark?.type === 'text') {
                node.mark = {...mark, align: categoryRows ? 'left' : 'center', dx: categoryRows ? 8 : 0,
                    dy: categoryRows ? 0 : -12, fontSize: 12};
                if (nestedEncoding) nestedEncoding.color = {value: '#EDF5FA'};
            }
            if (mark?.type === 'point' && mark.opacity !== 0.001) {
                node.mark = {...mark, opacity: 1, stroke: CHART_SURFACE_COLOR, strokeWidth: 1.5};
                if (nestedEncoding) nestedEncoding.shape = {field: seriesField, type: 'nominal',
                    scale: {domain, range: seriesStyles.map(series => series.shape)}, legend: null};
            }
            for (const channel of ['x', 'y']) {
                const definition = nestedEncoding?.[channel];
                if (definition && typeof definition === 'object') {
                    const def = definition as Record<string, unknown>;
                    const axis = def.axis as Record<string, unknown> | undefined;
                    if (def.field === seriesField && axis !== null) def.axis = {...axis, labels: true};
                    if (def.field === 'value' && axis?.format === '.0%') def.axis = {...axis, format: '.1%'};
                    nestedEncoding![channel] = polishAxis(channel, def);
                }
            }
            const nestedColor = nestedEncoding?.color as Record<string, unknown> | undefined;
            if (nestedColor?.field) {
                nestedEncoding!.color = {
                    ...nestedColor,
                    scale: {...((nestedColor.scale as Record<string, unknown> | undefined) ?? {}), domain, range: palette},
                    legend: nestedColor.legend === null ? null : {
                        ...((nestedColor.legend as Record<string, unknown> | undefined) ?? {}),
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
            for (const key of ['spec']) {
                const child = node[key];
                if (child && typeof child === 'object' && !Array.isArray(child)) polishNestedSpec(child as Record<string, unknown>);
            }
            for (const key of ['layer', 'vconcat', 'hconcat', 'concat']) {
                const children = node[key];
                if (Array.isArray(children)) {
                    for (const child of children) {
                        if (child && typeof child === 'object') polishNestedSpec(child as Record<string, unknown>);
                    }
                }
            }
        };
        polishNestedSpec(themed);
        return {
            ...themed,
            spacing: METRIC_CHART_SPACING,
            bounds: 'full',
            background: 'transparent',
            config: {
                ...((themed.config as Record<string, unknown> | undefined) ?? {}),
                font: CHART_FONT,
                view: {stroke: null},
                axis: {labelFont: CHART_FONT, labelFontWeight: 500, titleFont: CHART_FONT, titleFontWeight: 600},
                header: {labelFont: CHART_FONT, labelColor: CHART_LABEL_COLOR, labelFontWeight: 600},
                legend: {labelFont: CHART_FONT, labelFontWeight: 500, titleFont: CHART_FONT, titleFontWeight: 600},
                text: {font: CHART_FONT, fontWeight: 500},
                title: {font: CHART_FONT, fontWeight: 600, color: '#EDF5FA'}
            }
        };
    }
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
        const existingScale = color.scale as {domain?: unknown[]} | undefined;
        const domain = existingScale?.domain ?? (typeof colorField === 'string'
            ? [...new Set(values.map(value => value[colorField]))].sort((a, b) => String(a).localeCompare(String(b), undefined, {numeric:true})) : []);
        encoding!.color = {
            ...color,
            scale: {
                ...((color.scale as Record<string, unknown> | undefined) ?? {}),
                domain,
                range: teamChartSeriesPalette(team, Math.max(2, domain.length), sport, season)
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
            font: CHART_FONT,
            view: {stroke: null},
            axis: {
                labelFont: CHART_FONT,
                labelFontWeight: 500,
                titleFont: CHART_FONT,
                titleFontWeight: 600
            },
            legend: {
                labelFont: CHART_FONT,
                labelFontWeight: 500,
                titleFont: CHART_FONT,
                titleFontWeight: 600
            },
            text: {font: CHART_FONT, fontWeight: 500},
            title: {font: CHART_FONT, fontWeight: 600, color: '#EDF5FA'}
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
        const colorScale = (encoding.color as {scale: {domain: unknown[]; range: string[]}}).scale;
        endpoints.forEach((endpoint, index) => {
            const endpointColor = colorScale.range[Math.max(0, colorScale.domain.indexOf(endpoint[color.field as string]))];
            const value = Number(endpoint[yField]);
            const endpointData = {
                ...endpoint,
                endpointLabel: `${endpoint.season} · ${value.toFixed(3)}`
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
                        type: 'point', filled: true, size: 120, color: endpointColor,
                        stroke: CHART_OUTLINE_COLOR, strokeWidth: 1.2
                    },
                    encoding: endpointEncoding
                },
                {
                    data: {values: [endpointData]},
                    mark: {
                        type: 'text', align: index === 0 ? 'left' : 'right', baseline: 'bottom',
                        dx: index === 0 ? 9 : -9, dy: -8, fontSize: 12, fontWeight: 600, color: '#EDF5FA'
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
            {
                // Vega-Lite's points generated by `line.point` are too small to be
                // dependable pointer targets. Keep the visible marks above and add
                // a transparent interaction layer so every observation owns a
                // comfortably sized hover area and its encoded tooltip.
                mark: {type: 'point', filled: true, size: 700, opacity: 0.001},
                encoding: seriesEncoding
            },
            ...endpointLayers
        ]
    };
}

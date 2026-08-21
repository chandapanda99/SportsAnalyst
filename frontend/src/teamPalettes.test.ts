import { describe, expect, it } from 'vitest';
import {
  applyTeamChartPalette,
  CHART_SURFACE_COLOR,
  colorContrastRatio,
  DEFAULT_CHART_PALETTE,
  teamChartDisplayPalette,
  teamChartPalette,
  teamChartSeriesPalette,
  TEAM_CHART_PALETTES
} from './teamPalettes';

describe('NFL chart palettes', () => {
  it('covers every NFL team exposed by the plugin', () => {
    expect(Object.keys(TEAM_CHART_PALETTES)).toHaveLength(32);
    expect(teamChartPalette('KC')).toEqual(['#E31837', '#FFB81C']);
    expect(teamChartPalette('LA')).toEqual(['#003594', '#FFD100']);
  });

  it('falls back safely for an unknown team', () => {
    expect(teamChartPalette('unknown')).toEqual(DEFAULT_CHART_PALETTE);
  });

  it('extends team colors into a readable palette for multi-season comparisons', () => {
    const palette = teamChartSeriesPalette('CHI', 4);

    expect(palette).toHaveLength(4);
    expect(palette[0]).toBe(teamChartDisplayPalette('CHI')[0]);
    expect(palette[3]).toBe(teamChartDisplayPalette('CHI')[1]);
    expect(new Set(palette)).toHaveLength(4);
    expect(palette.every((color) => colorContrastRatio(color, CHART_SURFACE_COLOR) >= 3)).toBe(true);
  });

  it('brightens dark display colors without changing the official palette', () => {
    const official = teamChartPalette('LA');
    const display = teamChartDisplayPalette('LA');

    expect(official).toEqual(['#003594', '#FFD100']);
    expect(display[0]).not.toBe(official[0]);
    expect(colorContrastRatio(display[0], CHART_SURFACE_COLOR)).toBeGreaterThanOrEqual(3);
    expect(display[1]).toBe(official[1]);
  });

  it('applies team colors without mutating the stored chart specification', () => {
    const specification = {
      encoding: { color: { field: 'window', type: 'nominal' } }
    };
    const themed = applyTeamChartPalette(specification, 'KC');

    expect(themed).toMatchObject({
      background: 'transparent',
      width: 'container',
      height: 'container',
      autosize: { type: 'fit', contains: 'padding', resize: true },
      encoding: { color: { scale: { range: ['#E31837', '#FFB81C'] } } },
      config: {
        font: 'Manrope',
        axis: { labelFontWeight: 500, titleFontWeight: 600 },
        legend: { labelFontWeight: 500, titleFontWeight: 600 }
      }
    });
    expect(specification).toEqual({ encoding: { color: { field: 'window', type: 'nominal' } } });
  });

  it('layers line charts with a halo and non-color series cues', () => {
    const themed = applyTeamChartPalette(
      {
        mark: { type: 'line', point: true },
        encoding: {
          x: { field: 'week' },
          y: { field: 'epa' },
          color: { field: 'window', type: 'nominal' }
        }
      },
      'BUF'
    );

    expect(themed).not.toHaveProperty('mark');
    expect(themed).toMatchObject({
      layer: [
        { mark: { type: 'line', strokeWidth: 3.6, strokeOpacity: 0.3 } },
        {
          mark: { type: 'line', strokeWidth: 2.4, point: { size: 36, stroke: '#DBE8EE', strokeWidth: 0.8 } },
          encoding: {
            strokeDash: { scale: { range: [[1, 0], [7, 4]] } },
            shape: { scale: { range: ['circle', 'diamond'] } },
            color: { legend: { title: null, orient: 'top' } },
            x: { axis: { title: 'Week' } },
            y: { axis: { title: 'EPA / dropback', titleFontSize: 13, gridOpacity: 0.42 } }
          }
        }
      ]
    });
  });

  it('labels and distinguishes both endpoints of a season trend', () => {
    const themed = applyTeamChartPalette(
      {
        data: { values: [
          { season: 2022, value: -0.099, series: 'EPA/dropback' },
          { season: 2023, value: -0.066, series: 'EPA/dropback' },
          { season: 2025, value: 0.116, series: 'EPA/dropback' }
        ] },
        mark: { type: 'line', point: true },
        encoding: {
          x: { field: 'season', type: 'ordinal' },
          y: { field: 'value', type: 'quantitative' },
          color: { field: 'series', type: 'nominal' }
        }
      },
      'KC'
    ) as { layer: Array<Record<string, any>> };

    expect(themed.layer).toHaveLength(6);
    expect(themed.layer[2].data.values[0].endpointLabel).toBe('2022 · -0.099');
    expect(themed.layer[2].mark.color).toBe('#E31837');
    expect(themed.layer[4].data.values[0].endpointLabel).toBe('2025 · +0.116');
    expect(themed.layer[4].mark.color).toBe('#FFB81C');
  });
});

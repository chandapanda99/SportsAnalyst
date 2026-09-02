import { describe, expect, it } from 'vitest';
import {
  applyTeamChartPalette,
  CHART_SURFACE_COLOR,
  colorContrastRatio,
  NBA_TEAM_CHART_PALETTES,
  teamChartDisplayPalette,
  teamLogoUrl,
  teamChartPalette,
  teamChartSeriesPalette,
  TEAM_CHART_PALETTES
} from './teamPalettes';

describe('NFL chart palettes', () => {
  it('covers every NFL team exposed by the plugin', () => {
    expect(Object.keys(TEAM_CHART_PALETTES)).toHaveLength(32);
    expect(teamChartPalette('KC')).toEqual(['#E31837', '#FFB81C']);
    expect(teamChartPalette('LA')).toEqual(['#003594', '#FFD100']);
    expect(teamLogoUrl('LA')).toBe('https://a.espncdn.com/i/teamlogos/nfl/500/lar.png');
  });

  it('extends team colors into a readable palette for multi-season comparisons', () => {
    const palette = teamChartSeriesPalette('CHI', 4);

    expect(palette).toHaveLength(4);
    expect(palette[0]).toBe(teamChartDisplayPalette('CHI')[0]);
    expect(palette[3]).toBe(teamChartDisplayPalette('CHI')[1]);
    expect(new Set(palette)).toHaveLength(4);
    expect(palette.every((color) => colorContrastRatio(color, CHART_SURFACE_COLOR) >= 3)).toBe(true);
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
        },
        {mark: {type: 'point', size: 700, opacity: 0.001}}
      ]
    });
  });

  it('applies team colors inside independently scaled metric rows', () => {
    const themed = applyTeamChartPalette(
      {
        usermeta: {chartKind: 'metric-rows', metricRowCount: 1, seriesField: 'window'},
        data: {values: [{metric: 'EPA/dropback', window: '2024', value: -0.1}]},
        spacing: 10,
        spec: {
          height: {step: 25},
          layer: [{
            mark: {type: 'point'},
            encoding: {
              x: {field: 'value', type: 'quantitative', scale: {zero: true}},
              y: {field: 'window', type: 'nominal'},
              color: {field: 'window'}
            }
          }]
        }
      },
      'CHI'
    );

    expect(themed).toMatchObject({
      spacing: 32,
      bounds: 'full',
      spec: {
        height: 130,
        layer: [{encoding: {
          x: {field: 'window', type: 'ordinal'},
          y: {field: 'value', type: 'quantitative', scale: {zero: false}},
          color: {scale: {range: teamChartSeriesPalette('CHI', 2)}}
        }}]
      }
    });
  });

});

describe('NBA chart palettes', () => {
  it('covers all current teams without colliding with NFL abbreviations', () => {
    expect(Object.keys(NBA_TEAM_CHART_PALETTES)).toHaveLength(30);
    expect(teamChartPalette('ATL', 'nba')).toEqual(['#E03A3E', '#F9A01B']);
    expect(teamChartPalette('ATL', 'nfl')).toEqual(['#A71930', '#A5ACAF']);
    expect(teamChartPalette('SAC', 'nba')).toEqual(['#5A2D81', '#63727A']);
    expect(teamChartPalette('GS', 'nba')).toEqual(teamChartPalette('GSW', 'nba'));
    expect(teamLogoUrl('GSW', 'nba')).toBe('https://a.espncdn.com/i/teamlogos/nba/500/gs.png');
  });

  it('applies NBA colors to chart series through the shared theming path', () => {
    const palette = teamChartDisplayPalette('LAL', 'nba');
    const themed = applyTeamChartPalette(
      {encoding: {color: {field: 'window', type: 'nominal'}}},
      'LAL',
      'nba'
    );

    expect(themed).toMatchObject({
      encoding: {color: {scale: {range: [...palette]}}}
    });
    expect(palette.every((color) => colorContrastRatio(color, CHART_SURFACE_COLOR) >= 3)).toBe(true);
  });
});

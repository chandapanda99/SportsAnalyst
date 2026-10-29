import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/svelte';
import {afterEach, expect, it, vi} from 'vitest';
import DownloadScope from './DownloadScope.svelte';

const {catalog} = vi.hoisted(() => ({catalog: vi.fn()}));
vi.mock('./api', () => ({api: {downloadCatalog: catalog}}));
afterEach(() => {cleanup(); vi.clearAllMocks();});

it('scopes downloads by team and season-specific conference/division without fetching an entire league', async () => {
  catalog.mockResolvedValue({teams: [{value:'CHI',label:'Chicago Bears'}],
    conferences:[{value:'nfl:nfc',label:'NFC'}], divisions:[{value:'nfl:nfc-north',label:'NFC North'}]});
  const onchange = vi.fn();
  const result = render(DownloadScope, {sport:'nfl',season:2025,teams:[],onchange});
  expect(catalog).not.toHaveBeenCalled();
  await fireEvent.change(screen.getByLabelText('Download By'), {target:{value:'conference'}});
  await waitFor(() => expect(screen.getByRole('option',{name:'NFC'})).toBeTruthy());
  await fireEvent.change(screen.getByLabelText('Download Conference'), {target:{value:'nfl:nfc'}});
  expect(onchange).toHaveBeenLastCalledWith(expect.objectContaining({ready:true,conference_id:'nfl:nfc'}));
  await fireEvent.change(screen.getByLabelText('Download By'), {target:{value:'division'}});
  expect(onchange).toHaveBeenLastCalledWith(expect.objectContaining({ready:false}));
  await fireEvent.change(screen.getByLabelText('Download Division'), {target:{value:'nfl:nfc-north'}});
  expect(onchange).toHaveBeenLastCalledWith(expect.objectContaining({ready:true,division_id:'nfl:nfc-north'}));
  await result.rerender({sport:'nfl',season:2024,teams:[],onchange});
  await waitFor(() => expect(catalog).toHaveBeenLastCalledWith('nfl',2024,undefined));
  expect(onchange).toHaveBeenLastCalledWith(expect.objectContaining({ready:false}));
  await fireEvent.change(screen.getByLabelText('Download By'), {target:{value:'team'}});
  await fireEvent.change(screen.getByLabelText('Download Team'), {target:{value:'CHI'}});
  expect(onchange).toHaveBeenLastCalledWith(expect.objectContaining({ready:true,team_ids:['CHI']}));
});

it('does not invent soccer groups and offers retry when discovery fails', async () => {
  catalog.mockRejectedValueOnce(new Error('Discovery unavailable'))
    .mockResolvedValue({teams:[{value:'10',label:'Recorded Club'}],conferences:[],divisions:[]});
  const onchange = vi.fn();
  render(DownloadScope, {sport:'soccer',season:2025,competition:'eng.1',teams:[],onchange});
  await fireEvent.change(screen.getByLabelText('Download By'), {target:{value:'conference'}});
  await waitFor(() => expect(screen.getByRole('button',{name:'Retry Groups'})).toBeTruthy());
  expect(onchange).toHaveBeenLastCalledWith(expect.objectContaining({ready:false}));
  await fireEvent.click(screen.getByRole('button',{name:'Retry Groups'}));
  await waitFor(() => expect(screen.getByText(/No conferences or groups are recorded/)).toBeTruthy());
  await fireEvent.change(screen.getByLabelText('Download By'), {target:{value:'league'}});
  await fireEvent.change(screen.getByLabelText('Download By'), {target:{value:'team'}});
  await fireEvent.change(screen.getByLabelText('Download Team'), {target:{value:'10'}});
  expect(onchange).toHaveBeenLastCalledWith(expect.objectContaining({ready:true,team_ids:['10']}));
});

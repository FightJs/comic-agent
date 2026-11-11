// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {RuntimeCapacity} from './RuntimeCapacity';
import {api,ApiError} from './api';
vi.mock('./api',async()=>({...await vi.importActual('./api'),api:vi.fn()}));
const state=(revision=0,text=2)=>({revision,limits:{text,image:1,vision:1},usage:{text:{limit:text,active:2,waiting:3},image:{limit:1,active:0,waiting:0},vision:{limit:1,active:0,waiting:0}}});
afterEach(()=>{cleanup();vi.resetAllMocks();sessionStorage.clear();});
async function chooseText(value:string){const select=screen.getByRole('combobox',{name:'文本同时运行上限'});fireEvent.click(select);fireEvent.keyDown(select,{key:'Home'});for(let i=1;i<Number(value);i++)fireEvent.keyDown(select,{key:'ArrowDown'});fireEvent.keyDown(select,{key:'Enter'});}
it('shows shared live counts and only saves an explicit capacity change',async()=>{
  vi.mocked(api).mockResolvedValue(state());render(<RuntimeCapacity/>);
  expect(await screen.findByText('运行 2 · 排队 3')).toBeTruthy();
  expect(screen.getByRole('button',{name:'保存运行容量'})).toHaveProperty('disabled',true);
  await chooseText('1');expect(api).toHaveBeenCalledTimes(1);
  vi.mocked(api).mockResolvedValue(state(1,1));fireEvent.click(screen.getByRole('button',{name:'保存运行容量'}));
  await waitFor(()=>expect(api).toHaveBeenCalledWith('/runtime/limits',expect.objectContaining({method:'PUT',body:JSON.stringify({expected_revision:0,limits:{text:1,image:1,vision:1}})})));
  expect(await screen.findByText('运行容量已保存')).toBeTruthy();
  expect(screen.getByText(/缩小上限不会中止已提交请求/)).toBeTruthy();
});
it('preserves the draft on conflict and requires a deliberate version review',async()=>{
  vi.mocked(api).mockResolvedValue(state());render(<RuntimeCapacity/>);await screen.findByText('运行 2 · 排队 3');await chooseText('4');
  vi.mocked(api).mockRejectedValueOnce(new ApiError(409,'容量已更新')).mockResolvedValue(state(1,3));
  fireEvent.click(screen.getByRole('button',{name:'保存运行容量'}));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('容量已更新'));
  await waitFor(()=>expect(screen.getByText('当前已保存：3')).toBeTruthy());
  expect(screen.getByRole('combobox',{name:'文本同时运行上限'})).toHaveProperty('textContent',expect.stringContaining('4'));
  expect(screen.getByRole('button',{name:'保存运行容量'})).toHaveProperty('disabled',true);
  fireEvent.click(screen.getByRole('button',{name:'已核对最新设置，保留我的输入'}));
  vi.mocked(api).mockResolvedValue(state(2,4));fireEvent.click(screen.getByRole('button',{name:'保存运行容量'}));
  await waitFor(()=>expect(api).toHaveBeenLastCalledWith('/runtime/limits',expect.objectContaining({body:JSON.stringify({expected_revision:1,limits:{text:4,image:1,vision:1}})})));
});
it('keeps an unsaved draft across closing and reopening without silently rebasing it',async()=>{
  vi.mocked(api).mockResolvedValue(state());const view=render(<RuntimeCapacity/>);await screen.findByText('运行 2 · 排队 3');await chooseText('5');view.unmount();
  vi.mocked(api).mockResolvedValue(state(2,3));render(<RuntimeCapacity/>);await screen.findByText('当前已保存：3');
  expect(screen.getByRole('combobox',{name:'文本同时运行上限'})).toHaveProperty('textContent',expect.stringContaining('5'));
  expect(screen.getByRole('button',{name:'保存运行容量'})).toHaveProperty('disabled',true);
});
it('does not offer editable fallback limits after a failed initial load',async()=>{
  vi.mocked(api).mockRejectedValueOnce(new Error('本地服务暂不可用')).mockResolvedValue(state());render(<RuntimeCapacity/>);
  expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('本地服务暂不可用'));
  expect(screen.queryByRole('combobox')).toBeNull();fireEvent.click(screen.getByRole('button',{name:'刷新运行状态'}));
  expect(await screen.findByRole('combobox',{name:'文本同时运行上限'})).toBeTruthy();
});
it('refreshes live counts without replacing the current input or its reviewed revision',async()=>{
  vi.mocked(api).mockResolvedValue(state());render(<RuntimeCapacity/>);await screen.findByText('运行 2 · 排队 3');await chooseText('6');
  vi.mocked(api).mockResolvedValue({...state(1,3),usage:{...state().usage,text:{limit:3,active:4,waiting:1}}});
  fireEvent.click(screen.getByRole('button',{name:'刷新运行状态'}));
  expect(await screen.findByText('运行 4 · 排队 1')).toBeTruthy();
  expect(screen.getByRole('combobox',{name:'文本同时运行上限'})).toHaveProperty('textContent',expect.stringContaining('6'));
  expect(screen.getByRole('button',{name:'保存运行容量'})).toHaveProperty('disabled',true);
});
it('warns when the browser cannot retain the draft across closing',async()=>{
  vi.mocked(api).mockResolvedValue(state());render(<RuntimeCapacity/>);await screen.findByText('运行 2 · 排队 3');
  const persist=vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('storage blocked');});
  await chooseText('3');expect(screen.getByText(/浏览器无法保存容量草稿/)).toBeTruthy();
  expect(screen.queryByText(/刷新后会恢复这份输入/)).toBeNull();persist.mockRestore();
});

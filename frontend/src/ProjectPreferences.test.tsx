// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ProjectPreferences} from './ProjectPreferences';
import {api,ApiError} from './api';
vi.mock('./api',async()=>({...await vi.importActual('./api'),api:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();sessionStorage.clear();});
it('only saves explicit project text and preserves a new draft when deleting saved preferences',async()=>{
  vi.mocked(api).mockResolvedValueOnce({revision:1,text:'旧偏好'});
  render(<ProjectPreferences pid="p"/>);const input=await screen.findByLabelText('本项目创作偏好');await waitFor(()=>expect(input).toHaveProperty('disabled',false));
  fireEvent.change(input,{target:{value:'未保存的新偏好'}});expect(api).toHaveBeenCalledTimes(1);
  vi.mocked(api).mockResolvedValueOnce({revision:2,text:''});fireEvent.click(screen.getByRole('button',{name:'删除已保存偏好'}));
  expect(await screen.findByText('已删除已保存偏好；未保存输入仍保留。')).toBeTruthy();expect(input).toHaveProperty('value','未保存的新偏好');
  vi.mocked(api).mockResolvedValueOnce({revision:3,text:'未保存的新偏好'});fireEvent.click(screen.getByRole('button',{name:'保存项目偏好'}));
  await waitFor(()=>expect(api).toHaveBeenLastCalledWith('/projects/p/preferences',expect.objectContaining({method:'PUT',body:JSON.stringify({expected_revision:2,text:'未保存的新偏好'})})));
});
it('keeps a conflict draft and requires reviewing the latest saved version before overwrite',async()=>{
  vi.mocked(api).mockResolvedValueOnce({revision:1,text:'原偏好'});render(<ProjectPreferences pid="p"/>);
  const input=await screen.findByLabelText('本项目创作偏好');await waitFor(()=>expect(input).toHaveProperty('disabled',false));fireEvent.change(input,{target:{value:'我的输入'}});
  vi.mocked(api).mockRejectedValueOnce(new ApiError(409,'项目偏好已被更新；当前输入保留，请读取最新版本后核对')).mockResolvedValueOnce({revision:2,text:'其他窗口已保存的内容'});
  fireEvent.click(screen.getByRole('button',{name:'保存项目偏好'}));expect(await screen.findByText('其他窗口已保存的内容')).toBeTruthy();
  await waitFor(()=>expect(screen.getByRole('alert').textContent).toContain('已读取最新保存内容'));
  expect(screen.getByRole('alert').textContent).not.toContain('请读取最新版本');
  expect(input).toHaveProperty('value','我的输入');expect(screen.getByRole('button',{name:'保存项目偏好'})).toHaveProperty('disabled',true);
  fireEvent.click(screen.getByRole('button',{name:'已核对最新偏好，保留我的输入'}));
  expect(screen.getByRole('button',{name:'保存项目偏好'})).toHaveProperty('disabled',false);
});
it('restores an unsaved draft for its own project without copying it into another project',async()=>{
  vi.mocked(api).mockResolvedValue({revision:0,text:''});const a=render(<ProjectPreferences pid="a"/>);
  const input=await screen.findByLabelText('本项目创作偏好');await waitFor(()=>expect(input).toHaveProperty('disabled',false));fireEvent.change(input,{target:{value:'甲项目草稿'}});a.unmount();
  const b=render(<ProjectPreferences pid="b"/>);await waitFor(()=>expect(screen.getByLabelText('本项目创作偏好')).toHaveProperty('disabled',false));expect(screen.getByLabelText('本项目创作偏好')).toHaveProperty('value','');b.unmount();
  render(<ProjectPreferences pid="a"/>);await waitFor(()=>expect(screen.getByLabelText('本项目创作偏好')).toHaveProperty('disabled',false));expect(screen.getByLabelText('本项目创作偏好')).toHaveProperty('value','甲项目草稿');
});
it('does not invent an editable empty preference when the initial read fails',async()=>{
  vi.mocked(api).mockRejectedValue(new Error('本地服务不可用'));render(<ProjectPreferences pid="p"/>);
  expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('本地服务不可用'));
  expect(screen.getByRole('button',{name:'保存项目偏好'})).toHaveProperty('disabled',true);
});
it('does not persist credential-like text as a browser draft or submit it as preferences',async()=>{
  vi.mocked(api).mockResolvedValue({revision:0,text:''});render(<ProjectPreferences pid="private-draft"/>);
  const input=await screen.findByLabelText('本项目创作偏好');await waitFor(()=>expect(input).toHaveProperty('disabled',false));
  const syntheticKey='sk-'+('Z'.repeat(20));fireEvent.change(input,{target:{value:syntheticKey}});
  expect(sessionStorage.getItem('comic-project-preference-draft:private-draft')||'').not.toContain(syntheticKey);
  expect(screen.getByRole('button',{name:'保存项目偏好'})).toHaveProperty('disabled',true);
  expect(screen.getByText(/疑似包含密钥/)).toBeTruthy();expect(api).toHaveBeenCalledTimes(1);
  fireEvent.change(input,{target:{value:'台词简洁。'}});
  expect(sessionStorage.getItem('comic-project-preference-draft:private-draft')).toContain('台词简洁。');
  expect(screen.getByRole('button',{name:'保存项目偏好'})).toHaveProperty('disabled',false);
});

it('discards a credential-like cached draft before restoring an editor',async()=>{
  const syntheticKey='sk-'+('Q'.repeat(20));sessionStorage.setItem('comic-project-preference-draft:cached-private',JSON.stringify({revision:0,text:syntheticKey}));
  vi.mocked(api).mockResolvedValue({revision:0,text:''});render(<ProjectPreferences pid="cached-private"/>);
  await waitFor(()=>expect(screen.getByLabelText('本项目创作偏好')).toHaveProperty('disabled',false));
  expect(screen.getByLabelText('本项目创作偏好')).toHaveProperty('value','');
  expect(sessionStorage.getItem('comic-project-preference-draft:cached-private')).toBeNull();
});

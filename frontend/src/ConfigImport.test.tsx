// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ConfigImport} from './ConfigImport';
import {api} from './api';
vi.mock('./api',async()=>({...await vi.importActual('./api'),api:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
it('shows a redacted preview before applying and refreshes settings after success',async()=>{
  const applied=vi.fn();
  vi.mocked(api).mockImplementation(async path=>path.endsWith('/preview')?{token:'t',name:'创作配置',profiles:[{purpose:'text',url:'https://example.org/v1',model:'m',has_secret:true,secret_action:'replace'}]}:{applied:['text'],connection:'unverified'});
  render(<ConfigImport onApplied={applied}/>);
  fireEvent.change(screen.getByLabelText('选择配置包'),{target:{files:[new File(['{"secret":"private-key"}'],'配置.json',{type:'application/json'})]}});
  expect(await screen.findByText('创作配置')).toBeTruthy();
  expect(applied).not.toHaveBeenCalled();
  expect(screen.queryByText('private-key')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'应用这份配置'}));
  await waitFor(()=>expect(applied).toHaveBeenCalledOnce());
  expect(await screen.findByText(/配置已应用.*连接未验证/)).toBeTruthy();
});
it('keeps the preview when apply fails so the user can retry',async()=>{
  vi.mocked(api).mockImplementation(async path=>{if(path.endsWith('/preview'))return {token:'t',name:'待重试配置',profiles:[]};if(path.endsWith('/apply'))throw new Error('钥匙串未授权');return {};});
  render(<ConfigImport onApplied={()=>{}}/>);
  fireEvent.change(screen.getByLabelText('选择配置包'),{target:{files:[new File(['{}'],'配置.json')]}});
  fireEvent.click(await screen.findByRole('button',{name:'应用这份配置'}));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('钥匙串未授权'));
  expect(screen.getByText('待重试配置')).toBeTruthy();
});

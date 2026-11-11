// @vitest-environment jsdom
import {useState} from 'react';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {Conversation} from './Workflow';
import {api,type RecordItem} from './api';
vi.mock('./api',async()=>({...await vi.importActual('./api'),api:vi.fn()}));
vi.mock('./AgentPanel',()=>({AgentPanel:({boundRefs,onUseReply}:any)=>{const [draft,setDraft]=useState('');return <><input aria-label="助手未发送意见" value={draft} onChange={e=>setDraft(e.target.value)}/><span>固定底稿v{boundRefs[0].version}</span><button onClick={()=>onUseReply({id:'run',reply:'保持窗户方位一致',refs:boundRefs})}>测试导入AI回复</button></>}}));
HTMLDialogElement.prototype.showModal=function(){this.setAttribute("open","");};
HTMLDialogElement.prototype.close=function(){this.removeAttribute("open");};
afterEach(()=>{cleanup();vi.resetAllMocks();});
const record={id:'s',project_id:'p',kind:'script',title:'第1格',version:3,adopted:3,source:'manual',review:'pending',content:{episode:1,panel:1},created:'',updated:''} as RecordItem;
it('uses real batch assistant and explicitly carries its receipt into generation',async()=>{
  vi.mocked(api).mockImplementation(async(_path,options)=>options?.method==='POST'?{ids:['t']}:[]);
  render(<Conversation pid="batch-p" refs={[record]} operation="rewrite" refresh={async()=>{}}/>);
  fireEvent.click(await screen.findByRole('button',{name:'测试导入AI回复'}));
  expect((screen.getByLabelText('共同要求 / 整图要求') as HTMLTextAreaElement).value).toBe('保持窗户方位一致');
  expect(vi.mocked(api).mock.calls.some(([,o])=>o?.method==='POST')).toBe(false);
  fireEvent.click(screen.getByRole('button',{name:'按方案生成候选'}));
  await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([path])=>path.endsWith('/production-jobs'))).toBe(true));
  const call=vi.mocked(api).mock.calls.find(([path])=>path.endsWith('/production-jobs'))!;
  expect(JSON.parse(String(call[1]?.body))).toMatchObject({agent_run_ids:['run'],refs:[{id:'s',version:3}],instruction:'保持窗户方位一致'});
});

it('reopens the current version discussion without resurrecting an old nested result dialog',async()=>{
  localStorage.setItem('comic-ui:result-open:reopen-ps','true');
  localStorage.setItem('comic-ui:result-groups:reopen-ps','["old-group"]');
  vi.mocked(api).mockResolvedValue([]);
  render(<Conversation pid="reopen-p" refs={[{...record,version:4}]} operation="rewrite" refresh={async()=>{}}/>);
  await screen.findByRole('button',{name:'测试导入AI回复'});
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(screen.getByRole('button',{name:'查看本组修改结果 · 连续比较'})).toBeTruthy();
});

it('keeps the open assistant and plan on their original versions when the source updates',async()=>{
  vi.mocked(api).mockResolvedValue([]);
  const props={pid:'stale-p',operation:'rewrite' as const,refresh:async()=>{}};
  const view=render(<Conversation {...props} refs={[record]}/>);
  await screen.findByRole('button',{name:'测试导入AI回复'});
  fireEvent.change(screen.getByLabelText('助手未发送意见'),{target:{value:'保留未发送意见'}});
  fireEvent.change(screen.getByLabelText('共同要求 / 整图要求'),{target:{value:'保留原方案'}});
  view.rerender(<Conversation {...props} refs={[{...record,version:4}]}/>);
  expect((screen.getByLabelText('助手未发送意见') as HTMLInputElement).value).toBe('保留未发送意见');
  expect((screen.getByLabelText('共同要求 / 整图要求') as HTMLTextAreaElement).value).toBe('保留原方案');
  expect(screen.getByText('固定底稿v3')).toBeTruthy();
  expect(screen.getByText(/底稿已有新版本，当前讨论/)).toBeTruthy();
  expect((screen.getByRole('button',{name:'按方案生成候选'}) as HTMLButtonElement).disabled).toBe(true);
});

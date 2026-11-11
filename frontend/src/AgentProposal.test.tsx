// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {AgentProposal} from './AgentProposal';
import {api} from './api';
vi.mock('./api',async()=>({...await vi.importActual('./api'),api:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();localStorage.clear();});
const summary={id:'proposal',title:'调整画面',status:'pending',source:'ai'};
const detail={...summary,changes:[{target:'record',id:'script',title:'第2话第7格',kind:'script',version:1,before:{description:'旧画面'},patch:{description:'雨夜重逢'}}]};
it('requires opening and reviewing a proposal before an explicit adoption',async()=>{
  const changed=vi.fn();vi.mocked(api).mockImplementation(async (_path,options)=>options?.method==='POST'?{records:[{id:'script',version:2}]}:detail);
  render(<AgentProposal pid="p" proposal={summary} runStatus="completed" onChanged={changed}/>);
  expect(screen.queryByRole('button',{name:'采用这些修改'})).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'查看修改候选'}));
  expect(await screen.findByText('雨夜重逢')).toBeTruthy();
  expect(screen.getByText('旧画面')).toBeTruthy();
  expect(changed).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'采用这些修改'}));
  await waitFor(()=>expect(changed).toHaveBeenCalledOnce());
  expect(await screen.findByText('已采用')).toBeTruthy();
});
it('blocks adoption while a target has unsaved local edits',async()=>{
  vi.mocked(api).mockResolvedValue(detail);localStorage.setItem('comic-draft:p:script','{"content":{"description":"未保存意见"}}');
  render(<AgentProposal pid="p" proposal={summary} runStatus="completed" onChanged={()=>{}}/>);
  fireEvent.click(screen.getByRole('button',{name:'查看修改候选'}));
  fireEvent.click(await screen.findByRole('button',{name:'采用这些修改'}));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('未保存'));
  expect(vi.mocked(api).mock.calls.some(([,options])=>options?.method==='POST')).toBe(false);
});

it('shows new script identity and deletion consequences without graph wording',async()=>{
  vi.mocked(api).mockResolvedValue({...summary,changes:[
    {target:'script_create',id:'anchor',title:'参考格',kind:'script',version:1,location:{episode:2,panel:7},before:{},patch:{panel:8,description:'新增镜头'}},
    {target:'script_delete',id:'script',title:'删除格',kind:'script',version:1,location:{episode:2,panel:9},before:{description:'删除前画面'},patch:{reason:'重复'},dependencies:[{id:'script',kind:'script',title:'删除格',version:1},{id:'image',kind:'image',title:'关联图片',version:2}]},
  ]});
  render(<AgentProposal pid="p" proposal={summary} runStatus="completed" onChanged={()=>{}}/>);
  fireEvent.click(screen.getByRole('button',{name:'查看修改候选'}));
  expect(await screen.findByText('新增脚本 · 第2话第8格')).toBeTruthy();
  expect(screen.getByText('删除前画面')).toBeTruthy();
  expect(screen.getByText(/关联图片 · v2/)).toBeTruthy();
  expect(screen.queryByText(/图谱修改写入改编层/)).toBeNull();
});

it('blocks script deletion while a dependent image has unsaved edits',async()=>{
  vi.mocked(api).mockResolvedValue({...summary,changes:[{target:'script_delete',id:'script',title:'删除格',kind:'script',version:1,before:{description:'旧画面'},patch:{reason:'重复'},dependencies:[{id:'image',title:'关联图片',kind:'image',version:1}]}]});
  localStorage.setItem('comic-draft:p:image','未保存');
  render(<AgentProposal pid="p" proposal={summary} runStatus="completed" onChanged={()=>{}}/>);
  fireEvent.click(screen.getByRole('button',{name:'查看修改候选'}));
  fireEvent.click(await screen.findByRole('button',{name:'采用这些修改'}));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('未保存'));
  expect(vi.mocked(api).mock.calls.some(([,options])=>options?.method==='POST')).toBe(false);
});

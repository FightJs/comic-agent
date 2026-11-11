// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {SelectionAssistant} from './SelectionAssistant';
import {api} from './api';
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:vi.fn()}));
HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
afterEach(()=>{cleanup();vi.resetAllMocks();});
const record={id:'r',project_id:'p',kind:'outline',version:1,content:{html:'<p>原文</p>'}} as any;
const selection={start:0,end:2,text:'原文'};
const proposal={id:'proposal',title:'局部候选',status:'pending',source:'mock',changes:[{version:1,selection,patch:{text:'建议'}}]};
it('freezes the selection, displays a persistent candidate and only applies after the explicit action',async()=>{
 const onApply=vi.fn().mockResolvedValue(undefined);
 const run={id:'run',status:'completed',message:'只改选段',reply:'已提出候选',proposals:[proposal]};
 const session={id:'s',version:1,refs:[{id:'r',version:1}],selection,runs:[run]};
 vi.mocked(api).mockImplementation(async(path,options)=>{
  if(path.endsWith('selection=true'))return [];
  if(path.endsWith('/sessions')&&options)return {...session,version:0,runs:[]};
  if(path.endsWith('/messages'))return run;
  if(path.endsWith('/sessions/s'))return session;
  if(path.endsWith('/proposals/proposal'))return proposal;
  throw Error(path);
 });
 render(<SelectionAssistant record={record} selection={selection} onClose={vi.fn()} onApply={onApply}/>);
 fireEvent.change(screen.getByRole('textbox',{name:'修改要求或问题'}),{target:{value:'只改选段'}});
 fireEvent.click(screen.getByRole('button',{name:'发送给 Pi'}));
 fireEvent.click(await screen.findByRole('button',{name:/局部候选/}));
 await screen.findByText('建议替换');expect(onApply).not.toHaveBeenCalled();
 expect(JSON.parse(vi.mocked(api).mock.calls.find(([path,options])=>path.endsWith('/sessions')&&options)![1]!.body as string).selection).toEqual(selection);
 fireEvent.click(screen.getByRole('button',{name:'采用选段修改并保存'}));
 await waitFor(()=>expect(onApply).toHaveBeenCalledWith(proposal));
 expect(await screen.findByText('已采用；原版本保留')).toBeTruthy();
});
it('retains the candidate and surfaces a version conflict instead of claiming adoption',async()=>{
 const session={id:'s',version:1,refs:[{id:'r',version:1}],selection,runs:[{id:'run',status:'completed',message:'问题',reply:'候选',proposals:[proposal]}]};
 vi.mocked(api).mockImplementation(async path=>path.endsWith('selection=true')?[session]:path.endsWith('/proposals/proposal')?proposal:session);
 render(<SelectionAssistant record={record} selection={selection} onClose={vi.fn()} onApply={async()=>{throw Error('原稿已有新版本');}}/>);
 fireEvent.change(await screen.findByRole('combobox',{name:'历史选段讨论'}),{target:{value:'s'}});
 fireEvent.click(await screen.findByRole('button',{name:/局部候选/}));
 fireEvent.click(await screen.findByRole('button',{name:'采用选段修改并保存'}));
 expect(await screen.findByText('原稿已有新版本')).toBeTruthy();
 expect(screen.getByRole('button',{name:'采用选段修改并保存'})).toBeTruthy();
});
it('keeps the modal open while adoption is pending so toolbar edits cannot be overwritten',async()=>{
 let finish!:()=>void;
 const pending=new Promise<void>(resolve=>{finish=resolve;});const close=vi.fn();
 const session={id:'s',version:1,refs:[{id:'r',version:1}],selection,runs:[{id:'run',status:'completed',message:'问题',reply:'候选',proposals:[proposal]}]};
 vi.mocked(api).mockImplementation(async path=>path.endsWith('selection=true')?[session]:path.endsWith('/proposals/proposal')?proposal:session);
 render(<SelectionAssistant record={record} selection={selection} onClose={close} onApply={()=>pending}/>);
 fireEvent.change(await screen.findByRole('combobox',{name:'历史选段讨论'}),{target:{value:'s'}});
 fireEvent.click(await screen.findByRole('button',{name:/局部候选/}));
 fireEvent.click(await screen.findByRole('button',{name:'采用选段修改并保存'}));
 fireEvent.click(screen.getByRole('button',{name:'关闭面板'}));
 expect(close).not.toHaveBeenCalled();
 finish();await screen.findByText('已采用；原版本保留');
 fireEvent.click(screen.getByRole('button',{name:'关闭面板'}));expect(close).toHaveBeenCalledOnce();
});
it('requires a fresh checkbox grant for paused selection continuation and sends only the continuation endpoint',async()=>{
 const parent={id:'pause',status:'paused',checkpoint:{model_requests:20,tool_calls:20,session_saved:true,unreturned_models:0,unresolved_tools:0},message:'固定要求',reply:'已暂停',proposals:[]};
 let continued=false;
 const session={id:'s',version:1,refs:[{id:'r',version:1}],selection,runs:[parent]};
 vi.mocked(api).mockImplementation(async(path,options)=>{
  if(path.endsWith('selection=true'))return [session];
  if(path.endsWith('/continue')){continued=true;return {id:'child'};}
  return continued?{...session,version:2,runs:[{...parent,status:'continued'},{id:'child',status:'completed',message:'固定要求',reply:'续接完成',proposals:[]}]}:session;
 });
 render(<SelectionAssistant record={record} selection={selection} onClose={vi.fn()} onApply={vi.fn()}/>);
 fireEvent.change(await screen.findByRole('combobox',{name:'历史选段讨论'}),{target:{value:'s'}});
 const button=await screen.findByRole('button',{name:'明确续接此检查点'});
 expect(button.hasAttribute('disabled')).toBe(true);
 fireEvent.click(screen.getByRole('checkbox'));
 fireEvent.click(button);
 expect(await screen.findByText('续接完成')).toBeTruthy();
 const call=vi.mocked(api).mock.calls.find(([path])=>path.endsWith('/continue'))!;
 expect(JSON.parse(call[1]!.body as string)).toEqual({confirm:true,expected_version:1});
 expect(vi.mocked(api).mock.calls.some(([path])=>path.endsWith('/messages'))).toBe(false);
});
it('shows sequenced Pi reply deltas during a run and uses the persisted final answer when it ends',async()=>{
 const run={id:'stream',status:'running',message:'询问',reply:'',proposals:[]};
 const session={id:'s',version:1,refs:[{id:'r',version:1}],selection,runs:[run]};
 vi.mocked(api).mockImplementation(async path=>{
  if(path.endsWith('selection=true'))return [session];
  if(path.endsWith('/sessions/s'))return session;
  if(path.endsWith('/runs/stream?after=0'))return {...run,tool_calls:1,events:[{seq:1,event:'text_delta',delta:'已读第一段'}]};
  if(path.endsWith('/runs/stream?after=1'))return {...run,status:'completed',reply:'最终完整答复',events:[{seq:2,event:'text_delta',delta:'后续文字'}]};
  throw Error(path);
 });
 render(<SelectionAssistant record={record} selection={selection} onClose={vi.fn()} onApply={vi.fn()}/>);
 fireEvent.change(await screen.findByRole('combobox',{name:'历史选段讨论'}),{target:{value:'s'}});
 expect(await screen.findByText('已读第一段')).toBeTruthy();
 expect(await screen.findByText('最终完整答复')).toBeTruthy();
 expect(screen.queryByText('已读第一段后续文字')).toBeNull();
});
it('pauses a selection run and does not call it allowance exhaustion',async()=>{
 let requested=false,settled=false;
 const run=()=>({id:'manual',status:settled?'paused':'running',pause_requested:requested,message:'固定选段问题',reply:'部分答复',proposals:[],checkpoint:settled?{reason:'manual_pause',model_requests:1,tool_calls:0,session_saved:true,unreturned_models:0,unresolved_tools:0}:null});
 const session=()=>({id:'s',version:1,refs:[{id:'r',version:1}],selection,runs:[run()]});
 vi.mocked(api).mockImplementation(async path=>{
  if(path.endsWith('selection=true'))return [session()];
  if(path.endsWith('/sessions/s'))return session();
  if(path.endsWith('/pause')){requested=true;return run();}
  if(path.includes('/runs/manual?after=')){if(requested)settled=true;return {...run(),events:[]};}
  throw Error(path);
 });
 render(<SelectionAssistant record={record} selection={selection} onClose={vi.fn()} onApply={vi.fn()}/>);
 fireEvent.change(await screen.findByRole('combobox',{name:'历史选段讨论'}),{target:{value:'s'}});
 fireEvent.click(await screen.findByRole('button',{name:'暂停到检查点'}));
 expect(await screen.findByText(/已按请求停止新派发/)).toBeTruthy();
 expect(screen.queryByText(/本段额度已用完/)).toBeNull();
 expect(screen.getByRole('button',{name:'明确续接此检查点'}).hasAttribute('disabled')).toBe(true);
 expect(vi.mocked(api).mock.calls.some(([path])=>path.endsWith('/cancel'))).toBe(false);
});
it('does not offer a grant for an uncertain selection checkpoint',async()=>{
 const session={id:'s',version:1,refs:[{id:'r',version:1}],selection,runs:[{id:'uncertain',status:'paused',message:'问题',reply:'部分返回',proposals:[],checkpoint:{reason:'manual_pause',model_requests:1,tool_calls:1,session_saved:true,unreturned_models:0,unresolved_tools:1}}]};
 vi.mocked(api).mockImplementation(async path=>path.endsWith('selection=true')?[session]:session);
 render(<SelectionAssistant record={record} selection={selection} onClose={vi.fn()} onApply={vi.fn()}/>);
 fireEvent.change(await screen.findByRole('combobox',{name:'历史选段讨论'}),{target:{value:'s'}});
 expect(await screen.findByText(/检查点仍有未决调用/)).toBeTruthy();
 expect(screen.queryByRole('checkbox')).toBeNull();
});
it('repairs an interrupted selection run without sending the new draft or granting continuation',async()=>{
 let repaired=false;
 const current=()=>({id:'s',version:1,refs:[{id:'r',version:1}],selection,runs:[{id:'broken',status:repaired?'paused':'interrupted',message:'固定选段任务',reply:'部分',proposals:[],checkpoint:{reason:repaired?'tools_recovered':undefined,model_requests:1,tool_calls:1,session_saved:true,unreturned_models:0,unresolved_tools:repaired?0:1}}]});
 vi.mocked(api).mockImplementation(async path=>{
  if(path.endsWith('selection=true'))return [current()];if(path.endsWith('/sessions/s'))return current();
  if(path.endsWith('/tool-receipts'))return {receipts:[],recovery_available:true,read_only:true};
  if(path.endsWith('/recover-tools')){repaired=true;return {};}
  throw Error('unexpected '+path);
 });
 render(<SelectionAssistant record={record} selection={selection} onClose={vi.fn()} onApply={vi.fn()}/>);
 fireEvent.change(await screen.findByLabelText('历史选段讨论'),{target:{value:'s'}});
 fireEvent.click(await screen.findByRole('button',{name:'核对工具回执'}));
 fireEvent.change(screen.getByLabelText('修改要求或问题'),{target:{value:'新意见'}});
 fireEvent.click(await screen.findByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'明确仅补回已保存结果'}));
 expect((await screen.findByRole('checkbox',{name:/授权新增最多20/}) as HTMLInputElement).checked).toBe(false);
 expect(screen.getByText('结果已补回，原任务已暂停；请明确续接或结束。')).toBeTruthy();expect(screen.queryByText(/本段额度已用完/)).toBeNull();
 expect((screen.getByLabelText('修改要求或问题') as HTMLTextAreaElement).value).toBe('新意见');
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/messages')||p.endsWith('/continue'))).toBe(false);
});

// @vitest-environment jsdom
import { cleanup,fireEvent,render,screen,waitFor } from '@testing-library/react';
import { afterEach,expect,it,vi } from 'vitest';
import { AgentPanel } from './AgentPanel';
import { api } from './api';
vi.mock('./api', async () => ({...await vi.importActual('./api'),api:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
it('restores server conversation and retains input when sending fails',async()=>{
  vi.mocked(api).mockImplementation(async path=>{
    if(path==='/agent/health')return {status:'ready'};
    if(path.endsWith('/agent/sessions?stage=outline'))return [{id:'s',stage:'outline',version:1,refs:[]}];
    if(path.endsWith('/agent/sessions/s'))return {id:'s',stage:'outline',version:1,refs:[],runs:[{id:'r',message:'之前的问题',reply:'有依据的答复',status:'completed',usage:{totalTokens:0}}]};
    if(path.endsWith('/messages'))throw new Error('文本密钥缺失');
    return {};
  });
  render(<AgentPanel pid="p" stage="outline" records={[]}/>);
  expect(await screen.findByText('有依据的答复')).toBeTruthy();
  expect(screen.getByText(/用量未知/)).toBeTruthy();
  expect(screen.getByRole('button',{name:'发送消息'}).hasAttribute('disabled')).toBe(true);
  fireEvent.change(screen.getByLabelText('发送给 AI 的消息'),{target:{value:'继续优化'}});
  fireEvent.click(screen.getByRole('button',{name:'发送消息'}));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('文本密钥缺失'));
  expect(screen.getByRole('alert').closest('form')).not.toBeNull();
  expect((screen.getByLabelText('发送给 AI 的消息') as HTMLTextAreaElement).value).toBe('继续优化');
});
it('creates a session with selected immutable refs before sending',async()=>{
  const sent:any[]=[];
  vi.mocked(api).mockImplementation(async (path,options)=>{
    if(path==='/agent/health')return {status:'ready'};
    if(path.endsWith('?stage=outline'))return [];
    if(options?.body){const value=JSON.parse(String(options.body));sent.push(value);if(path.endsWith('/sessions'))return {id:'s',version:0,refs:value.refs,runs:[]};return {id:'r',status:'completed',reply:'建议',message:'修改第一话'};}
    if(path.endsWith('/sessions/s'))return {id:'s',version:1,refs:[{id:'doc',version:3}],runs:[]};
    return {};
  });
  render(<AgentPanel pid="p" stage="outline" records={[{id:'doc',project_id:'p',kind:'outline',title:'全书细纲',version:3,adopted:1,source:'manual',review:'pending',content:{},created:'',updated:''}]}/>);
  await screen.findByLabelText('全书细纲 · v3');
  fireEvent.click(screen.getByLabelText('全书细纲 · v3'));
  fireEvent.change(screen.getByLabelText('发送给 AI 的消息'),{target:{value:'修改第一话'}});
  fireEvent.click(screen.getByRole('button',{name:'发送消息'}));
  await waitFor(()=>expect(sent.length).toBe(2));
  expect(sent[0]).toEqual({stage:'outline',refs:[{id:'doc',version:3}]});
  expect(sent[1].expected_version).toBe(0);
  expect(screen.getByRole('combobox',{name:'AI 会话'}).textContent).toContain('1 条消息');
});
it('keeps unsent drafts when closing and scopes them to each stage',async()=>{
  vi.mocked(api).mockImplementation(async path=>path==='/agent/health'?{status:'ready'}:[]);
  const first=render(<AgentPanel pid="draft-project" stage="outline" records={[]}/>);
  await screen.findByRole('button',{name:'发送消息'});
  fireEvent.change(screen.getByLabelText('发送给 AI 的消息'),{target:{value:'很长的改编意见尚未发送'}});
  first.unmount();
  const second=render(<AgentPanel pid="draft-project" stage="memory" records={[]}/>);
  await screen.findByRole('button',{name:'发送消息'});
  expect((screen.getByLabelText('发送给 AI 的消息') as HTMLTextAreaElement).value).toBe('');
  second.unmount();
  render(<AgentPanel pid="draft-project" stage="outline" records={[]}/>);
  await screen.findByRole('button',{name:'发送消息'});
  expect((screen.getByLabelText('发送给 AI 的消息') as HTMLTextAreaElement).value).toBe('很长的改编意见尚未发送');
});
it('pages through every panel reference instead of hiding items after 100',async()=>{
  vi.mocked(api).mockImplementation(async path=>path==='/agent/health'?{status:'ready'}:[]);
  const records=Array.from({length:121},(_,i)=>({id:'pkg'+i,project_id:'many',kind:'package',title:'生图包'+(i+1),version:1,adopted:1,source:'manual',review:'pending',content:{episode:1,panel:i+1},created:'',updated:''}));
  render(<AgentPanel pid="many" stage="package" records={records}/>);
  await screen.findByRole('button',{name:'发送消息'});
  fireEvent.click(screen.getByRole('button',{name:'下一页资料'}));
  fireEvent.click(screen.getByRole('button',{name:'下一页资料'}));
  expect(screen.getByLabelText(/生图包121 · v1/)).toBeTruthy();
  fireEvent.click(screen.getByLabelText(/生图包121 · v1/));
  expect(screen.getByText('本次资料 · 1 项固定版本')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('查找资料'),{target:{value:'生图包121'}});
  expect(screen.getAllByRole('checkbox').length).toBe(1);
});

it('binds a batch discussion to exact selected versions and imports only completed replies explicitly',async()=>{
  const useReply=vi.fn(),sent:any[]=[];
  vi.mocked(api).mockImplementation(async (path,options)=>{
    if(path==='/agent/health')return {status:'ready'};
    if(path.includes('/sessions?'))return [];
    if(path.endsWith('/sessions')){const body=JSON.parse(String(options?.body));sent.push(body);return {id:'bound',version:0,refs:body.refs};}
    if(path.endsWith('/messages'))return {id:'answer',message:'优化这些格',reply:'已完成的建议',status:'completed'};
    return {};
  });
  render(<AgentPanel pid="bound-project" stage="script" records={[]} boundRefs={[{id:'panel',version:4}]} onUseReply={useReply}/>);
  await screen.findByRole('button',{name:'发送消息'});
  expect(screen.queryByRole('checkbox')).toBeNull();
  fireEvent.change(screen.getByLabelText('发送给 AI 的消息'),{target:{value:'优化这些格'}});
  fireEvent.click(screen.getByRole('button',{name:'发送消息'}));
  expect(await screen.findByText('已完成的建议')).toBeTruthy();
  expect(sent[0]).toEqual({stage:'script',refs:[{id:'panel',version:4}]});
  expect(useReply).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'将此回复加入生成方案'}));
  expect(useReply).toHaveBeenCalledWith(expect.objectContaining({id:'answer',reply:'已完成的建议',refs:[{id:'panel',version:4}]}));
});
it('requires explicit new allowance to continue a paused checkpoint and retains a separate unsent message',async()=>{
  const paused={id:'paused',status:'paused',message:'固定原任务',reply:'已查询部分资料',error:'turn_limit',checkpoint:{model_requests:20,model_limit:20,tool_calls:20,tool_limit:50,unresolved_tools:0,unreturned_models:0,session_saved:true}};
  let resumed=false;
  vi.mocked(api).mockImplementation(async(path,opts)=>{
    if(path==='/agent/health')return {status:'ready'};
    if(path.endsWith('?stage=outline'))return [{id:'s',version:1,stage:'outline',refs:[]}];
    if(path.endsWith('/continue')){resumed=true;return {id:'child',status:'completed',reply:'续接完成',message:'继续原任务'};}
    if(path.endsWith('/sessions/s'))return {id:'s',version:resumed?2:1,stage:'outline',refs:[],runs:resumed?[{...paused,status:'continued'},{id:'child',status:'completed',reply:'续接完成',message:'继续原任务',continuation:{parent_run_id:'paused',known_tokens:147,unknown_runs:0}}]:[paused]};
    return {};
  });
  render(<AgentPanel pid="continue-confirm" stage="outline" records={[]}/>);
  const button=await screen.findByRole('button',{name:'明确续接此检查点'});
  expect(button).toHaveProperty('disabled',true);
  fireEvent.change(screen.getByLabelText('发送给 AI 的消息'),{target:{value:'这条新意见还没发送'}});
  expect(screen.getByRole('button',{name:'发送消息'})).toHaveProperty('disabled',true);
  fireEvent.click(screen.getByLabelText('已核对原固定输入，授权新增最多20次模型请求和50次工具派发；费用未知。'));
  fireEvent.click(button);expect(await screen.findByText('续接完成')).toBeTruthy();
  expect(api).toHaveBeenCalledWith('/projects/continue-confirm/agent/runs/paused/continue',expect.objectContaining({body:JSON.stringify({expected_version:1,confirm:true})}));
  expect(screen.getByLabelText('发送给 AI 的消息')).toHaveProperty('value','这条新意见还没发送');
  expect(screen.getByText(/续接链已知147 tokens/)).toBeTruthy();
  expect(vi.mocked(api).mock.calls.some(([path])=>path.endsWith('/messages'))).toBe(false);
});
it('keeps the paused checkpoint after a scope conflict and lets the user end it without more generation',async()=>{
  const paused={id:'paused',status:'paused',message:'固定旧稿',reply:'部分答复',checkpoint:{model_requests:20,model_limit:20,tool_calls:20,tool_limit:50,unresolved_tools:0,unreturned_models:0,session_saved:true}};
  vi.mocked(api).mockImplementation(async path=>{
    if(path==='/agent/health')return {status:'ready'};
    if(path.endsWith('?stage=outline'))return [{id:'s',version:1,stage:'outline',refs:[]}];
    if(path.endsWith('/sessions/s'))return {id:'s',version:1,stage:'outline',refs:[],runs:[paused]};
    if(path.endsWith('/continue'))throw Error('原稿已变化，不能续接旧输入');
    if(path.endsWith('/cancel'))return {...paused,status:'cancelled'};
    return {};
  });
  render(<AgentPanel pid="continue-conflict" stage="outline" records={[]}/>);
  await screen.findByRole('button',{name:'明确续接此检查点'});
  fireEvent.click(screen.getByLabelText('已核对原固定输入，授权新增最多20次模型请求和50次工具派发；费用未知。'));
  fireEvent.click(screen.getByRole('button',{name:'明确续接此检查点'}));
  const error=await screen.findByRole('alert');expect(error.textContent).toContain('原稿已变化');expect(error.closest('form')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'结束这次暂停'}));
  await waitFor(()=>expect(screen.queryByRole('button',{name:'明确续接此检查点'})).toBeNull());
  expect(vi.mocked(api).mock.calls.filter(([path])=>path.endsWith('/continue'))).toHaveLength(1);
});
it('pauses the active discussion instead of cancelling and preserves unsent instructions',async()=>{
 let paused=false;
 const run=()=>({id:'manual',status:paused?'paused':'running',message:'原始要求',reply:'部分答复',pause_requested:paused,checkpoint:paused?{reason:'manual_pause',model_requests:1,model_limit:20,tool_calls:0,tool_limit:50,session_saved:true,unreturned_models:0,unresolved_tools:0}:null});
 vi.mocked(api).mockImplementation(async path=>{
  if(path==='/agent/health')return {status:'ready'};
  if(path.includes('/sessions?'))return [{id:'s',stage:'outline',version:1,refs:[]}];
  if(path.endsWith('/sessions/s'))return {id:'s',stage:'outline',version:1,refs:[],runs:[run()]};
  if(path.endsWith('/pause')){paused=true;return {...run(),status:'running'};}
  if(path.includes('/runs/manual?after='))return {...run(),events:[]};
  return {};
 });
 render(<AgentPanel pid="manual-project" stage="outline" records={[]}/>);
 const pause=await screen.findByRole('button',{name:'暂停到检查点'});
 fireEvent.change(screen.getByLabelText('发送给 AI 的消息'),{target:{value:'尚未发送的新意见'}});
 fireEvent.click(pause);
 expect(await screen.findByRole('heading',{name:'已按请求暂停，检查点已保留'})).toBeTruthy();
 expect((screen.getByLabelText('发送给 AI 的消息') as HTMLTextAreaElement).value).toBe('尚未发送的新意见');
 expect(screen.getByRole('button',{name:'明确续接此检查点'}).hasAttribute('disabled')).toBe(true);
 expect(vi.mocked(api).mock.calls.some(([path])=>path.endsWith('/cancel'))).toBe(false);
});
it('recovers saved tool results separately from the unchecked continuation allowance and preserves drafts',async()=>{
 let recovered=false;
 vi.mocked(api).mockImplementation(async path=>{
  if(path==='/agent/health')return {status:'ready'};
  if(path.includes('/sessions?'))return [{id:'s',stage:'outline',version:2,refs:[]}];
  if(path.endsWith('/sessions/s'))return {id:'s',stage:'outline',version:2,refs:[],runs:[{id:'broken',message:'原任务',reply:'部分',status:recovered?'paused':'failed',checkpoint:{reason:recovered?'tools_recovered':undefined,session_saved:true,unresolved_tools:recovered?0:1,unreturned_models:0}}]};
  if(path.endsWith('/tool-receipts'))return {receipts:[],recovery_available:true,read_only:true};
  if(path.endsWith('/recover-tools')){recovered=true;return {};}
  throw Error('unexpected '+path);
 });
 render(<AgentPanel pid="recovery" stage="outline" records={[]}/>);
 fireEvent.click(await screen.findByRole('button',{name:'核对工具回执'}));
 fireEvent.change(screen.getByLabelText('发送给 AI 的消息'),{target:{value:'保留新意见'}});
 fireEvent.click(await screen.findByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'明确仅补回已保存结果'}));
 expect(await screen.findByRole('heading',{name:'结果已补回，原任务已暂停；请明确续接或结束'})).toBeTruthy();
 const grant=await screen.findByRole('checkbox',{name:/授权新增最多20/});expect((grant as HTMLInputElement).checked).toBe(false);
 expect((screen.getByLabelText('发送给 AI 的消息') as HTMLTextAreaElement).value).toBe('保留新意见');
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/continue')||p.endsWith('/messages'))).toBe(false);
});

// @vitest-environment jsdom
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {SetupAssistant} from './SetupAssistant';
import {Settings} from './Auxiliary';
import {api} from './api';
vi.mock('./api',async()=>({...await vi.importActual('./api'),api:vi.fn()}));
HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
afterEach(()=>{cleanup();vi.resetAllMocks();});
const capacity={revision:0,limits:{text:2,image:1,vision:1},usage:{text:{limit:2,active:0,waiting:0},image:{limit:1,active:0,waiting:0},vision:{limit:1,active:0,waiting:0}}};
const profile={purpose:'text',url:'http://fixture/v1',model:'fixture',has_secret:true};
const action={id:'a',kind:'apply_config',attachment:'config0',status:'pending',display:{name:'图片包',scope:'system_all_projects',profiles:[{purpose:'image',url:'http://image/v1',model:'image-fixture',secret_action:'replace'}]}};
const run={id:'r',session_id:'s',status:'completed',message:'配置图片包',reply:'建议核对图片包后应用。',actions:[action],public_input:{profiles:[],selection:{hashes:[]},catalog:[]},usage:null,error:''};
it('requires reviewing each concrete action before explicitly applying it',async()=>{
 const applied=vi.fn();let state=run;
 vi.mocked(api).mockImplementation(async(path,opts)=>{
  if(path.startsWith('/settings'))return profile;
  if(path.endsWith('/sessions/s'))return {id:'s',version:1,runs:[state]};
  if(path.endsWith('/apply')){state={...run,actions:[{...action,status:'applied'}]};return state;}
  return [{id:'s',version:1,created:'2026-11-05'}];
 });
 render(<SetupAssistant pid="review-test" onApplied={applied} onClose={()=>{}}/>);
 const apply=await screen.findByRole('button',{name:'应用此配置包'});
 expect(apply).toHaveProperty('disabled',true);
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/apply'))).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'查看变更并核对'}));
 expect(screen.getByText('image-fixture')).toBeTruthy();
 fireEvent.click(apply);
 await waitFor(()=>expect(applied).toHaveBeenCalled());
 expect(screen.getByText('已应用 · 连接未验证')).toBeTruthy();
});
it('keeps a failed message draft and never changes configuration on send failure',async()=>{
 vi.mocked(api).mockImplementation(async(path,opts)=>{
  if(path.startsWith('/settings'))return profile;
  if(path.endsWith('/messages'))throw Error('暂时不可用');
  if(path.endsWith('/sessions/s'))return {id:'s',version:0,runs:[]};
  if(opts?.method==='POST')return {id:'s',version:0,runs:[]};return [];
 });
 render(<SetupAssistant pid="failure-test" onApplied={async()=>{}} onClose={()=>{}}/>);
 fireEvent.change(await screen.findByLabelText('配置或流程要求'),{target:{value:'帮我检查一致性流程'}});
 await waitFor(()=>expect(screen.getByRole('button',{name:'发送给配置助手'})).toHaveProperty('disabled',false));
 fireEvent.click(screen.getByRole('button',{name:'发送给配置助手'}));
 expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('暂时不可用'));
 expect(screen.getByLabelText('配置或流程要求')).toHaveProperty('value','帮我检查一致性流程');
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/apply'))).toBe(false);
});
it('protects unsaved manual configuration before opening the assistant',async()=>{
 vi.mocked(api).mockImplementation(async(path)=>path==='/runtime/limits'?capacity:path.startsWith('/settings')?profile:[]);
 render(<Settings onClose={()=>{}}/>);
 await waitFor(()=>expect(screen.getByLabelText('服务地址')).toHaveProperty('value','http://fixture/v1'));
 fireEvent.change(screen.getByLabelText('服务地址'),{target:{value:'http://draft/v1'}});
 expect(screen.getByRole('button',{name:'AI 配置与流程助手'})).toHaveProperty('disabled',true);
 expect(screen.getByLabelText('服务地址')).toHaveProperty('value','http://draft/v1');
 fireEvent.click(screen.getByRole('button',{name:'还原已保存配置'}));
 expect(screen.getByLabelText('服务地址')).toHaveProperty('value','http://fixture/v1');
 expect(screen.getByRole('button',{name:'AI 配置与流程助手'})).toHaveProperty('disabled',false);
});
it('sends configuration files only to the staging endpoint and attaches an opaque token',async()=>{
 let sent:any;let uploaded:any;
 vi.mocked(api).mockImplementation(async(path,opts)=>{
  if(path.startsWith('/settings'))return profile;
  if(path==='/config-packages/preview'){uploaded=opts?.body;return {token:'opaque',name:'配置待核对',profiles:action.display.profiles};}
  if(path.endsWith('/messages')){sent=JSON.parse(String(opts?.body));return {...run,actions:[]};}
  if(path.endsWith('/sessions/s'))return {id:'s',version:1,runs:[{...run,actions:[]}]};
  if(opts?.method==='POST')return {id:'s',version:0,runs:[]};return [];
 });
 render(<SetupAssistant pid="upload-test" onApplied={async()=>{}} onClose={()=>{}}/>);
 await waitFor(()=>expect(screen.getByLabelText('配置或流程要求')).toHaveProperty('disabled',false));
 const file=new File(['{"secret":"never-copy-to-chat"}'],'模型包.json',{type:'application/json'});
 fireEvent.change(screen.getByLabelText('附加模型配置包'),{target:{files:[file]}});
 expect(await screen.findByText('配置待核对')).toBeTruthy();
 fireEvent.change(screen.getByLabelText('配置或流程要求'),{target:{value:'核对这份包'}});
 await waitFor(()=>expect(screen.getByRole('button',{name:'发送给配置助手'})).toHaveProperty('disabled',false));fireEvent.click(screen.getByRole('button',{name:'发送给配置助手'}));
 await waitFor(()=>expect(sent.config_tokens).toEqual(['opaque']));
 expect(uploaded).toBe(file);expect(JSON.stringify(sent)).not.toContain('never-copy-to-chat');
});
it('blocks manual edits while a direct package upload is in progress',async()=>{
 let release!:(value:any)=>void;const pending=new Promise(resolve=>{release=resolve;});
 vi.mocked(api).mockImplementation(async(path)=>path==='/runtime/limits'?capacity:path.startsWith('/settings')?profile:path==='/config-packages/preview'?pending:[]);
 render(<Settings onClose={()=>{}}/>);
 await waitFor(()=>expect(screen.getByLabelText('服务地址')).toHaveProperty('disabled',false));
 fireEvent.change(screen.getByLabelText('选择配置包'),{target:{files:[new File(['{}'],'包.json')]}});
 expect(screen.getByLabelText('服务地址')).toHaveProperty('disabled',true);
 expect(screen.getByRole('button',{name:'AI 配置与流程助手'})).toHaveProperty('disabled',true);
 release({token:'direct',name:'直导包',profiles:[]});
 await waitFor(()=>expect(screen.getByLabelText('服务地址')).toHaveProperty('disabled',false));
});
it('selecting new conversation does not reopen the last saved session',async()=>{
 vi.mocked(api).mockImplementation(async(path)=>path.startsWith('/settings')?profile:path.endsWith('/sessions/s')?{id:'s',version:1,runs:[run]}:[{id:'s',version:1,created:'2026-11-05'}]);
 render(<SetupAssistant pid="new-selector-test" onApplied={async()=>{}} onClose={()=>{}}/>);
 await screen.findByText('建议核对图片包后应用。');
 fireEvent.click(screen.getByRole('combobox',{name:'设置对话'}));fireEvent.click(screen.getByText('新对话'));
 await waitFor(()=>expect(screen.queryByText('建议核对图片包后应用。')).toBeNull());
});
it('blocks editing while switching configuration purpose',async()=>{
 let release!:(value:any)=>void;const pending=new Promise(resolve=>{release=resolve;});
 vi.mocked(api).mockImplementation(async(path)=>path==='/runtime/limits'?capacity:path==='/settings'?profile:path==='/settings?purpose=image'?pending:[]);
 render(<Settings onClose={()=>{}}/>);
 await waitFor(()=>expect(screen.getByLabelText('服务地址')).toHaveProperty('disabled',false));
 fireEvent.click(screen.getByRole('combobox',{name:'用途'}));fireEvent.click(screen.getByText('生图与修改'));
 expect(screen.getByLabelText('服务地址')).toHaveProperty('disabled',true);
 release({...profile,purpose:'image',model:'image-model'});
 await waitFor(()=>expect(screen.getByLabelText('模型标识')).toHaveProperty('value','image-model'));
});

it('restores an unsent draft when session creation completes after closing',async()=>{
 let release!:(value:any)=>void;let created=false;const pending=new Promise(resolve=>{release=resolve;});
 vi.mocked(api).mockImplementation(async(path,opts)=>{
  if(path.startsWith('/settings'))return profile;
  if(path.endsWith('/sessions')&&opts?.method==='POST')return pending;
  if(path.endsWith('/sessions/closed'))return {id:'closed',version:0,runs:[]};
  return created?[{id:'closed',version:0}]:[];
 });
 const first=render(<SetupAssistant pid="late-create" onApplied={async()=>{}} onClose={()=>{}}/>);
 await waitFor(()=>expect(screen.getByLabelText('配置或流程要求')).toHaveProperty('disabled',false));
 fireEvent.change(screen.getByLabelText('配置或流程要求'),{target:{value:'尚未提交的配置要求'}});fireEvent.click(screen.getByRole('button',{name:'发送给配置助手'}));
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p,o])=>p.endsWith('/sessions')&&o?.method==='POST')).toBe(true));first.unmount();
 await act(async()=>{created=true;release({id:'closed',version:0,runs:[]});});
 render(<SetupAssistant pid="late-create" onApplied={async()=>{}} onClose={()=>{}}/>);
 await waitFor(()=>expect(screen.getByLabelText('配置或流程要求')).toHaveProperty('disabled',false));
 expect(screen.getByLabelText('配置或流程要求')).toHaveProperty('value','尚未提交的配置要求');
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/messages'))).toBe(false);
});
it('removing an attachment after a late send response does not invalidate its pending candidate',async()=>{
 let release!:(value:any)=>void;let finished=false;const pending=new Promise(resolve=>{release=resolve;});
 vi.mocked(api).mockImplementation(async(path,opts)=>{
  if(path.startsWith('/settings'))return profile;
  if(path==='/config-packages/preview')return {token:'late-token',name:'已提交包',profiles:action.display.profiles};
  if(path.endsWith('/messages'))return pending;
  if(path.endsWith('/sessions/s'))return {id:'s',version:finished?1:0,runs:finished?[run]:[]};
  return [{id:'s',version:0}];
 });
 const first=render(<SetupAssistant pid="late-send" onApplied={async()=>{}} onClose={()=>{}}/>);
 await waitFor(()=>expect(screen.getByLabelText('配置或流程要求')).toHaveProperty('disabled',false));
 fireEvent.change(screen.getByLabelText('附加模型配置包'),{target:{files:[new File(['{}'],'包.json')]}});await screen.findByText('已提交包');
 fireEvent.change(screen.getByLabelText('配置或流程要求'),{target:{value:'核对并配置这份包'}});
 await waitFor(()=>expect(screen.getByRole('button',{name:'发送给配置助手'})).toHaveProperty('disabled',false));fireEvent.click(screen.getByRole('button',{name:'发送给配置助手'}));
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/messages'))).toBe(true));first.unmount();
 await act(async()=>{finished=true;release(run);});
 render(<SetupAssistant pid="late-send" onApplied={async()=>{}} onClose={()=>{}}/>);await screen.findByText('建议核对图片包后应用。');
 fireEvent.click(screen.getByRole('button',{name:'移除 已提交包'}));
 expect(vi.mocked(api).mock.calls.some(([p])=>p==='/config-packages/discard')).toBe(false);
});
it.each([true,false])('reconciles an applied attachment on reopen with response already received: %s',async(received)=>{
 let release!:(value:any)=>void;let state={id:'s',version:0,runs:[] as any[]};const pending=new Promise(resolve=>{release=resolve;});
 vi.mocked(api).mockImplementation(async(path,opts)=>{
  if(path.startsWith('/settings'))return profile;
  if(path==='/config-packages/preview')return {token:'apply-late',name:'在途应用包',profiles:action.display.profiles};
  if(path.endsWith('/messages')){state={id:'s',version:1,runs:[run]};return run;}
  if(path.endsWith('/apply'))return pending;
  if(path.endsWith('/sessions/s'))return state;
  return [{id:'s',version:state.version}];
 });
 const first=render(<SetupAssistant pid={`late-apply-${received}`} onApplied={async()=>{}} onClose={()=>{}}/>);
 await waitFor(()=>expect(screen.getByLabelText('配置或流程要求')).toHaveProperty('disabled',false));
 fireEvent.change(screen.getByLabelText('附加模型配置包'),{target:{files:[new File(['{}'],'包.json')]}});await screen.findByText('在途应用包');
 fireEvent.change(screen.getByLabelText('配置或流程要求'),{target:{value:'配置此包'}});
 await waitFor(()=>expect(screen.getByRole('button',{name:'发送给配置助手'})).toHaveProperty('disabled',false));fireEvent.click(screen.getByRole('button',{name:'发送给配置助手'}));
 await screen.findByText('建议核对图片包后应用。');fireEvent.click(screen.getByRole('button',{name:'查看变更并核对'}));fireEvent.click(screen.getByRole('button',{name:'应用此配置包'}));
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/apply'))).toBe(true));first.unmount();
 const applied={...run,actions:[{...action,status:'applied'}]};state={...state,runs:[applied]};
 if(received)await act(async()=>{release(applied);});
 render(<SetupAssistant pid={`late-apply-${received}`} onApplied={async()=>{}} onClose={()=>{}}/>);
 await screen.findByText('已应用 · 连接未验证');
 await waitFor(()=>expect(screen.queryByText('在途应用包')).toBeNull());
 await act(async()=>{release(applied);});
});
it('shows queried catalog receipts separately from the initial filtered page',async()=>{
 const value={...run,actions:[],public_input:{...run.public_input,catalog:[],catalog_total:0,catalog_library_total:55,catalog_reads:[{query:'一致性',start:0,total:3,next_start:1,items:[{id:'flow',name:'一致性流程',version:'1',hash:'fixed-hash'}]}]}};
 vi.mocked(api).mockImplementation(async(path)=>path.startsWith('/settings')?profile:path.endsWith('/sessions/s')?{id:'s',version:1,runs:[value]}:[{id:'s',version:1}]);
 render(<SetupAssistant pid="catalog-receipts" onApplied={async()=>{}} onClose={()=>{}}/>);
 expect(await screen.findByText('已安装流程库 55 项；初始目录 0 项，筛选匹配 0 项。')).toBeTruthy();
 expect(screen.getByText('一致性 · 从第1项读取1/3项，仍有后续。')).toBeTruthy();
 expect(screen.getByText('一致性流程 v1')).toBeTruthy();
});
it('does not present a historical filtered total as the full library size',async()=>{
 const value={...run,actions:[],public_input:{catalog:[],catalog_total:0}};
 vi.mocked(api).mockImplementation(async(path)=>path.startsWith('/settings')?profile:path.endsWith('/sessions/s')?{id:'s',version:1,runs:[value]}:[{id:'s',version:1}]);
 render(<SetupAssistant pid="legacy-catalog-count" onApplied={async()=>{}} onClose={()=>{}}/>);
 expect(await screen.findByText('已安装流程库数量未记录；初始目录 0 项，筛选匹配 0 项。')).toBeTruthy();
 expect(screen.queryByText('已安装流程库 0 项；初始目录 0 项，筛选匹配 0 项。')).toBeNull();
});
it('distinguishes pinned enabled entries from initial filter matches',async()=>{
 const value={...run,actions:[],public_input:{catalog:[{hash:'pinned',name:'当前流程',version:'1'}],catalog_total:0,catalog_library_total:55,catalog_reads:[]}};
 vi.mocked(api).mockImplementation(async(path)=>path.startsWith('/settings')?profile:path.endsWith('/sessions/s')?{id:'s',version:1,runs:[value]}:[{id:'s',version:1}]);
 render(<SetupAssistant pid="pinned-catalog-count" onApplied={async()=>{}} onClose={()=>{}}/>);
 expect(await screen.findByText('已安装流程库 55 项；初始目录 1 项，筛选匹配 0 项。')).toBeTruthy();
});
it('labels bundled rule proposals and catalog source without claiming complete migration',async()=>{
 const install={...action,kind:'install_skill',attachment:'bundled:fixed',display:{id:'comic-shot-design',name:'条漫镜头',version:'1.0.0-pi.1',hash:'fixed',file_count:13,stages:['package'],tags:['条漫'],main_rules:'只读当前批准依据。',origin:'bundled_rules_first_pass'}};
 const value={...run,actions:[install],public_input:{...run.public_input,available_bundles:[{id:'comic-shot-design',name:'条漫镜头'}],catalog_library_total:0,catalog_total:0,catalog_reads:[{source:'bundled',query:'不存在',start:0,total:0,next_start:null,items:[]}]}};
 vi.mocked(api).mockImplementation(async(path)=>path.startsWith('/settings')?profile:path.endsWith('/sessions/s')?{id:'s',version:1,runs:[value]}:[{id:'s',version:1}]);
 render(<SetupAssistant pid="bundled-rules-ui" onApplied={async()=>{}} onClose={()=>{}}/>);
 fireEvent.click(await screen.findByRole('button',{name:'查看变更并核对'}));
 expect(screen.getByText('随应用提供的首版规则包；仅规则层，脚本与完整迁移未完成。')).toBeTruthy();
 expect(screen.getByText('已安装流程库 0 项；初始目录 0 项，筛选匹配 0 项。')).toBeTruthy();
 expect(screen.getByText('查询来源：应用内置规则（查询不安装）')).toBeTruthy();
 expect(screen.getByText('查询 不存在：无匹配项。')).toBeTruthy();
 expect(screen.getByRole('button',{name:'安装此Skill'})).toHaveProperty('disabled',false);
});
it('identifies each installation candidate by name before expanding it',async()=>{
 const install={...action,kind:'install_skill',attachment:'bundled:fixed',display:{name:'条漫镜头',version:'1.0.0-pi.1',origin:'bundled_rules_first_pass'}};
 const value={...run,actions:[install]};
 vi.mocked(api).mockImplementation(async(path)=>path.startsWith('/settings')?profile:path.endsWith('/sessions/s')?{id:'s',version:1,runs:[value]}:[{id:'s',version:1}]);
 render(<SetupAssistant pid="bundled-candidate-names" onApplied={async()=>{}} onClose={()=>{}}/>);
 expect(await screen.findByRole('heading',{name:'安装共享Skill · 条漫镜头 v1.0.0-pi.1'})).toBeTruthy();
 expect(screen.getByRole('button',{name:'安装此Skill'})).toHaveProperty('disabled',true);
});

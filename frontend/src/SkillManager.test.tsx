// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {SkillManager} from './SkillManager';
import {api} from './api';
vi.mock('./api',async()=>({...await vi.importActual('./api'),api:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
it('installs a data bundle then lets the user explicitly enable its frozen hash',async()=>{
  const item={hash:'abc',id:'faithful',name:'忠实流程',version:'1',stages:['outline'],tags:['一致性'],files:['SKILL.md'],entrypoint:'SKILL.md'};
  let installed=false;const saved:any[]=[];
  vi.mocked(api).mockImplementation(async (path,options)=>{
    if(path==='/skills/import'){installed=true;return item;}
    if(path==='/skills')return installed?[item]:[];
    if(options?.method==='PUT'){saved.push(JSON.parse(String(options.body)));return {revision:1,hashes:['abc']};}
    return {revision:0,hashes:[]};
  });
  render(<SkillManager pid="p"/>);
  await screen.findByLabelText('导入Skill包');
  fireEvent.change(screen.getByLabelText('导入Skill包'),{target:{files:[new File(['{}'],'流程.json')]}});
  expect(await screen.findByText('忠实流程')).toBeTruthy();
  expect(saved).toEqual([]);
  fireEvent.click(screen.getByLabelText('启用 忠实流程 v1'));
  fireEvent.click(screen.getByRole('button',{name:'保存本项目流程'}));
  await waitFor(()=>expect(saved).toEqual([{expected_revision:0,hashes:['abc']}]));
});
it('keeps the current selection when saving conflicts',async()=>{
  vi.mocked(api).mockImplementation(async (path,options)=>{
    if(path==='/skills')return [{hash:'x',id:'x',name:'创意流程',version:'2',stages:['outline'],tags:[],files:['SKILL.md']}];
    if(options?.method==='PUT')throw new Error('流程选择已变化');
    return {revision:0,hashes:[]};
  });
  render(<SkillManager pid="p"/>);
  fireEvent.click(await screen.findByLabelText('启用 创意流程 v2'));
  fireEvent.click(screen.getByRole('button',{name:'保存本项目流程'}));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('流程选择已变化'));
  expect((screen.getByLabelText('启用 创意流程 v2') as HTMLInputElement).checked).toBe(true);
});
it('preserves unsaved project flow choices when closing and reopening settings',async()=>{
  vi.mocked(api).mockImplementation(async path=>path==='/skills'?[{hash:'d',id:'d',name:'待确认流程',version:'1',stages:['outline'],tags:[],files:['SKILL.md']}]:{revision:0,hashes:[]});
  const view=render(<SkillManager pid="draft-skills"/>);
  fireEvent.click(await screen.findByLabelText('启用 待确认流程 v1'));
  view.unmount();
  render(<SkillManager pid="draft-skills"/>);
  expect((await screen.findByLabelText('启用 待确认流程 v1') as HTMLInputElement).checked).toBe(true);
});
it('shows pinned dependencies without silently selecting them and retains a rejected selection',async()=>{
  const items=[{hash:'root',id:'root',name:'引用主流程',version:'1',stages:['script'],tags:[],files:['SKILL.md'],entrypoint:'SKILL.md',dependencies:[{id:'shared',version:'1.0'}]},{hash:'dep',id:'shared',name:'公共资料库',version:'1.0',stages:['review'],tags:[],files:['SKILL.md'],entrypoint:'SKILL.md'}];
  vi.mocked(api).mockImplementation(async(path,opts)=>{
    if(path==='/skills')return items;
    if(opts?.method==='PUT'){const value=JSON.parse(String(opts.body));if(value.hashes.length===1)throw Error('请同时启用shared v1.0；未更新选择');return {revision:1,hashes:value.hashes};}
    return {revision:0,hashes:[]};
  });
  render(<SkillManager pid="dependency-project"/>);
  expect(await screen.findByText(/依赖：shared v1.0/)).toBeTruthy();
  fireEvent.click(screen.getByLabelText('启用 引用主流程 v1'));
  expect(screen.getByLabelText('启用 公共资料库 v1.0')).toHaveProperty('checked',false);
  fireEvent.click(screen.getByRole('button',{name:'保存本项目流程'}));await screen.findByRole('alert');
  expect(screen.getByLabelText('启用 引用主流程 v1')).toHaveProperty('checked',true);
  fireEvent.change(screen.getByLabelText('查找流程'),{target:{value:'shared'}});
  expect(screen.queryByLabelText('启用 引用主流程 v1')).toBeNull();
  fireEvent.click(screen.getByLabelText('启用 公共资料库 v1.0'));
  fireEvent.click(screen.getByRole('button',{name:'保存本项目流程'}));
  await waitFor(()=>expect(api).toHaveBeenLastCalledWith('/projects/dependency-project/skills',expect.objectContaining({body:JSON.stringify({expected_revision:0,hashes:['root','dep']})})));
});

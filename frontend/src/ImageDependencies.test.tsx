// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,it} from 'vitest';
import {useState} from 'react';
import {ImageDependencies} from './ImageDependencies';
import type {RecordItem} from './api';
afterEach(cleanup);
const records=[{id:'p',kind:'package',version:3,adopted:3,title:'前格生图包',content:{episode:1,panel:1},source:'manual',review:'approved'},
 {id:'img',kind:'image',version:2,adopted:2,title:'已审核前图',content:{url:'/real-image'},source:'ai',review:'approved'},
 {id:'pending',kind:'image',version:1,adopted:1,title:'未审核图',content:{url:'/pending'},source:'ai',review:'pending'}].map(r=>({...r,project_id:'p',created:'t',updated:'t'})) as RecordItem[];
function Harness({initial={}}:{initial?:any}){const [content,set]=useState(initial);return <><ImageDependencies id="self" records={records} content={content} onChange={set}/><output>{JSON.stringify(content)}</output></>;}
it('binds exact package versions and current reviewed actual images without editing JSON',()=>{
 render(<Harness/>);
 fireEvent.keyDown(screen.getByRole('combobox',{name:'生成依赖包'}),{key:'ArrowDown'});fireEvent.keyDown(screen.getByRole('combobox',{name:'生成依赖包'}),{key:'ArrowDown'});fireEvent.keyDown(screen.getByRole('combobox',{name:'生成依赖包'}),{key:'Enter'});fireEvent.click(screen.getByRole('button',{name:'添加生成依赖'}));
 expect(screen.getByRole('status').textContent).toContain('"generation_dependencies":[{"id":"p","version":3}]');
 expect(screen.queryByRole('option',{name:/未审核图/})).toBeNull();
 fireEvent.keyDown(screen.getByRole('combobox',{name:'已有前图'}),{key:'ArrowDown'});fireEvent.keyDown(screen.getByRole('combobox',{name:'已有前图'}),{key:'ArrowDown'});fireEvent.keyDown(screen.getByRole('combobox',{name:'已有前图'}),{key:'Enter'});fireEvent.click(screen.getByRole('button',{name:'添加已有前图'}));
 expect(screen.getByRole('status').textContent).toContain('"previous_image_dependencies":[{"id":"img","version":2}]');
 fireEvent.click(screen.getByRole('button',{name:'移除依赖 · 前格生图包'}));expect(screen.getByRole('status').textContent).toContain('"generation_dependencies":[]');
});
it('preserves stale or missing references and shows which needs rebinding',()=>{
 render(<Harness initial={{generation_dependencies:[{id:'p',version:1},{id:'gone',version:2}]}}/>);
 expect(screen.getByText(/当前已为v3/)).toBeTruthy();expect(screen.getByText(/记录不可见/)).toBeTruthy();
 expect(screen.getByRole('status').textContent).toContain('"version":1');
});

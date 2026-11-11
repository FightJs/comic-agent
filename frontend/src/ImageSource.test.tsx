// @vitest-environment jsdom
import {cleanup,render,screen} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {Images} from './Images';
import {api} from './api';
vi.mock('./api',async()=>({...await vi.importActual('./api'),api:vi.fn()}));
vi.mock('./AnnotationCanvas',()=>({AnnotationCanvas:()=>null}));
afterEach(()=>{cleanup();vi.resetAllMocks();localStorage.clear();});
it('identifies an adopted model image as AI instead of imported',async()=>{
 const r={id:'i',project_id:'p',kind:'image',title:'模型图',version:2,adopted:2,source:'ai',review:'pending',content:{episode:1,panel:1,batch:1,url:'/image.png',checked:false},created:'',updated:''};
 vi.mocked(api).mockImplementation(async path=>path.includes('?version=')?r:path.includes('/annotations')?{version:0,items:[]}:[]);
 render(<Images pid="p" records={[r]} batch={1} episode={1} panel={1} onSaved={()=>{}} refresh={async()=>{}} run={async()=>{}} onPanel={()=>{}} onLocation={()=>{}}/>);
 expect(await screen.findByText(/未检查.*AI生成\/修改/)).toBeTruthy();
 expect(screen.queryByText(/未检查.*人工导入/)).toBeNull();
});

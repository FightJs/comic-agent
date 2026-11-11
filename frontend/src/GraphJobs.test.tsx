// @vitest-environment jsdom

import {render,screen,cleanup} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {GraphJobs} from './GraphDocuments';
vi.mock('./api',()=>({base:()=>'/fixture',json:vi.fn(),api:vi.fn(async()=>[{id:'job',kind:'document',status:'succeeded',stage:'publish',completed:1,total:1,usage:{input_tokens:12,output_tokens:8,unknown:true}}])}));
afterEach(cleanup);
it('marks incomplete provider usage instead of implying a complete measured total',async()=>{
 render(<GraphJobs pid="fixture"/>);
 expect(await screen.findByText(/已记录用量：输入 12/)).toBeTruthy();
 expect(screen.getByText(/部分请求未返回用量，总量未知/)).toBeTruthy();
});

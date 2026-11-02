// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {downloadZip} from './api';
afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks();vi.unstubAllGlobals()});
it('ZIP download sends a JSON request that the local API accepts',async()=>{
 vi.spyOn(globalThis,'fetch').mockImplementation(async(_url,options)=>{
   if(new Headers(options?.headers).get('content-type')!=='application/json')return new Response('Unsupported request',{status:422});
   const {ids}=JSON.parse(options!.body as string);
   return new Response(ids.length===1?'PK-test':'invalid',{status:ids.length===1?200:422});
 });
 vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
 vi.useFakeTimers();
 const objectUrl=URL.createObjectURL, revoke=URL.revokeObjectURL;
 URL.createObjectURL=()=> 'blob:qa';URL.revokeObjectURL=()=>{};
 try{await expect(downloadZip('project',['image-one'])).resolves.toBeUndefined();await vi.runAllTimersAsync()}finally{URL.createObjectURL=objectUrl;URL.revokeObjectURL=revoke}
});

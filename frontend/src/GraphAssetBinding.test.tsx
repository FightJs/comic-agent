// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { GraphAssetBinding } from './GraphAssetBinding';
import { emptyGraph } from './graphTypes';
import type { RecordItem } from './api';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('blocks stale entity/state references even when the asset is approved',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(emptyGraph),{status:200})));
 const record={id:'asset',project_id:'p',kind:'asset',title:'旧参考',version:1,adopted:1,created:'2026-11-04',updated:'2026-11-04',review:'approved',source:'import',content:{entity_id:'removed',state_id:'old-state'}} as RecordItem;
 render(<GraphAssetBinding record={record} dirty={false} onSaved={()=>{}}/>);
 await screen.findByText('原关联身份或状态已变化，请重新选择当前图谱中的实体与状态。');
 expect((screen.getByText('确认采用并绑定图谱') as HTMLButtonElement).disabled).toBe(true);
});

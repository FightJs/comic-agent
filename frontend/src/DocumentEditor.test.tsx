// @vitest-environment jsdom
import {cleanup,render,screen,fireEvent} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {DocumentEditor} from './DocumentEditor';
import {api} from './api';
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:vi.fn()}));
HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
afterEach(()=>{cleanup();localStorage.clear();vi.clearAllMocks();});
it('loads a legacy text-only document into the actual editor without creating a blank save',async()=>{
 const record={id:'legacy',project_id:'p',kind:'skeleton',title:'旧骨架',version:1,source:'manual',content:{text:'旧骨架正文<script>\n第二段仍保留'}} as any;
 render(<DocumentEditor record={record} onSaved={vi.fn()}/>);
 const editor=await screen.findByRole('textbox',{name:'文档正文'});
 expect(editor.textContent).toContain('旧骨架正文<script>');
 expect(editor.textContent).toContain('第二段仍保留');
 expect(editor.querySelector('script')).toBeNull();
 expect(api).not.toHaveBeenCalled();
});

it('opens real Pi selection discussion instead of the old simulated direct replacement',async()=>{
 const record={id:'one',project_id:'p',kind:'skeleton',title:'骨架',version:1,source:'manual',content:{html:'<p>保留原稿</p>'}} as any;
 vi.mocked(api).mockResolvedValue([]);
 render(<DocumentEditor record={record} onSaved={vi.fn()}/>);
 await screen.findByRole('textbox',{name:'文档正文'});
 fireEvent.click(screen.getByRole('button',{name:'选段 AI 修改'}));
 expect(await screen.findByText(/请先在正文中选择文字/)).toBeTruthy();
 expect(screen.getByRole('button',{name:'发送给 Pi'}).hasAttribute('disabled')).toBe(true);
 expect(screen.queryByText('模拟修改并替换')).toBeNull();
});

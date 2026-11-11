// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { RangeGeneration } from './Workflow';
import { api } from './api';
vi.mock('./api', async importOriginal => ({...await importOriginal<typeof import('./api')>(), api:vi.fn(async () => null)}));
HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
afterEach(() => {cleanup(); localStorage.clear(); vi.clearAllMocks();});
it('opens the requested outline and retains unsaved input instead of generating from stale text', async () => {
 const records = ['a','b'].map(id => ({id,project_id:'p',kind:'outline',title:`细纲${id}`,version:1,content:{html:'<h3>第一话</h3><p>细纲正文</p>'}})) as any;
 render(<RangeGeneration pid="p" initialOutlineId="a" records={records} refresh={vi.fn()} onClose={vi.fn()} />);
 await waitFor(() => expect(api).toHaveBeenCalledWith('/projects/p/outline-index/a'));
 expect(screen.getByRole('combobox',{name:'细纲版本'}).textContent).toContain('细纲a');
 localStorage.setItem('comic-draft:p:a','{"content":{"html":"未保存输入"}}');
 fireEvent.click(screen.getByRole('button',{name:'生成第 1–1 话候选'}));
 await screen.findByText('骨架或所选细纲仍有未保存编辑，请保存成功后再生成脚本。');
 expect(vi.mocked(api).mock.calls.some(([url]) => url.endsWith('/production-jobs'))).toBe(false);
 expect(localStorage.getItem('comic-draft:p:a')).toContain('未保存输入');
});

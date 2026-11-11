// @vitest-environment jsdom
import {expect,it} from 'vitest';
import {documentHtml,documentText,withDocumentHtml} from './documentContent';
it('renders legacy text safely while preserving the authoritative HTML field',()=>{
 const html=documentHtml({text:'旧骨架<script>\n第二行'});
 expect(html).toBe('<p>旧骨架&lt;script&gt;</p><p>第二行</p>');
 expect(documentText({text:'旧骨架'})).toContain('旧骨架');
 expect(documentHtml({html:'<p>新正文</p>',text:'旧遮蔽字段'})).toBe('<p>新正文</p>');
 expect(documentHtml({html:'',text:'不应复活的旧文'})).toBe('<p></p>');
});
it('removes the legacy shadow text when editor content is actually changed',()=>{
 const next=withDocumentHtml({text:'旧文',generated_entries:[{episode:1}]},'<p>新稿</p>');
 expect(next.text).toBeUndefined();
 expect(next.html).toBe('<p>新稿</p>');
 expect(next.generated_entries).toHaveLength(1);
});

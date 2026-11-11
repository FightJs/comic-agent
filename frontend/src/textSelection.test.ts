// @vitest-environment jsdom
import {Editor} from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import {expect,it} from 'vitest';
import {captureTextSelection,selectionHtml} from './textSelection';
it('uses UTF-16 positions to replace the second identical quote and preserve outside marks',()=>{
 const editor=new Editor({extensions:[StarterKit],content:'<h2>开头😀</h2><p>重复<strong>文字</strong>，重复文字。</p>'});
 try{
  editor.commands.setTextSelection({from:12,to:16});
  const selected=captureTextSelection(editor);expect(selected).toEqual({start:9,end:13,text:'重复文字'});
  const html=selectionHtml(editor,selected!,'新的😀词');
  expect(html).toBe('<h2>开头😀</h2><p>重复<strong>文字</strong>，新的😀词。</p>');
  expect(editor.getHTML()).toContain('，重复文字。');
 }finally{editor.destroy();}
});
it('replaces a cross-paragraph selection while preserving outside list structure and never applies a stale quote',()=>{
 const editor=new Editor({extensions:[StarterKit],content:'<p>保留前文A</p><p>B保留后文</p><ul><li><p>尾部</p></li></ul>'});
 try{
  const selection={start:4,end:6,text:'AB'};
  expect(selectionHtml(editor,selection,'新')).toBe('<p>保留前文新保留后文</p><ul><li><p>尾部</p></li></ul>');
  expect(()=>selectionHtml(editor,{...selection,text:'错误'},'新')).toThrow('原文已变化');
 }finally{editor.destroy();}
});

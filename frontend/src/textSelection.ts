import type {Editor} from '@tiptap/react';
import {DOMSerializer} from '@tiptap/pm/model';
export type TextSelection={start:number;end:number;text:string};
export function captureTextSelection(editor:Editor):TextSelection|null{
 const {from,to}=editor.state.selection;
 const text=editor.state.doc.textBetween(from,to,'');
 if(!text)return null;
 const start=editor.state.doc.textBetween(0,from,'').length;
 return {start,end:start+text.length,text};
}
export function selectionHtml(editor:Editor,selection:TextSelection,replacement:string){
 let offset=0,from:number|undefined,to:number|undefined;
 editor.state.doc.descendants((node,pos)=>{
  if(!node.isText)return;
  const end=offset+(node.text?.length||0);
  if(from===undefined&&selection.start>=offset&&selection.start<end)from=pos+selection.start-offset;
  if(to===undefined&&selection.end>offset&&selection.end<=end)to=pos+selection.end-offset;
  offset=end;
 });
 if(from===undefined||to===undefined||editor.state.doc.textBetween(from,to,'')!==selection.text)throw Error('选段原文已变化，请重新选择正文讨论；候选仍保留。');
 const doc=editor.state.tr.insertText(replacement,from,to).doc;
 const area=document.createElement('div');
 area.append(DOMSerializer.fromSchema(editor.schema).serializeFragment(doc.content));
 return area.innerHTML;
}

/** Legacy text is a fallback only when HTML has never been stored. */
export function documentHtml(content:Record<string,any>){
 if(typeof content.html==='string')return content.html || '<p></p>';
 const escape=(text:string)=>text.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#x27;');
 return typeof content.text==='string'?content.text.split('\n').map(line=>'<p>'+escape(line)+'</p>').join(''):'<p></p>';
}
export function documentText(content:Record<string,any>){
 return new DOMParser().parseFromString(documentHtml(content).replace(/<\/(?:p|h[1-6]|li)>/g,'\n'),'text/html').body.textContent || '';
}
export function withDocumentHtml(content:Record<string,any>,html:string){
 const next:Record<string,any>={...content,html};delete next.text;return next;
}

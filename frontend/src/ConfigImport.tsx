import {useEffect,useRef,useState} from 'react';
import {api,json} from './api';
import {ErrorNote} from './ui';
import './config-import.css';
type Preview={token:string;name:string;profiles:{purpose:string;url:string;model:string;api?:string;secret_action:string}[]};
const purposes:Record<string,string>={text:'文本理解与编排',image:'生图与修改',vision:'看图检查',parse:'PDF解析'};
export function ConfigImport({onApplied,disabled=false,onWorking}:{onApplied:()=>void|Promise<void>;disabled?:boolean;onWorking?:(busy:boolean)=>void}){
  const [preview,setPreview]=useState<Preview|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[success,setSuccess]=useState('');
  const token=useRef(''),mounted=useRef(true);
  const discard=()=>{if(token.current){void api('/config-packages/discard',json('POST',{token:token.current})).catch(()=>{});token.current='';}};
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;discard();};},[]);
  async function upload(file:File){
    if(disabled||busy)return;onWorking?.(true);
    discard();setPreview(null);setError('');setSuccess('');setBusy(true);
    try{
      const value=await api<Preview>('/config-packages/preview',{method:'POST',body:file});
      if(!mounted.current){void api('/config-packages/discard',json('POST',{token:value.token})).catch(()=>{});return;}
      token.current=value.token;setPreview(value);
    }catch(e){if(mounted.current)setError((e as Error).message);}finally{onWorking?.(false);if(mounted.current)setBusy(false);}
  }
  async function apply(){
    if(!preview||busy||disabled)return;onWorking?.(true);setBusy(true);setError('');
    try{
      await api('/config-packages/apply',json('POST',{token:preview.token}));
      if(!mounted.current)return;
      discard();setPreview(null);setSuccess('配置已应用 · 连接未验证');await onApplied();
    }catch(e){if(mounted.current)setError((e as Error).message);}finally{onWorking?.(false);if(mounted.current)setBusy(false);}
  }
  return <section className="config-import" aria-label="导入配置包">
    <h3>导入配置包</h3><p>提供配置包后自动填入对应模型，并把包内密钥存入钥匙串，无需逐项填写。先核对用途和服务地址，再应用。</p>
    <label className="config-file">选择配置包<input type="file" accept=".json,application/json" disabled={busy||disabled} onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void upload(file);}}/></label>
    <small>JSON · comic-config/v1 · 最多1MB。配置包在服务内存中临时预览，10分钟后失效；关闭设置将丢弃预览。</small>
    {busy&&<p role="status">正在处理配置包…</p>}
    {preview&&<div className="config-preview"><h4>{preview.name}</h4><dl>{preview.profiles.map(p=><div key={p.purpose}><dt>{purposes[p.purpose]||p.purpose}</dt><dd><strong>{p.model}</strong><span>{p.url}</span>{p.api&&<span>接口协议：{p.api}</span>}<span>{p.secret_action==='replace'?'密钥：将存入钥匙串并替换该用途密钥':'密钥：保留当前已存密钥'}</span></dd></div>)}</dl><p>仅更新以上用途，连接仍需实际验证。当前配置如有变化，系统会要求重新预览。</p><div className="actions"><button type="button" disabled={busy||disabled} onClick={()=>{discard();setPreview(null);setError('');}}>丢弃预览</button><button type="button" className="primary" disabled={busy||disabled} onClick={()=>void apply()}>应用这份配置</button></div></div>}
    <ErrorNote message={error}/>{success&&<p className="success" role="status">{success}</p>}
    <details><summary>配置包内容说明</summary><p>支持文本、生图、看图、PDF解析用途；脚本和skill资源包将由独立安装入口处理，不执行上传文件中的代码。</p><pre>{`{"format":"comic-config/v1","name":"创作配置","profiles":[{"purpose":"text","url":"https://供应商地址/v1","model":"实际模型标识","secret":"API密钥"}]}`}</pre></details>
  </section>;
}

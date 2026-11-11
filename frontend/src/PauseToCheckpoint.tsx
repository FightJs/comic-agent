import {useEffect,useRef,useState} from 'react';
import {api,json} from './api';
import {ErrorNote} from './ui';
import './pause-control.css';
export function PauseToCheckpoint({endpoint,requested,focusId,fallbackId,onChanged}:{endpoint:string;requested:boolean;focusId:string;fallbackId?:string;onChanged:()=>Promise<void>|void}){
 const [busy,setBusy]=useState(false),[accepted,setAccepted]=useState(false),[error,setError]=useState('');
 const alive=useRef(true),clicked=useRef(false),area=useRef<HTMLDivElement>(null);
 useEffect(()=>{alive.current=true;const node=area.current;return()=>{
  alive.current=false;
  if(clicked.current&&(document.activeElement===document.body||node?.contains(document.activeElement)))requestAnimationFrame(()=>{
   const target=document.getElementById(focusId);
   const control=target?.querySelector<HTMLElement>('input,button');
   (control||target||(fallbackId?document.getElementById(fallbackId):null))?.focus();
  });
 };},[endpoint,focusId,fallbackId]);
 async function pause(){
  if(busy||requested||accepted)return;clicked.current=true;setBusy(true);setError('');
  try{await api(endpoint,json('POST',{}));if(!alive.current)return;setAccepted(true);await onChanged();}
  catch(e){if(alive.current){setError((e as Error).message);try{await onChanged();}catch{}}}
  finally{if(alive.current)setBusy(false);}
 }
 const waiting=requested||accepted;
 return <div className="pause-control" ref={area}>
  <button type="button" disabled={busy||waiting} onClick={()=>void pause()}>{waiting?'正在暂停，等待收尾':busy?'正在请求暂停…':'暂停到检查点'}</button>
  {waiting&&<p className="notice" role="status">暂停请求已保存，不表示已经暂停；停止新派发，等待已提交调用收尾。若已自然完成，将保留完整结果。</p>}
  <ErrorNote message={error}/>
 </div>;
}

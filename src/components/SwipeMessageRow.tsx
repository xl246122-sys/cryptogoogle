import React, { useRef, useState } from 'react';

/** A horizontal gesture reveals an explicit action; vertical gestures scroll normally. */
export function SwipeMessageRow({children,onDelete}:{children:React.ReactNode;onDelete:()=>void}) {
  const [offset,setOffset]=useState(0);
  const gesture=useRef<{x:number;y:number;start:number;axis?:'x'|'y';moved:boolean}|null>(null);
  const suppress=useRef(false);
  return <div className="relative overflow-hidden rounded-xl" style={{touchAction:'pan-y'}}
    onPointerDown={e=>{if(e.button!==0)return;suppress.current=false;gesture.current={x:e.clientX,y:e.clientY,start:offset,moved:false};}}
    onPointerMove={e=>{
      const g=gesture.current;if(!g)return;
      const dx=e.clientX-g.x,dy=e.clientY-g.y;
      if(!g.axis && Math.max(Math.abs(dx),Math.abs(dy))>10) g.axis=Math.abs(dx)>Math.abs(dy)*1.3?'x':'y';
      if(g.axis==='x') {g.moved=true;suppress.current=true;setOffset(Math.max(-80,Math.min(0,g.start+dx)));e.currentTarget.setPointerCapture(e.pointerId);}
    }}
    onPointerUp={()=>{const g=gesture.current;if(g?.axis==='x')setOffset(offset<=-40?-80:0);gesture.current=null;}}
    onPointerCancel={()=>{setOffset(0);gesture.current=null;}}
    onClickCapture={e=>{
      if(suppress.current){e.preventDefault();e.stopPropagation();suppress.current=false;return;}
      if(offset<0 && !(e.target as HTMLElement).closest('[data-delete-message]')){e.stopPropagation();setOffset(0);}
    }}>
    <button data-delete-message type="button" aria-label="删除消息" tabIndex={offset<0?0:-1}
      className="absolute right-0 inset-y-0 w-20 bg-red-600 text-white text-sm font-semibold"
      onClick={e=>{e.stopPropagation();if(offset<0)onDelete();}}>删除</button>
    <div className="relative transition-transform duration-150" style={{transform:`translateX(${offset}px)`}}>{children}</div>
  </div>;
}

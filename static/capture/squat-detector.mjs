// Fixed-angle detector used by the original local capture UI.
export const DOWN_ANGLE=120;
export const UP_ANGLE=155;
export function kneeAngle(hip,knee,ankle,width,height){
  const ax=(hip.x-knee.x)*width,ay=(hip.y-knee.y)*height,bx=(ankle.x-knee.x)*width,by=(ankle.y-knee.y)*height;
  const magnitude=Math.hypot(ax,ay)*Math.hypot(bx,by);
  return magnitude>0?Math.acos(Math.max(-1,Math.min(1,(ax*bx+ay*by)/magnitude)))*180/Math.PI:null;
}
export class SquatDetector{
  constructor(){this.fixedAngleMode=true;this.clearCalibration();}
  get calibrated(){return true;} get calibrating(){return false;}
  clearCalibration(){this.side=null;this.stage='ready';this.reset();}
  startCalibration(){this.reset();}
  reset(){this.angle=null;this.lastTime=null;this.phase='calibrating';this.candidate=null;this.since=0;this.cooldownUntil=0;}
  output(rep=false,candidate=null){
    const angle=this.angle,progress=Number.isFinite(angle)?Math.max(0,Math.min(1,(UP_ANGLE-angle)/(UP_ANGLE-DOWN_ANGLE))):0;
    let label='Pose lost',message='Show both shoulders and one full leg.';
    if(Number.isFinite(angle)){
      if(candidate==='down'){label=this.phase==='down'?'DOWN ✓':'Confirming depth';message='Depth is valid. Hold briefly, then stand up.';}
      else if(candidate==='up'){label=this.phase==='up'?'STAND ✓':'Confirming stand';message=this.phase==='down'?'Hold your standing position briefly.':'Ready: stand → squat → stand.';}
      else if(this.phase==='down'){label='Stand up';message=`Stand ${Math.max(0,Math.ceil(UP_ANGLE-angle))}° taller to finish the rep.`;}
      else{label=this.phase==='calibrating'?'Stand first':'Go lower';message=`Squat ${Math.max(0,Math.ceil(angle-DOWN_ANGLE))}° lower to reach valid depth.`;}
    }
    return{rep,angle,phase:this.phase,candidate,stage:'ready',calibrated:true,progress,label,message,
      metrics:{side:this.side===0?'left':this.side===1?'right':null,standingAngle:UP_ANGLE,squatAngle:DOWN_ANGLE,
        angleRange:35,hipDrop:null,calibratedHipDrop:null,score:progress,signal:'angle',downScore:1,upScore:0}};
  }
  update(points,width,height,now){
    const visible=p=>p&&Number.isFinite(p.x)&&Number.isFinite(p.y)&&p.x>=0&&p.x<=1&&p.y>=0&&p.y<=1&&(p.visibility??0)>=0.6;
    const legs=[[23,25,27],[24,26,28]],valid=legs.map(ids=>ids.every(i=>visible(points?.[i])));
    if(!points||!visible(points[11])||!visible(points[12])||!valid.some(Boolean)||!(width>0&&height>0)){this.reset();return this.output();}
    if(this.lastTime!==null&&(now-this.lastTime>700||now<this.lastTime))this.reset();
    if(this.side!==null&&!valid[this.side])this.reset();
    if(this.side===null)this.side=valid[0]&&(!valid[1]||legs[0].reduce((s,i)=>s+points[i].visibility,0)>=legs[1].reduce((s,i)=>s+points[i].visibility,0))?0:1;
    const [h,k,a]=legs[this.side].map(i=>points[i]),raw=kneeAngle(h,k,a,width,height);
    if(raw===null){this.reset();return this.output();}
    const dt=this.lastTime===null?0:now-this.lastTime;
    this.angle=this.angle===null?raw:this.angle+(raw-this.angle)*(1-Math.exp(-dt/80));this.lastTime=now;
    const candidate=this.angle>=UP_ANGLE?'up':this.angle<=DOWN_ANGLE?'down':null;
    if(candidate!==this.candidate){this.candidate=candidate;this.since=now;}
    let rep=false;
    if(candidate&&now-this.since>=180){
      if(candidate==='up'){if(this.phase==='down'&&now>=this.cooldownUntil){rep=true;this.cooldownUntil=now+400;}this.phase='up';}
      else if(this.phase==='up'&&now>=this.cooldownUntil)this.phase='down';
    }
    return this.output(rep,candidate);
  }
}

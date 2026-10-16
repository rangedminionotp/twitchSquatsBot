// Pure, camera-independent detector. Angles use pixel-scaled 2D coordinates.
export function kneeAngle(hip, knee, ankle, width, height) {
  const ax=(hip.x-knee.x)*width, ay=(hip.y-knee.y)*height;
  const bx=(ankle.x-knee.x)*width, by=(ankle.y-knee.y)*height;
  const magnitude=Math.hypot(ax,ay)*Math.hypot(bx,by);
  return magnitude > 0 ? Math.acos(Math.max(-1,Math.min(1,(ax*bx+ay*by)/magnitude)))*180/Math.PI : null;
}

export class SquatDetector {
  constructor() { this.reset(); }
  reset() {
    this.side=null; this.angle=null; this.lastTime=null;
    this.phase='calibrating'; this.candidate=null; this.since=0;
    this.cooldownUntil=0;
  }
  update(points, width, height, now) {
    const visible=p=>p && Number.isFinite(p.x) && Number.isFinite(p.y) &&
      p.x>=0 && p.x<=1 && p.y>=0 && p.y<=1 && (p.visibility ?? 0)>=0.6;
    const legs=[[23,25,27],[24,26,28]];
    const valid=legs.map(ids=>ids.every(i=>visible(points?.[i])));
    if (!points || !visible(points[11]) || !visible(points[12]) || !valid.some(Boolean) || !(width>0 && height>0)) {
      this.reset(); return {rep:false,angle:null,phase:'lost'};
    }
    if (this.lastTime!==null && (now-this.lastTime>700 || now<this.lastTime)) this.reset();
    // Keep the same leg while it is reliable. Switching requires a fresh stand.
    if (this.side!==null && !valid[this.side]) this.reset();
    if (this.side===null) this.side=valid[0] && (!valid[1] ||
      legs[0].reduce((s,i)=>s+points[i].visibility,0)>=legs[1].reduce((s,i)=>s+points[i].visibility,0)) ? 0 : 1;
    const [h,k,a]=legs[this.side].map(i=>points[i]);
    const raw=kneeAngle(h,k,a,width,height);
    if (raw===null) { this.reset(); return {rep:false,angle:null,phase:'lost'}; }
    const dt=this.lastTime===null ? 0 : now-this.lastTime;
    this.angle=this.angle===null ? raw : this.angle+(raw-this.angle)*(1-Math.exp(-dt/80));
    this.lastTime=now;
    const candidate=this.angle>=155 ? 'up' : this.angle<=120 ? 'down' : null;
    if (candidate!==this.candidate) { this.candidate=candidate; this.since=now; }
    let rep=false;
    if (candidate && now-this.since>=180) {
      if (candidate==='up') {
        if (this.phase==='down' && now>=this.cooldownUntil) { rep=true; this.cooldownUntil=now+400; }
        this.phase='up';
      } else if (this.phase==='up' && now>=this.cooldownUntil) this.phase='down';
    }
    return {rep,angle:this.angle,phase:this.phase,candidate};
  }
}

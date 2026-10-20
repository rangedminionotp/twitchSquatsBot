import assert from 'node:assert/strict';
import {SquatDetector,kneeAngle,DOWN_ANGLE,UP_ANGLE} from '../../static/capture/squat-detector.mjs';
function pose(angle,width=1280,height=720){
  const p=Array.from({length:33},()=>({x:.5,y:.3,visibility:.9}));
  for(const[hip,knee,ankle]of[[23,25,27],[24,26,28]]){
    p[knee]={x:.5,y:.6,visibility:.9};p[hip]={x:.5,y:.6-100/height,visibility:.9};
    p[ankle]={x:.5+Math.sin(angle*Math.PI/180)*100/width,y:.6-Math.cos(angle*Math.PI/180)*100/height,visibility:.9};
  }return p;
}
assert.equal(DOWN_ANGLE,120);assert.equal(UP_ANGLE,155);
for(const[w,h]of[[1280,720],[720,1280],[640,480]])assert.ok(Math.abs(kneeAngle(pose(110,w,h)[23],pose(110,w,h)[25],pose(110,w,h)[27],w,h)-110)<1e-8);
for(const fps of[10,15,30,60]){
  const detector=new SquatDetector();let time=0,reps=0,last;
  const hold=(angle,ms=900)=>{for(let i=0;i<Math.ceil(ms*fps/1000);i++){time+=1000/fps;last=detector.update(pose(angle),1280,720,time);reps+=Number(last.rep);}return last;};
  hold(100);hold(170);assert.equal(reps,0,'Starting crouched cannot count');
  const midway=hold(140);assert.match(midway.message,/\d+°/,'Midpoint reports degrees remaining');
  hold(100);hold(170);assert.equal(reps,1,`One rep at ${fps} FPS`);
  hold(170);assert.equal(reps,1,'Standing cannot repeat');
  hold(100);detector.update(null,1280,720,time+1);hold(170);assert.equal(reps,1,'Occlusion cancels rep');
  hold(100);time+=1000;hold(170);assert.equal(reps,1,'Frame gap cancels rep');
  hold(100);hold(170);assert.equal(reps,2,'Recovers after interruption');
}
console.log('Original fixed-angle detector passed at 10–60 FPS with live degree guidance.');

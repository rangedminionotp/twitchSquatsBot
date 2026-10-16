import assert from 'node:assert/strict';
import {SquatDetector,kneeAngle} from '../../static/capture/squat-detector.mjs';
function pose(angle,width=1280,height=720) {
  const p=Array.from({length:33},()=>({x:0.5,y:0.3,visibility:0.9}));
  for(const [hip,knee,ankle] of [[23,25,27],[24,26,28]]) {
    p[knee]={x:0.5,y:0.6,visibility:0.9};
    p[hip]={x:0.5,y:0.6-100/height,visibility:0.9};
    p[ankle]={x:0.5+Math.sin(angle*Math.PI/180)*100/width,y:0.6-Math.cos(angle*Math.PI/180)*100/height,visibility:0.9};
  }
  return p;
}
for(const [w,h] of [[1280,720],[720,1280],[640,480]]) {
  const p=pose(110,w,h); assert.ok(Math.abs(kneeAngle(p[23],p[25],p[27],w,h)-110)<1e-8);
}
for(const fps of [10,15,30,60]) {
  const detector=new SquatDetector(); let time=0,reps=0;
  function hold(angle,ms=900) { for(let i=0;i<Math.ceil(ms*fps/1000);i++){time+=1000/fps;reps+=Number(detector.update(pose(angle),1280,720,time).rep);} }
  hold(100);hold(170);assert.equal(reps,0,'Starting crouched cannot count');
  hold(100);hold(170);assert.equal(reps,1,`One rep at ${fps} FPS`);
  hold(170);assert.equal(reps,1,'Standing cannot repeat');
  hold(100);detector.update(null,1280,720,time+1);hold(170);assert.equal(reps,1,'Occlusion cancels rep');
  hold(100);time+=1000;hold(170);assert.equal(reps,1,'Frame gap cancels rep');
  hold(100);hold(170);assert.equal(reps,2,'Recovers after interruption');
}
const d=new SquatDetector();
for(let t=0;t<=500;t+=50)d.update(pose(170),1280,720,t);
let p=pose(110);p[24].visibility=p[26].visibility=p[28].visibility=0.99;
d.update(p,1280,720,550);assert.equal(d.side,0,'Confidence fluctuation does not switch legs');
p[23].visibility=0.1;
assert.equal(d.update(p,1280,720,600).phase,'calibrating','Lost selected leg requires stand');
console.log('Squat detector passed: aspect ratios, 10–60 FPS, initial stand, interruption, recovery and stable leg selection.');

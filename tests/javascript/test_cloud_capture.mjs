import assert from 'node:assert/strict';
import {Outbox, SquatDetector, kneeAngle} from '../../static/cloud/capture-core.mjs';
class Storage {
  data=new Map();
  get length(){return this.data.size;}
  key(i){return [...this.data.keys()][i];}
  getItem(k){return this.data.get(k)??null;}
  setItem(k,v){this.data.set(k,v);}
  removeItem(k){this.data.delete(k);}
}
const storage=new Storage(), a=new Outbox(storage,'11'), b=new Outbox(storage,'22');
const report={run_id:'run-a',lease:'lease-a',count:4};
a.save(report);
assert.deepEqual(b.entries(),[]);
assert.equal(new Outbox(storage,'11').entries()[0].count,4);
a.acknowledge(report,3); assert.equal(a.entries().length,1);
a.save({...report,count:5}); a.acknowledge(report,4); assert.equal(a.entries()[0].count,5);
a.acknowledge({...report,count:5},5); assert.equal(a.entries().length,0);
a.save(report); a.save({...report,lease:'lease-b'}); a.acknowledge(report,4); assert.equal(a.entries().length,1);
a.discard(a.entries()[0]); assert.equal(a.entries().length,0);
storage.setItem('sc-cloud-reps-v1:22:broken','invalid'); assert.deepEqual(a.entries(),[]);
assert.throws(()=>b.entries());
assert.throws(()=>new Outbox({setItem(){throw Error('quota');}},'11').save(report));
assert.throws(()=>a.save({...report,count:1.2}));

const detector=new SquatDetector(); let now=100, reps=0;
function hold(angle, frames=4) { for(let i=0;i<frames;i++) {now+=80; reps+=Number(detector.update(angle,now));} }
hold(100); hold(170); assert.equal(reps,0,'Must stand before the first squat');
hold(100); hold(170); assert.equal(reps,1);
hold(170,10); assert.equal(reps,1,'Standing is not repeated reps');
hold(100,1); hold(170); assert.equal(reps,1,'Reject depth jitter');
hold(100); hold(null); hold(170); assert.equal(reps,1,'Pose loss disarms the rep');
hold(100); now+=1000; hold(170); assert.equal(reps,1,'Long frame gap disarms the rep');
hold(100); hold(170); assert.equal(reps,2);
const points=Array.from({length:33},()=>({x:.5,y:.5,visibility:.9}));
points[23]={x:.5,y:.2,visibility:.9}; points[25]={x:.5,y:.5,visibility:.9}; points[27]={x:.5,y:.8,visibility:.9};
assert.equal(kneeAngle(points,1280,720),180);
points[27].visibility=0; points[28].visibility=0; assert.equal(kneeAngle(points),null);
points[27].visibility=.9; points[11].visibility=0; assert.equal(kneeAngle(points),null);
assert.equal(kneeAngle(null),null);
console.log('Cloud capture core passed: account isolation, durable recovery, acknowledgment races, storage errors and squat state machine.');

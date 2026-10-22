import assert from 'node:assert/strict';
import {ViewerSquatDetector} from '../../static/cloud/viewer-core.mjs';

const detector = new ViewerSquatDetector();
let now = 1000;
function hold(angle, duration, step=100) {
  const results = [];
  for (let elapsed=0; elapsed<=duration; elapsed+=step) {
    now += step;
    results.push(detector.update(angle,now));
  }
  return results;
}

detector.beginCalibration(now);
assert.equal(hold(125,900).at(-1).stage,'standing','Bent posture cannot calibrate as standing');
assert.equal(hold(168,800).at(-1).stage,'squat');
assert.equal(hold(140,300).at(-1).stage,'squat','Partial depth is not enough');
assert.equal(hold(96,800).at(-1).stage,'return');
let result = hold(167,600).find(value=>value.calibrated);
assert.equal(result.stage,'ready');
assert.equal(result.calibrated,true);
assert.equal(result.standing_angle,168);
assert.equal(result.squat_angle,96);
assert.ok(result.duration_ms >= 2500);

let reps = 0;
function track(angle, duration=300) {
  const values = hold(angle,duration);
  reps += values.filter(value=>value.rep).length;
  return values.at(-1);
}
track(168); track(96); track(168);
assert.equal(reps,1);
track(168,1000);
assert.equal(reps,1,'Standing still never creates repetitions');
track(125); track(168);
assert.equal(reps,1,'A shallow squat does not count');
track(96,100); track(168);
assert.equal(reps,1,'Depth jitter does not count');
track(96); detector.update(null,now+=100); track(168);
assert.equal(reps,1,'Pose loss disarms an unfinished repetition');
track(96); now += 1200; track(168);
assert.equal(reps,1,'A long frame gap disarms an unfinished repetition');
track(96); track(168);
assert.equal(reps,2);

const incomplete = new ViewerSquatDetector();
incomplete.beginCalibration(0);
assert.equal(incomplete.update(null,100).calibrated,false);
assert.throws(()=>incomplete.update(170,Number.NaN));

console.log('Viewer detector passed: personal calibration, full-range reps, jitter, pose loss and frame gaps.');

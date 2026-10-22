const labels = {
  idle: 'Ready to calibrate',
  standing: 'Stand tall and hold still',
  squat: 'Squat to a comfortable depth and hold',
  return: 'Stand tall again',
  ready: 'Calibration complete',
  tracking: 'Tracking your squats'
};

function whole(value) { return Math.round(value); }

export class ViewerSquatDetector {
  constructor() { this.reset(); }

  reset() {
    this.stage = 'idle';
    this.last = 0;
    this.calibrationStarted = 0;
    this.stableSince = 0;
    this.samples = [];
    this.minimum = Infinity;
    this.standingAngle = null;
    this.squatAngle = null;
    this.phase = 'need_up';
    this.pose = '';
    this.poseSince = 0;
  }

  beginCalibration(now=0) {
    this.reset();
    this.stage = 'standing';
    this.calibrationStarted = now;
    return this.snapshot(false, now);
  }

  clearStability(now, angle=null) {
    this.stableSince = now;
    this.samples = Number.isFinite(angle) ? [angle] : [];
  }

  stable(angle, now, milliseconds, tolerance) {
    if (!this.samples.length) this.clearStability(now, angle);
    this.samples.push(angle);
    const low = Math.min(...this.samples), high = Math.max(...this.samples);
    if (high - low > tolerance) {
      this.clearStability(now, angle);
      return false;
    }
    return now - this.stableSince >= milliseconds;
  }

  snapshot(rep=false, now=this.last, calibrated=false) {
    const calibrationProgress = this.stage === 'standing' ? .2 : this.stage === 'squat' ? .55 :
      this.stage === 'return' ? .82 : ['ready','tracking'].includes(this.stage) ? 1 : 0;
    return {
      stage: this.stage,
      label: labels[this.stage],
      calibrated,
      rep,
      calibration_progress: calibrationProgress,
      standing_angle: this.standingAngle == null ? null : whole(this.standingAngle),
      squat_angle: this.squatAngle == null ? null : whole(this.squatAngle),
      duration_ms: this.calibrationStarted ? Math.max(0, whole(now - this.calibrationStarted)) : 0
    };
  }

  update(angle, now) {
    if (!Number.isFinite(now)) throw Error('A monotonic timestamp is required');
    if (!Number.isFinite(angle)) {
      this.last = now;
      this.clearStability(now);
      this.pose = '';
      this.phase = 'need_up';
      return this.snapshot(false, now);
    }
    if (this.last && now - this.last > 900) {
      this.clearStability(now, angle);
      this.pose = '';
      this.phase = 'need_up';
    }
    this.last = now;

    if (this.stage === 'standing') {
      if (angle < 135) {
        this.clearStability(now);
      } else if (this.stable(angle, now, 700, 8)) {
        this.standingAngle = this.samples.reduce((sum,value)=>sum+value,0) / this.samples.length;
        this.stage = 'squat';
        this.minimum = angle;
        this.clearStability(now);
      }
      return this.snapshot(false, now);
    }

    if (this.stage === 'squat') {
      if (angle < this.minimum - 2) {
        this.minimum = angle;
        this.clearStability(now, angle);
      } else if (angle <= this.minimum + 6 && this.standingAngle - this.minimum >= 25 &&
                 this.stable(angle, now, 650, 8)) {
        this.squatAngle = this.minimum;
        this.stage = 'return';
        this.clearStability(now);
      }
      return this.snapshot(false, now);
    }

    if (this.stage === 'return') {
      if (angle >= this.standingAngle - 10) {
        if (this.stable(angle, now, 500, 8) && now - this.calibrationStarted >= 2500) {
          this.stage = 'ready';
          this.phase = 'need_up';
          this.pose = '';
          this.poseSince = now;
          return this.snapshot(false, now, true);
        }
      } else {
        this.clearStability(now);
      }
      return this.snapshot(false, now);
    }

    if (this.stage === 'idle') return this.snapshot(false, now);
    if (this.stage === 'ready') this.stage = 'tracking';
    const upThreshold = this.standingAngle - 10;
    const downThreshold = this.squatAngle + 7;
    const nextPose = angle >= upThreshold ? 'up' : angle <= downThreshold ? 'down' : 'middle';
    if (nextPose !== this.pose) {
      this.pose = nextPose;
      this.poseSince = now;
    }
    if (now - this.poseSince < 180) return this.snapshot(false, now);
    if (this.phase === 'need_up' && nextPose === 'up') this.phase = 'need_down';
    else if (this.phase === 'need_down' && nextPose === 'down') this.phase = 'need_return';
    else if (this.phase === 'need_return' && nextPose === 'up') {
      this.phase = 'need_down';
      return this.snapshot(true, now);
    }
    return this.snapshot(false, now);
  }
}

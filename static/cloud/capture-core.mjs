// Durable outbox: write before reporting; isolate by authenticated account/run.
export class Outbox {
  constructor(storage, uid) { this.storage = storage; this.uid = uid; this.prefix = `sc-cloud-reps-v1:${uid}:`; }
  save(report) {
    if (!report.run_id || !report.lease || !Number.isInteger(report.count) || report.count < 0) throw Error('Invalid saved progress');
    const item = {...report, uid:this.uid};
    this.storage.setItem(this.prefix + report.run_id, JSON.stringify(item));
    return item;
  }
  entries() {
    const result = [];
    for (let i=0; i<this.storage.length; i++) {
      const key = this.storage.key(i);
      if (!key.startsWith(this.prefix)) continue;
      const item = JSON.parse(this.storage.getItem(key));
      if (item.uid !== this.uid || key !== this.prefix+item.run_id || !item.lease || !Number.isInteger(item.count) || item.count<0) throw Error('Saved progress is invalid. Do not clear site data.');
      result.push(item);
    }
    return result;
  }
  acknowledge(report, accepted) {
    const key = this.prefix + report.run_id;
    const item = JSON.parse(this.storage.getItem(key) || 'null');
    if (item && item.lease === report.lease && item.count === report.count && accepted >= item.count) this.storage.removeItem(key);
  }
  discard(report) { this.acknowledge(report, report.count); }
}

// Time-based stability, not frame rate; full stand -> down -> stand is one rep.
export class SquatDetector {
  constructor() { this.reset(); }
  reset() { this.phase='stand'; this.candidate=''; this.since=0; this.last=0; }
  update(angle, now) {
    if (!Number.isFinite(angle)) { this.reset(); return false; }
    if (this.last && now-this.last>700) this.reset();
    this.last=now;
    const pose = angle>=155 ? 'up' : angle<=120 ? 'down' : 'middle';
    if (pose !== this.candidate) { this.candidate=pose; this.since=now; }
    if (now-this.since<180) return false;
    if (this.phase==='stand' && pose==='up') this.phase='down';
    else if (this.phase==='down' && pose==='down') this.phase='up';
    else if (this.phase==='up' && pose==='up') { this.phase='down'; return true; }
    return false;
  }
}

export function kneeAngle(points, width=1, height=1) {
  const visible = p => p && Number.isFinite(p.x) && Number.isFinite(p.y) && p.x>=0 && p.x<=1 && p.y>=0 && p.y<=1 && (p.visibility ?? 0)>.6;
  if (!points || !visible(points[11]) || !visible(points[12])) return null;
  const legs = [[23,25,27],[24,26,28]].map(ids=>ids.map(i=>points[i])).filter(leg=>leg.every(visible));
  legs.sort((a,b)=>Math.min(...b.map(p=>p.visibility))-Math.min(...a.map(p=>p.visibility)));
  if (!legs.length) return null;
  const [hip,knee,ankle] = legs[0];
  const a = [(hip.x-knee.x)*width,(hip.y-knee.y)*height], b = [(ankle.x-knee.x)*width,(ankle.y-knee.y)*height];
  const size = Math.hypot(...a)*Math.hypot(...b);
  return size ? Math.acos(Math.max(-1,Math.min(1,(a[0]*b[0]+a[1]*b[1])/size)))*180/Math.PI : null;
}

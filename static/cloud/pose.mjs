// Pinned loader and model. Downloads assets; never sends camera images to a server.
const base = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.22-rc.20250304';
export async function loadPose() {
  const {FilesetResolver, PoseLandmarker} = await import(`${base}/vision_bundle.mjs`);
  const files = await FilesetResolver.forVisionTasks(`${base}/wasm`);
  return PoseLandmarker.createFromOptions(files, {
    baseOptions: {modelAssetPath:'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task', delegate:'CPU'},
    runningMode:'VIDEO', numPoses:1, minPoseDetectionConfidence:.6, minPosePresenceConfidence:.6, minTrackingConfidence:.6
  });
}

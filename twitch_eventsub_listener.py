import hashlib
import hmac
import json
import os
import shlex
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8080"))
CALLBACK_PATH = os.environ.get("TWITCH_CALLBACK_PATH", "/eventsub")
POPUP_PATH = os.environ.get("TWITCH_POPUP_PATH", "/squat-popup")
POPUP_EVENTS_PATH = os.environ.get("TWITCH_POPUP_EVENTS_PATH", "/popup-events")
EVENTSUB_SECRET = os.environ.get("TWITCH_EVENTSUB_SECRET", "")
BROADCASTER_LOGIN = "nannersowo"
TARGET_REWARD_TITLE = os.environ.get("TARGET_REWARD_TITLE", "Hydrate")
TARGET_REWARD_ID = os.environ.get("TARGET_REWARD_ID")
MAX_MESSAGE_AGE_SECONDS = 600
AUTO_OPEN_POPUP = os.environ.get("AUTO_OPEN_POPUP", "1") == "1"
POPUP_OPEN_URL = os.environ.get("POPUP_OPEN_URL", f"http://127.0.0.1:{PORT}{POPUP_PATH}")
DEFAULT_SQUAT_TARGET = int(os.environ.get("DEFAULT_SQUAT_TARGET", "10"))
POPUP_VERSION = "2026-06-21-debug-3"
RIOT_CHECK_ENABLED = os.environ.get("RIOT_CHECK_ENABLED", "1") == "1"
RIOT_CHECK_COMMAND = os.environ.get("RIOT_CHECK_COMMAND", "python3 script.py")

MESSAGE_ID_HEADER = "Twitch-Eventsub-Message-Id"
MESSAGE_TIMESTAMP_HEADER = "Twitch-Eventsub-Message-Timestamp"
MESSAGE_SIGNATURE_HEADER = "Twitch-Eventsub-Message-Signature"
MESSAGE_TYPE_HEADER = "Twitch-Eventsub-Message-Type"
HMAC_PREFIX = "sha256="
POPUP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Twitch Squat Popup</title>
  <style>
    :root {
      --bg: #0d1016;
      --panel: rgba(18, 23, 34, 0.88);
      --accent: #66f0c9;
      --accent-2: #ffb347;
      --text: #f4f7fb;
      --muted: #95a5c2;
      --danger: #ff7a90;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-rounded, "SF Pro Rounded", "Avenir Next", "Trebuchet MS", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(102, 240, 201, 0.18), transparent 35%),
        radial-gradient(circle at top right, rgba(255, 179, 71, 0.16), transparent 30%),
        linear-gradient(160deg, #0d1016 0%, #121a27 60%, #0a0d14 100%);
      color: var(--text);
      min-height: 100vh;
      overflow: hidden;
    }
    .shell {
      display: grid;
      grid-template-columns: 1.6fr 1fr;
      min-height: 100vh;
      gap: 20px;
      padding: 24px;
    }
    .stage, .panel {
      background: var(--panel);
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 24px;
      box-shadow: 0 24px 80px rgba(0, 0, 0, 0.35);
      backdrop-filter: blur(14px);
    }
    .stage {
      position: relative;
      overflow: hidden;
      min-height: 70vh;
    }
    video, canvas {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      transform: scaleX(-1);
    }
    .overlay {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      pointer-events: none;
      padding: 24px;
      background: linear-gradient(to bottom, rgba(0, 0, 0, 0.36), transparent 24%, transparent 76%, rgba(0, 0, 0, 0.5));
    }
    .banner {
      align-self: flex-start;
      max-width: 70%;
      padding: 14px 18px;
      border-radius: 18px;
      background: rgba(255, 122, 144, 0.16);
      border: 1px solid rgba(255, 122, 144, 0.34);
      font-size: 22px;
      line-height: 1.2;
    }
    .banner.hidden { visibility: hidden; }
    .meter {
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 12px;
    }
    .count {
      font-size: 88px;
      font-weight: 800;
      letter-spacing: -0.05em;
    }
    .target {
      color: var(--muted);
      font-size: 22px;
      margin-bottom: 14px;
    }
    .panel {
      padding: 24px;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }
    .eyebrow {
      color: var(--accent);
      text-transform: uppercase;
      font-size: 12px;
      letter-spacing: 0.18em;
      font-weight: 700;
    }
    .title {
      margin: 0;
      font-size: 34px;
      line-height: 1;
    }
    .status {
      font-size: 18px;
      color: var(--muted);
      min-height: 44px;
    }
    .card {
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.05);
      padding: 16px 18px;
    }
    .card strong {
      display: block;
      font-size: 13px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 8px;
    }
    .card span {
      font-size: 26px;
      line-height: 1.15;
    }
    .pill-row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(102, 240, 201, 0.12);
      border: 1px solid rgba(102, 240, 201, 0.28);
      color: var(--text);
      font-size: 14px;
    }
    .pill.warn {
      background: rgba(255, 179, 71, 0.12);
      border-color: rgba(255, 179, 71, 0.28);
    }
    .pill.bad {
      background: rgba(255, 122, 144, 0.12);
      border-color: rgba(255, 122, 144, 0.28);
    }
    .button-row {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }
    button {
      appearance: none;
      border: 0;
      border-radius: 999px;
      padding: 14px 18px;
      font-size: 16px;
      font-weight: 700;
      background: linear-gradient(135deg, var(--accent), #3db8ff);
      color: #071018;
      cursor: pointer;
    }
    button.secondary {
      background: rgba(255, 255, 255, 0.08);
      color: var(--text);
    }
    .tiny {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }
    .version {
      color: var(--muted);
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .error-box {
      display: none;
      border-radius: 18px;
      padding: 16px 18px;
      background: rgba(255, 122, 144, 0.15);
      border: 1px solid rgba(255, 122, 144, 0.45);
      color: #ffd8df;
      font-size: 15px;
      line-height: 1.45;
      white-space: pre-wrap;
    }
    .error-box.visible {
      display: block;
    }
    .debug-box {
      border-radius: 18px;
      padding: 16px 18px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.08);
      color: #d7deeb;
      font-size: 12px;
      line-height: 1.45;
      max-height: 180px;
      overflow: auto;
      white-space: pre-wrap;
    }
    @media (max-width: 980px) {
      .shell { grid-template-columns: 1fr; }
      .count { font-size: 72px; }
      .banner { max-width: 100%; font-size: 18px; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="stage">
      <video id="video" autoplay playsinline muted></video>
      <canvas id="overlayCanvas"></canvas>
      <div class="overlay">
        <div id="banner" class="banner">Waiting for a Twitch redeem...</div>
        <div class="meter">
          <div>
            <div id="count" class="count">0</div>
            <div id="target" class="target">Target 10 squats</div>
          </div>
          <div class="pill-row">
            <div id="cameraState" class="pill warn">Camera not started</div>
            <div id="poseState" class="pill bad">Pose idle</div>
          </div>
        </div>
      </div>
    </section>
    <aside class="panel">
      <div>
        <div class="eyebrow">Live Redeem Trigger</div>
        <h1 class="title">Squat Counter Popup</h1>
      </div>
      <div id="status" class="status">Open this page before stream or let the listener auto-open it when a matching redeem arrives.</div>
      <div class="card">
        <strong>Viewer</strong>
        <span id="viewer">Waiting...</span>
      </div>
      <div class="card">
        <strong>Reward</strong>
        <span id="reward">No active redeem</span>
      </div>
      <div class="card">
        <strong>Form Hint</strong>
        <span id="phase">Stand tall with your full body visible.</span>
      </div>
      <div id="errorBox" class="error-box"></div>
      <div id="debugBox" class="debug-box">Debug log starting...</div>
      <div class="button-row">
        <button id="startButton">Start Camera</button>
        <button id="resetButton" class="secondary">Reset Counter</button>
      </div>
      <div class="version">Popup version %POPUP_VERSION%</div>
      <div class="tiny">
        This page uses your webcam in-browser and MediaPipe pose landmarks to estimate squat reps. Keep your full body in frame, preferably from the side or slight angle.
      </div>
    </aside>
  </div>
  <script>
    async function initPopupPage() {
    const popupEventsPath = "%POPUP_EVENTS_PATH%";
    const defaultSquatTarget = Number("%DEFAULT_SQUAT_TARGET%") || 10;
    const mediaPipeScriptGroups = [
      {
        base: "https://cdn.jsdelivr.net/npm",
        scripts: [
          "https://cdn.jsdelivr.net/npm/@mediapipe/pose/pose.js",
          "https://cdn.jsdelivr.net/npm/@mediapipe/drawing_utils/drawing_utils.js"
        ]
      },
      {
        base: "https://unpkg.com",
        scripts: [
          "https://unpkg.com/@mediapipe/pose/pose.js",
          "https://unpkg.com/@mediapipe/drawing_utils/drawing_utils.js"
        ]
      }
    ];

    const video = document.getElementById("video");
    const canvas = document.getElementById("overlayCanvas");
    const canvasContext = canvas.getContext("2d");
    const countEl = document.getElementById("count");
    const targetEl = document.getElementById("target");
    const viewerEl = document.getElementById("viewer");
    const rewardEl = document.getElementById("reward");
    const statusEl = document.getElementById("status");
    const phaseEl = document.getElementById("phase");
    const cameraStateEl = document.getElementById("cameraState");
    const poseStateEl = document.getElementById("poseState");
    const bannerEl = document.getElementById("banner");
    const errorBoxEl = document.getElementById("errorBox");
    const debugBoxEl = document.getElementById("debugBox");
    const startButton = document.getElementById("startButton");
    const resetButton = document.getElementById("resetButton");

    let poseDetector;
    let streamStarted = false;
    let lastVideoTime = -1;
    let currentJob = null;
    let squatCount = 0;
    let squatTargetTotal = defaultSquatTarget;
    let squatPhase = "idle";
    let lastDepth = "up";
    let cooldownFrames = 0;
    const newline = String.fromCharCode(10);
    let poseScriptsLoaded = false;
    let poseFrameInFlight = false;

    function debugLog(message) {
      const time = new Date().toLocaleTimeString();
      debugBoxEl.textContent = "[" + time + "] " + message + newline + debugBoxEl.textContent;
    }

    function setStatus(text) {
      statusEl.textContent = text;
      debugLog("status: " + text);
    }

    function showError(text) {
      errorBoxEl.textContent = text;
      errorBoxEl.classList.add("visible");
      debugLog("error: " + text);
    }

    function clearError() {
      errorBoxEl.textContent = "";
      errorBoxEl.classList.remove("visible");
    }

    function loadScript(url) {
      return new Promise(function (resolve, reject) {
        const script = document.createElement("script");
        script.src = url;
        script.async = true;
        script.crossOrigin = "anonymous";
        script.onload = function () {
          resolve();
        };
        script.onerror = function () {
          reject(new Error("Failed to load script: " + url));
        };
        document.head.appendChild(script);
      });
    }

    async function ensureMediaPipeGlobals() {
      if (window.Pose && window.drawConnectors && window.drawLandmarks && window.POSE_CONNECTIONS) {
        return;
      }

      let lastError = null;
      for (let index = 0; index < mediaPipeScriptGroups.length; index += 1) {
        const candidateGroup = mediaPipeScriptGroups[index];
        try {
          debugLog("loading MediaPipe scripts from " + candidateGroup.base);
          for (let scriptIndex = 0; scriptIndex < candidateGroup.scripts.length; scriptIndex += 1) {
            await loadScript(candidateGroup.scripts[scriptIndex]);
          }
          if (window.Pose && window.drawConnectors && window.drawLandmarks && window.POSE_CONNECTIONS) {
            debugLog("MediaPipe scripts loaded from " + candidateGroup.base);
            poseScriptsLoaded = true;
            return;
          }
          lastError = new Error("Scripts loaded but MediaPipe globals were missing: " + candidateGroup.base);
          debugLog(lastError.message);
        } catch (error) {
          lastError = error;
          debugLog(error.message);
        }
      }

      throw lastError || new Error("MediaPipe pose scripts did not load");
    }

    function setPoseState(label, tone) {
      poseStateEl.textContent = label;
      poseStateEl.className = "pill";
      if (tone) poseStateEl.classList.add(tone);
    }

    function setCameraState(label, tone) {
      cameraStateEl.textContent = label;
      cameraStateEl.className = "pill";
      if (tone) cameraStateEl.classList.add(tone);
    }

    function updateCountUi() {
      countEl.textContent = String(squatCount);
      targetEl.textContent = "Target " + squatTargetTotal + " squats";
    }

    function resetCounter() {
      squatCount = 0;
      squatTargetTotal = currentJob ? currentJob.squat_target : defaultSquatTarget;
      squatPhase = "idle";
      lastDepth = "up";
      cooldownFrames = 0;
      phaseEl.textContent = "Stand tall with your full body visible.";
      updateCountUi();
      setPoseState("Pose idle", "bad");
    }

    function parseSquatTarget(rewardTitle) {
      const match = /([0-9]+)/.exec(rewardTitle || "");
      if (!match) return defaultSquatTarget;
      const parsed = Number(match[1]);
      return Number.isFinite(parsed) && parsed > 0 ? parsed : defaultSquatTarget;
    }

    function activateJob(job) {
      const addedTarget = parseSquatTarget(job.reward_title);
      const viewerName = job.user_name || job.user_login || "Unknown viewer";
      const rewardTitle = job.reward_title || "Unknown reward";

      if (!currentJob) {
        currentJob = Object.assign({}, job, {
          squat_target: addedTarget,
          redeemers: [viewerName],
        });
        squatTargetTotal = addedTarget;
      } else {
        currentJob = Object.assign({}, currentJob, {
          squat_target: currentJob.squat_target + addedTarget,
          reward_title: rewardTitle,
          user_name: viewerName,
          user_login: job.user_login || currentJob.user_login,
          redeemers: (currentJob.redeemers || []).concat([viewerName]),
        });
        squatTargetTotal += addedTarget;
      }

      viewerEl.textContent = (currentJob.redeemers || []).join(", ");
      rewardEl.textContent = rewardTitle;
      bannerEl.textContent = viewerName + " redeemed " + rewardTitle + " +" + addedTarget;
      bannerEl.classList.remove("hidden");
      setStatus("Redeem received. Added " + addedTarget + " squats to the queue.");
      cooldownFrames = 0;
      updateCountUi();
      window.focus();
    }

    function onPoseResults(results) {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvasContext.clearRect(0, 0, canvas.width, canvas.height);
      if (!results.poseLandmarks || !results.poseLandmarks.length) return;

      const landmarks = results.poseLandmarks;
      window.drawConnectors(canvasContext, landmarks, window.POSE_CONNECTIONS, {
        color: "#66f0c9",
        lineWidth: 4,
      });
      window.drawLandmarks(canvasContext, landmarks, {
        color: "#ffb347",
        lineWidth: 1,
        radius: 4,
      });
      detectSquatPhase(landmarks);
    }

    async function ensurePoseLandmarker() {
      if (poseDetector) return;
      setStatus("Loading pose model...");
      clearError();
      debugLog("starting pose model setup");
      try {
        if (!poseScriptsLoaded) {
          debugLog("reading MediaPipe globals");
          await ensureMediaPipeGlobals();
          debugLog("MediaPipe globals ready");
        }
        poseDetector = new window.Pose({
          locateFile: function (file) {
            return "https://cdn.jsdelivr.net/npm/@mediapipe/pose/" + file;
          }
        });
        poseDetector.setOptions({
          modelComplexity: 1,
          smoothLandmarks: true,
          enableSegmentation: false,
          minDetectionConfidence: 0.55,
          minTrackingConfidence: 0.55,
        });
        poseDetector.onResults(onPoseResults);
        debugLog("pose model created");
        setStatus("Pose model ready.");
      } catch (error) {
        console.error(error);
        setPoseState("Pose load failed", "bad");
        const errorMessage = "Failed to load pose model:" + newline + (error.message || error);
        setStatus(errorMessage);
        showError(errorMessage);
        throw error;
      }
    }

    async function startCamera() {
      if (streamStarted) return;
      debugLog("start camera clicked");
      clearError();
      await ensurePoseLandmarker();
      try {
        debugLog("requesting webcam");
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        });
        debugLog("webcam stream granted");
        video.srcObject = stream;
        await video.play();
        debugLog("video playback started");
        streamStarted = true;
        setCameraState("Camera live", "");
        setStatus("Camera started. Waiting for redeems or counting the active one.");
        requestAnimationFrame(renderLoop);
      } catch (error) {
        console.error(error);
        setCameraState("Camera blocked", "bad");
        const errorMessage = "Camera start failed:" + newline + (error.message || error);
        setStatus(errorMessage);
        showError(errorMessage);
      }
    }

    function average(values) {
      const total = values.reduce((sum, value) => sum + value, 0);
      return total / values.length;
    }

    function landmarkVisible(landmark) {
      const visibility = landmark && landmark.visibility != null ? landmark.visibility : 1;
      return landmark && visibility > 0.45;
    }

    function computeKneeAngle(hip, knee, ankle) {
      const hipVectorX = hip.x - knee.x;
      const hipVectorY = hip.y - knee.y;
      const ankleVectorX = ankle.x - knee.x;
      const ankleVectorY = ankle.y - knee.y;
      const dot = hipVectorX * ankleVectorX + hipVectorY * ankleVectorY;
      const magnitudeA = Math.hypot(hipVectorX, hipVectorY);
      const magnitudeB = Math.hypot(ankleVectorX, ankleVectorY);
      if (!magnitudeA || !magnitudeB) return 180;
      const cosine = Math.min(1, Math.max(-1, dot / (magnitudeA * magnitudeB)));
      return Math.acos(cosine) * 180 / Math.PI;
    }

    function detectSquatPhase(landmarks) {
      const leftHip = landmarks[23];
      const rightHip = landmarks[24];
      const leftKnee = landmarks[25];
      const rightKnee = landmarks[26];
      const leftAnkle = landmarks[27];
      const rightAnkle = landmarks[28];
      const leftShoulder = landmarks[11];
      const rightShoulder = landmarks[12];

      const required = [leftHip, rightHip, leftKnee, rightKnee, leftAnkle, rightAnkle, leftShoulder, rightShoulder];
      if (!required.every(landmarkVisible)) {
        phaseEl.textContent = "Move back so hips, knees, ankles, and shoulders stay visible.";
        setPoseState("Pose lost", "bad");
        return;
      }

      const leftAngle = computeKneeAngle(leftHip, leftKnee, leftAnkle);
      const rightAngle = computeKneeAngle(rightHip, rightKnee, rightAnkle);
      const kneeAngle = average([leftAngle, rightAngle]);

      const hipY = average([leftHip.y, rightHip.y]);
      const shoulderY = average([leftShoulder.y, rightShoulder.y]);
      const torsoDrop = hipY - shoulderY;
      const downNow = kneeAngle < 105 && torsoDrop > 0.16;
      const upNow = kneeAngle > 150;

      if (cooldownFrames > 0) cooldownFrames -= 1;

      if (downNow) {
        lastDepth = "down";
        squatPhase = "down";
        phaseEl.textContent = "Down phase detected. Knee angle " + Math.round(kneeAngle) + "°";
        setPoseState("Squat depth hit", "");
        return;
      }

      if (upNow) {
        if (lastDepth === "down" && cooldownFrames === 0) {
          squatCount += 1;
          cooldownFrames = 12;
          const target = squatTargetTotal;
          if (squatCount >= target) {
            phaseEl.textContent = "Completed " + target + " squats. Nice work.";
            setStatus("Target reached.");
            bannerEl.textContent = "Queue finished at " + target + " squats";
          } else {
            phaseEl.textContent = "Rep " + squatCount + " counted. Stand tall before the next one.";
          }
          updateCountUi();
        }
        lastDepth = "up";
        squatPhase = "up";
        setPoseState("Standing tall", "");
        return;
      }

      squatPhase = "transition";
      phaseEl.textContent = "Tracking movement. Knee angle " + Math.round(kneeAngle) + "°";
      setPoseState("Tracking pose", "warn");
    }

    async function renderLoop() {
      if (!streamStarted || !poseDetector) return;
      if (video.currentTime !== lastVideoTime && !poseFrameInFlight) {
        poseFrameInFlight = true;
        try {
          await poseDetector.send({ image: video });
          lastVideoTime = video.currentTime;
        } finally {
          poseFrameInFlight = false;
        }
      }
      requestAnimationFrame(renderLoop);
    }

    function connectEventStream() {
      debugLog("connecting popup event stream");
      const eventSource = new EventSource(popupEventsPath);
      eventSource.onmessage = function (message) {
        const payload = JSON.parse(message.data);
        debugLog("received popup event for " + (payload.user_login || "unknown"));
        activateJob(payload);
      };
      eventSource.onerror = function () {
        setStatus("Connection to local popup event feed dropped. Retrying...");
      };
    }

    startButton.addEventListener("click", function () {
      startCamera();
    });

    resetButton.addEventListener("click", function () {
      currentJob = null;
      squatTargetTotal = defaultSquatTarget;
      resetCounter();
      viewerEl.textContent = "Waiting...";
      rewardEl.textContent = "No active redeem";
      bannerEl.classList.add("hidden");
      setStatus("Counter reset.");
    });

    updateCountUi();
    debugLog("page script loaded");
    window.addEventListener("error", function (event) {
      showError("Window error:" + newline + event.message);
    });
    window.addEventListener("unhandledrejection", function (event) {
      showError("Unhandled promise rejection:" + newline + event.reason);
    });
    connectEventStream();
    }

    initPopupPage().catch(function (error) {
      const errorBoxEl = document.getElementById("errorBox");
      const debugBoxEl = document.getElementById("debugBox");
      const message = "Bootstrap failure:" + newline + (error && error.message ? error.message : error);
      if (errorBoxEl) {
        errorBoxEl.textContent = message;
        errorBoxEl.classList.add("visible");
      }
      if (debugBoxEl) {
        debugBoxEl.textContent = message + newline + debugBoxEl.textContent;
      }
      console.error(error);
    });
  </script>
</body>
</html>
"""


class RedeemPopupState:
    def __init__(self):
        self.condition = threading.Condition()
        self.current_job = None
        self.sequence = 0
        self.last_popup_opened_at = 0.0
        self.last_popup_connected_at = 0.0

    def publish(self, redemption):
        with self.condition:
            self.sequence += 1
            payload = dict(redemption)
            payload["sequence"] = self.sequence
            payload["squat_target"] = extract_squat_target(payload.get("reward_title"))
            self.current_job = payload
            self.condition.notify_all()
            return payload

    def wait_for_next(self, last_seen_sequence, timeout=30.0):
        with self.condition:
            self.last_popup_connected_at = time.time()
            if self.current_job and self.current_job["sequence"] > last_seen_sequence:
                return self.current_job

            self.condition.wait(timeout)
            self.last_popup_connected_at = time.time()
            if self.current_job and self.current_job["sequence"] > last_seen_sequence:
                return self.current_job
            return None


POPUP_STATE = RedeemPopupState()


def extract_squat_target(reward_title):
    if not reward_title:
        return DEFAULT_SQUAT_TARGET

    digits = "".join(character if character.isdigit() else " " for character in reward_title)
    for token in digits.split():
        parsed = int(token)
        if parsed > 0:
            return parsed
    return DEFAULT_SQUAT_TARGET


def maybe_open_popup():
    if not AUTO_OPEN_POPUP:
        return

    now = time.time()
    if now - POPUP_STATE.last_popup_connected_at < 20:
        return

    if now - POPUP_STATE.last_popup_opened_at < 2:
        return

    try:
        subprocess.Popen(["open", POPUP_OPEN_URL])
        POPUP_STATE.last_popup_opened_at = now
    except OSError as error:
        print(json.dumps({"popup_open_error": str(error), "url": POPUP_OPEN_URL}), flush=True)


def should_trigger_popup_from_riot_check():
    if not RIOT_CHECK_ENABLED:
        return True, "riot_check_disabled"

    try:
        command = shlex.split(RIOT_CHECK_COMMAND)
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
            cwd=os.getcwd(),
        )
    except Exception as error:
        return False, f"riot_check_failed:{error}"

    stdout = (result.stdout or "").strip().lower()
    stderr = (result.stderr or "").strip()

    if result.returncode != 0:
        return False, f"riot_check_nonzero:{result.returncode}:{stderr or stdout}"

    if stdout == "false":
        return True, "riot_idle"

    if stdout == "true":
        return False, "riot_recently_active"

    return False, f"riot_check_unexpected_output:{stdout}"


def build_hmac(message_id, timestamp, raw_body):
    message = message_id.encode("utf-8") + timestamp.encode("utf-8") + raw_body
    digest = hmac.new(
        EVENTSUB_SECRET.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    return HMAC_PREFIX + digest


def is_valid_signature(headers, raw_body):
    message_id = headers.get(MESSAGE_ID_HEADER, "")
    timestamp = headers.get(MESSAGE_TIMESTAMP_HEADER, "")
    signature = headers.get(MESSAGE_SIGNATURE_HEADER, "")

    if not message_id or not timestamp or not signature:
        return False, "missing signature headers"

    expected_signature = build_hmac(message_id, timestamp, raw_body)
    if not hmac.compare_digest(expected_signature, signature):
        return (
            False,
            f"signature mismatch expected={expected_signature} got={signature}",
        )
    return True, "ok"


def is_recent_message(headers):
    timestamp = headers.get(MESSAGE_TIMESTAMP_HEADER, "")
    if not timestamp:
        return False, "missing timestamp"

    try:
        if timestamp.endswith("Z"):
            seconds_text, _, fractional_and_zone = timestamp[:-1].partition(".")
            if fractional_and_zone:
                fractional_seconds = fractional_and_zone[:6]
                normalized = f"{seconds_text}.{fractional_seconds}+00:00"
            else:
                normalized = f"{timestamp[:-1]}+00:00"
        else:
            normalized = timestamp

        event_time = datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return False, f"invalid timestamp format: {timestamp}"

    age_seconds = abs(time.time() - event_time)
    if age_seconds > MAX_MESSAGE_AGE_SECONDS:
        return False, f"message too old age_seconds={age_seconds:.2f}"
    return True, "ok"


def get_matching_redemption(payload):
    event = payload.get("event", {})
    broadcaster_login = (event.get("broadcaster_user_login") or "").lower()
    reward = event.get("reward", {})
    reward_title = reward.get("title")
    reward_id = reward.get("id")

    if broadcaster_login != BROADCASTER_LOGIN.lower():
        return None

    if TARGET_REWARD_ID and reward_id != TARGET_REWARD_ID:
        return None

    if TARGET_REWARD_TITLE and reward_title != TARGET_REWARD_TITLE:
        return None

    return {
        "redeemed": True,
        "event_type": payload.get("subscription", {}).get("type"),
        "broadcaster_login": broadcaster_login,
        "user_login": event.get("user_login"),
        "user_name": event.get("user_name"),
        "reward_title": reward_title,
        "reward_id": reward_id,
        "redeemed_at": event.get("redeemed_at"),
        "user_input": event.get("user_input"),
    }


def summarize_redemption(payload):
    event = payload.get("event", {})
    reward = event.get("reward", {})
    return {
        "event_type": payload.get("subscription", {}).get("type"),
        "broadcaster_login": event.get("broadcaster_user_login"),
        "user_login": event.get("user_login"),
        "user_name": event.get("user_name"),
        "reward_title": reward.get("title"),
        "reward_id": reward.get("id"),
        "redeemed_at": event.get("redeemed_at"),
        "user_input": event.get("user_input"),
    }


class EventSubHandler(BaseHTTPRequestHandler):
    seen_message_ids = set()

    def send_json_response(self, status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_popup_page(self):
        html = (
            POPUP_HTML
            .replace("%POPUP_EVENTS_PATH%", POPUP_EVENTS_PATH)
            .replace("%DEFAULT_SQUAT_TARGET%", str(DEFAULT_SQUAT_TARGET))
            .replace("%POPUP_VERSION%", POPUP_VERSION)
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def serve_popup_events(self):
        last_event_id = self.headers.get("Last-Event-ID", "0")
        try:
            last_seen_sequence = int(last_event_id or "0")
        except ValueError:
            last_seen_sequence = 0

        event = POPUP_STATE.wait_for_next(last_seen_sequence, timeout=25.0)
        if event is None:
            payload = "event: keepalive\ndata: {}\n\n".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Connection", "keep-alive")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        body = f"id: {event['sequence']}\ndata: {json.dumps(event)}\n\n".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Connection", "keep-alive")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == CALLBACK_PATH:
            self.send_json_response(
                200,
                {
                    "ok": True,
                    "channel": BROADCASTER_LOGIN,
                    "reward_title": TARGET_REWARD_TITLE,
                    "reward_id": TARGET_REWARD_ID,
                    "popup_path": POPUP_PATH,
                    "popup_events_path": POPUP_EVENTS_PATH,
                    "auto_open_popup": AUTO_OPEN_POPUP,
                },
            )
            return

        if parsed_path.path == POPUP_PATH or parsed_path.path == "/":
            self.serve_popup_page()
            return

        if parsed_path.path == POPUP_EVENTS_PATH:
            self.serve_popup_events()
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return

        raw_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))

        if not EVENTSUB_SECRET:
            self.send_response(500)
            self.end_headers()
            return

        signature_valid, signature_reason = is_valid_signature(self.headers, raw_body)
        if not signature_valid:
            print(
                json.dumps(
                    {
                        "verification_error": "invalid_signature",
                        "reason": signature_reason,
                    }
                ),
                flush=True,
            )
            self.send_response(403)
            self.end_headers()
            return

        message_recent, recent_reason = is_recent_message(self.headers)
        if not message_recent:
            print(
                json.dumps(
                    {
                        "verification_error": "stale_message",
                        "reason": recent_reason,
                    }
                ),
                flush=True,
            )
            self.send_response(403)
            self.end_headers()
            return

        message_id = self.headers.get(MESSAGE_ID_HEADER)
        if message_id in self.seen_message_ids:
            self.send_response(204)
            self.end_headers()
            return
        self.seen_message_ids.add(message_id)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        message_type = self.headers.get(MESSAGE_TYPE_HEADER, "")

        if message_type == "webhook_callback_verification":
            challenge = payload.get("challenge", "").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(challenge)))
            self.end_headers()
            self.wfile.write(challenge)
            return

        if message_type == "revocation":
            print(
                json.dumps(
                    {
                        "revoked": True,
                        "subscription_type": payload.get("subscription", {}).get("type"),
                        "status": payload.get("subscription", {}).get("status"),
                    }
                )
            )
            self.send_response(204)
            self.end_headers()
            return

        if message_type != "notification":
            self.send_response(204)
            self.end_headers()
            return

        summary = summarize_redemption(payload)
        print(json.dumps({"incoming_redemption": summary}), flush=True)

        matched = get_matching_redemption(payload)
        if matched is not None:
            user_login = matched.get("user_login") or "unknown_user"
            reward_title = matched.get("reward_title") or "unknown_reward"
            should_trigger, trigger_reason = should_trigger_popup_from_riot_check()
            print(
                json.dumps(
                    {
                        "riot_gate": {
                            "allowed": should_trigger,
                            "reason": trigger_reason,
                            "user_login": user_login,
                            "reward_title": reward_title,
                        }
                    }
                ),
                flush=True,
            )
            if not should_trigger:
                print(
                    json.dumps(
                        {
                            "redeemed": False,
                            "skipped": True,
                            "skip_reason": trigger_reason,
                            "user_login": user_login,
                            "reward_title": reward_title,
                        }
                    ),
                    flush=True,
                )
                self.send_response(204)
                self.end_headers()
                return

            popup_job = POPUP_STATE.publish(matched)
            maybe_open_popup()
            print(f"{user_login} redeemed {reward_title}", flush=True)
            print(
                json.dumps(
                    {
                        "popup_job": {
                            "sequence": popup_job["sequence"],
                            "squat_target": popup_job["squat_target"],
                            "popup_url": POPUP_OPEN_URL,
                        }
                    }
                ),
                flush=True,
            )
            print(json.dumps(matched), flush=True)
        else:
            print(
                json.dumps(
                    {
                        "matched": False,
                        "target_reward_title": TARGET_REWARD_TITLE,
                        "target_reward_id": TARGET_REWARD_ID,
                    }
                ),
                flush=True,
            )

        self.send_response(204)
        self.end_headers()


def main():
    if not EVENTSUB_SECRET or len(EVENTSUB_SECRET) < 10:
        print("Set TWITCH_EVENTSUB_SECRET to an ASCII string with at least 10 characters.")
        return

    server = ThreadingHTTPServer((HOST, PORT), EventSubHandler)
    print(
        json.dumps(
            {
                "listening": True,
                "host": HOST,
                "port": PORT,
                "path": CALLBACK_PATH,
                "channel": BROADCASTER_LOGIN,
                "reward_title": TARGET_REWARD_TITLE,
                "reward_id": TARGET_REWARD_ID,
                "popup_path": POPUP_PATH,
                "popup_open_url": POPUP_OPEN_URL,
                "auto_open_popup": AUTO_OPEN_POPUP,
            }
        ),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()

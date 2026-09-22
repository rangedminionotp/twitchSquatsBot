import hashlib
import hmac
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from app_config import APP_CONFIG
from app_stats import APP_STATS
from control_panel import CONTROL_HTML
from camera_overlay import CAMERA_CONTROL, CAMERA_STYLE
from twitch_eventsub_websocket import TwitchService
from support_events import SupportService


HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8080"))
CALLBACK_PATH = os.environ.get("TWITCH_CALLBACK_PATH", "/eventsub")
POPUP_PATH = os.environ.get("TWITCH_POPUP_PATH", "/squat-popup")
POPUP_EVENTS_PATH = os.environ.get("TWITCH_POPUP_EVENTS_PATH", "/popup-events")
OVERLAY_PATH = os.environ.get("TWITCH_OVERLAY_PATH", "/overlay")
OVERLAY_REFRESH_PATH = os.environ.get("TWITCH_OVERLAY_REFRESH_PATH", "/overlay-refresh")
OVERLAY_KEY_PATH = os.environ.get("TWITCH_OVERLAY_KEY_PATH", "/overlay-key")
OVERLAY_MAGENTA_KEY_PATH = os.environ.get("TWITCH_OVERLAY_MAGENTA_KEY_PATH", "/overlay-magenta-key")
OVERLAY_EVENTS_PATH = os.environ.get("TWITCH_OVERLAY_EVENTS_PATH", "/overlay-events")
OVERLAY_STATE_PATH = os.environ.get("TWITCH_OVERLAY_STATE_PATH", "/overlay-state")
SQUAT_PROGRESS_PATH = os.environ.get("TWITCH_SQUAT_PROGRESS_PATH", "/squat-progress")
SQUAT_COMPLETE_PATH = os.environ.get("TWITCH_SQUAT_COMPLETE_PATH", "/squat-complete")
EVENTSUB_SECRET = os.environ.get("TWITCH_EVENTSUB_SECRET", "")
BROADCASTER_LOGIN = os.environ.get("TWITCH_BROADCASTER_LOGIN", "")
TARGET_REWARD_TITLE = os.environ.get("TARGET_REWARD_TITLE", "")
TARGET_REWARD_ID = os.environ.get("TARGET_REWARD_ID", "")
MAX_MESSAGE_AGE_SECONDS = 600
AUTO_OPEN_POPUP = os.environ.get("AUTO_OPEN_POPUP", "1") == "1"
POPUP_OPEN_URL = os.environ.get("POPUP_OPEN_URL", f"http://127.0.0.1:{PORT}{POPUP_PATH}")
DEFAULT_SQUAT_TARGET = int(os.environ.get("DEFAULT_SQUAT_TARGET", "10"))
MAX_SESSION_SQUATS = int(os.environ.get("MAX_SESSION_SQUATS", "50"))
POPUP_VERSION = "2026-07-12-live-progress-1"
RIOT_CHECK_ENABLED = os.environ.get("RIOT_CHECK_ENABLED", "1") == "1"
RIOT_CHECK_COMMAND = os.environ.get("RIOT_CHECK_COMMAND", f'"{sys.executable}" script.py')
SOFT_LOCK_ENABLED = os.environ.get("SOFT_LOCK_ENABLED", "1") == "1"

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
      overflow: auto;
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
      overflow: auto;
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
    .form-guide {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }
    .form-step {
      border-radius: 16px;
      padding: 14px;
      background: rgba(255, 255, 255, 0.04);
      border: 2px solid rgba(255, 255, 255, 0.08);
      transition: border-color 120ms ease, background 120ms ease, transform 120ms ease;
    }
    .form-step.active {
      border-color: var(--accent);
      background: rgba(102, 240, 201, 0.13);
      transform: translateY(-2px);
    }
    .form-step strong {
      display: block;
      color: var(--text);
      font-size: 20px;
      margin-bottom: 4px;
    }
    .form-step span {
      color: var(--muted);
      font-size: 13px;
    }
    .angle-readout {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 10px;
    }
    .angle-readout strong { margin: 0; }
    .angle-readout span {
      font-size: 24px;
      font-weight: 800;
    }
    .depth-track {
      height: 14px;
      overflow: hidden;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.09);
    }
    .depth-fill {
      width: 0%;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent-2), var(--accent));
      transition: width 100ms linear;
    }
    .threshold-labels {
      display: flex;
      justify-content: space-between;
      margin-top: 7px;
      color: var(--muted);
      font-size: 11px;
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
    .camera-picker {
      display: flex;
      gap: 10px;
      align-items: center;
    }
    select {
      min-width: 0;
      flex: 1;
      appearance: none;
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 14px;
      padding: 12px 14px;
      background: #171d29;
      color: var(--text);
      font: inherit;
    }
    select:disabled { opacity: 0.55; }
    .small-button {
      flex: 0 0 auto;
      padding: 12px 14px;
      border-radius: 14px;
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
        <strong>Squats Owed</strong>
        <span id="owedCount">0</span>
      </div>
      <div class="card">
        <strong>Completed · Twitch stream</strong>
        <span id="completedCount">0</span>
      </div>
      <div class="card">
        <strong>Form Hint</strong>
        <span id="phase">Stand tall with your full body visible.</span>
      </div>
      <div class="form-guide" aria-label="Squat phase guide">
        <div id="standIndicator" class="form-step active">
          <strong>1. STAND</strong>
          <span>Legs nearly straight: 155°+</span>
        </div>
        <div id="downIndicator" class="form-step">
          <strong>2. DOWN</strong>
          <span>Knees bent to 120° or lower</span>
        </div>
      </div>
      <div class="card">
        <div class="angle-readout">
          <strong>Knee Bend</strong>
          <span id="angleValue">--°</span>
        </div>
        <div class="depth-track">
          <div id="depthFill" class="depth-fill"></div>
        </div>
        <div class="threshold-labels">
          <span>Standing 180°</span>
          <span>Down ≤120°</span>
        </div>
      </div>
      <div class="card">
        <strong>Camera Device</strong>
        <div class="camera-picker">
          <select id="cameraSelect" aria-label="Camera device">
            <option value="">Start camera to load devices</option>
          </select>
          <button id="refreshCamerasButton" class="secondary small-button">Refresh</button>
        </div>
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
    const squatProgressPath = "%SQUAT_PROGRESS_PATH%";
    const squatCompletePath = "%SQUAT_COMPLETE_PATH%";
    const defaultSquatTarget = Number("%DEFAULT_SQUAT_TARGET%") || 10;
    const isCameraOverlay = location.pathname === '/camera-overlay';
    let cameraMode = 'webcam';
    let cameraModeBusy = false;
    let queueTicket = null;
    const cameraCounts = new Map();
    const cameraPending = new Map();
    let savingCamera = false;
    const cameraPageId = crypto.randomUUID();
    let cameraLeaseUntil = 0, cameraStorageOk = true, lastBodySeen = 0;
    const outboxPrefix = 'squat-camera-outbox-v1:';
    function persistCamera(payload){
      try{localStorage.setItem(outboxPrefix+payload.capture_session_id,JSON.stringify(payload));cameraStorageOk=true;return true}
      catch(e){cameraStorageOk=false;cameraMode='webcam';showError('Local saving unavailable. Capture paused; free browser storage before continuing.');return false}
    }
    function recoverCamera(){
      try{for(let i=0;i<localStorage.length;i++){const key=localStorage.key(i);if(!key.startsWith(outboxPrefix))continue;const p=JSON.parse(localStorage.getItem(key));if(p&&typeof p.capture_session_id==='string'&&Number.isInteger(p.count)&&p.count>=0)cameraPending.set(p.capture_session_id,p)}cameraStorageOk=true}catch(e){cameraStorageOk=false;showError('Cannot recover saved reps. Capture paused; do not clear site data.')}
    }
    async function flushCameraCounts(){
      if(savingCamera||Date.now()>=cameraLeaseUntil)return;savingCamera=true;
      try{for(const [key,payload] of cameraPending){if(!persistCamera(payload))throw Error('Local saving unavailable');const r=await fetch('/api/camera/progress',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,page_id:cameraPageId}),signal:AbortSignal.timeout(4000)});if(!r.ok)throw Error('Could not save reps; retrying');if(cameraPending.get(key)===payload){localStorage.removeItem(outboxPrefix+payload.capture_session_id);cameraPending.delete(key)}}}finally{savingCamera=false}
    }
    const captureSessionId = window.crypto && window.crypto.randomUUID
      ? window.crypto.randomUUID()
      : String(Date.now()) + Math.random();
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
    const owedCountEl = document.getElementById("owedCount");
    const completedCountEl = document.getElementById("completedCount");
    const statusEl = document.getElementById("status");
    const phaseEl = document.getElementById("phase");
    const cameraStateEl = document.getElementById("cameraState");
    const poseStateEl = document.getElementById("poseState");
    const bannerEl = document.getElementById("banner");
    const errorBoxEl = document.getElementById("errorBox");
    const debugBoxEl = document.getElementById("debugBox");
    const startButton = document.getElementById("startButton");
    const resetButton = document.getElementById("resetButton");
    const standIndicatorEl = document.getElementById("standIndicator");
    const downIndicatorEl = document.getElementById("downIndicator");
    const angleValueEl = document.getElementById("angleValue");
    const depthFillEl = document.getElementById("depthFill");
    const cameraSelectEl = document.getElementById("cameraSelect");
    const refreshCamerasButton = document.getElementById("refreshCamerasButton");

    let poseDetector;
    let cameraStream = null;
    let streamStarted = false;
    let renderLoopStarted = false;
    let lastVideoTime = -1;
    let currentJob = null;
    let squatCount = 0;
    let squatTargetTotal = defaultSquatTarget;
    let squatPhase = "idle";
    let lastDepth = "up";
    let cooldownFrames = 0;
    let downCandidateFrames = 0;
    let upCandidateFrames = 0;
    const newline = String.fromCharCode(10);
    let poseScriptsLoaded = false;
    let poseFrameInFlight = false;
    let completionReported = false;
    let lastProgressSignature = "";
    const downAngleThreshold = 120;
    const upAngleThreshold = 155;
    const stableFramesRequired = 3;

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

    function updateCountUi(progressStatus, forceProgressReport) {
      countEl.textContent = String(squatCount);
      targetEl.textContent = "Target " + squatTargetTotal + " squats";
      maybeReportSquatProgress(progressStatus || "active", forceProgressReport);
    }

    function resetCounter() {
      squatCount = 0;
      squatTargetTotal = currentJob ? currentJob.squat_target : defaultSquatTarget;
      squatPhase = "idle";
      lastDepth = "up";
      cooldownFrames = 0;
      downCandidateFrames = 0;
      upCandidateFrames = 0;
      completionReported = false;
      phaseEl.textContent = "Stand tall with your full body visible.";
      angleValueEl.textContent = "--°";
      depthFillEl.style.width = "0%";
      standIndicatorEl.classList.add("active");
      downIndicatorEl.classList.remove("active");
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
      if (squatCount < squatTargetTotal) {
        completionReported = false;
      }
      updateCountUi("active", true);
      window.focus();
    }

    async function reportSquatComplete(target) {
      if (completionReported) return;
      completionReported = true;
      const payload = {
        sequence: currentJob ? currentJob.sequence : null,
        user_login: currentJob ? currentJob.user_login : null,
        user_name: currentJob ? currentJob.user_name : null,
        reward_title: currentJob ? currentJob.reward_title : null,
        squat_count: squatCount,
        squat_target: target,
        capture_session_id: captureSessionId,
      };
      try {
        const response = await fetch(squatCompletePath, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        });
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        debugLog("soft lock release reported");
      } catch (error) {
        completionReported = false;
        showError("Could not report squat completion:" + newline + (error.message || error));
      }
    }

    async function reportSquatProgress(status) {
      const payload = {
        status: status || "active",
        sequence: currentJob ? currentJob.sequence : null,
        user_login: currentJob ? currentJob.user_login : null,
        user_name: currentJob ? currentJob.user_name : null,
        reward_title: currentJob ? currentJob.reward_title : null,
        squat_count: squatCount,
        squat_target: squatTargetTotal,
        capture_session_id: captureSessionId,
      };
      try {
        const response = await fetch(squatProgressPath, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        });
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        const result = await response.json();
        if (result.overlay) {
          owedCountEl.textContent = String(result.overlay.owed_squats || 0);
          completedCountEl.textContent = String(result.overlay.completed_squats || 0);
        }
      } catch (error) {
        debugLog("could not report squat progress: " + (error.message || error));
      }
    }

    function maybeReportSquatProgress(status, force) {
      if (!currentJob) return;
      const payloadStatus = status || "active";
      const signature = [
        payloadStatus,
        currentJob.sequence || "",
        squatCount,
        squatTargetTotal,
        currentJob.user_login || "",
        currentJob.reward_title || "",
      ].join(":");
      if (!force && signature === lastProgressSignature) return;
      lastProgressSignature = signature;
      reportSquatProgress(payloadStatus);
    }

    function onPoseResults(results) {
      if (isCameraOverlay && (cameraMode !== 'capture' || Date.now()>=cameraLeaseUntil || !cameraStorageOk)) return;
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvasContext.clearRect(0, 0, canvas.width, canvas.height);
      if (!results.poseLandmarks || !results.poseLandmarks.length) {
        phaseEl.textContent = "No body detected. Step back and keep your full body in frame.";
        angleValueEl.textContent = "--°";
        setPoseState("Pose lost", "bad");
        return;
      }

      const landmarks = results.poseLandmarks;
      lastBodySeen = Date.now();
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

    function stopCameraStream() {
      if (!cameraStream) return;
      cameraStream.getTracks().forEach(function (track) {
        track.stop();
      });
      cameraStream = null;
    }

    async function refreshCameraDevices(preferredDeviceId) {
      if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
        cameraSelectEl.innerHTML = '<option value="">Camera selection unavailable</option>';
        cameraSelectEl.disabled = true;
        return;
      }

      const devices = await navigator.mediaDevices.enumerateDevices();
      const cameras = devices.filter(function (device) {
        return device.kind === "videoinput";
      });
      const activeTrack = cameraStream && cameraStream.getVideoTracks()[0];
      const activeSettings = activeTrack && activeTrack.getSettings ? activeTrack.getSettings() : {};
      const selectedDeviceId = preferredDeviceId || activeSettings.deviceId || cameraSelectEl.value;

      cameraSelectEl.innerHTML = "";
      cameras.forEach(function (camera, index) {
        const option = document.createElement("option");
        option.value = camera.deviceId;
        option.textContent = camera.label || "Camera " + (index + 1);
        cameraSelectEl.appendChild(option);
      });

      if (!cameras.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "No camera devices found";
        cameraSelectEl.appendChild(option);
        cameraSelectEl.disabled = true;
        return;
      }

      cameraSelectEl.disabled = false;
      if (selectedDeviceId && cameras.some(function (camera) { return camera.deviceId === selectedDeviceId; })) {
        cameraSelectEl.value = selectedDeviceId;
      }
      debugLog("found " + cameras.length + " camera device(s)");
    }

    function getCameraConstraintAttempts(deviceId) {
      if (deviceId) {
        return [
          {
            label: "selected camera at preferred HD",
            video: {
              deviceId: { exact: deviceId },
              width: { ideal: 1280 },
              height: { ideal: 720 },
            },
          },
          {
            label: "selected camera without resolution constraints",
            video: {
              deviceId: { exact: deviceId },
            },
          },
          {
            label: "selected camera with flexible device match",
            video: {
              deviceId: { ideal: deviceId },
            },
          },
        ];
      }

      return [
        {
          label: "default front camera at preferred HD",
          video: {
            facingMode: "user",
            width: { ideal: 1280 },
            height: { ideal: 720 },
          },
        },
        {
          label: "default camera without constraints",
          video: true,
        },
      ];
    }

    async function openCamera(deviceId) {
      try {
        setCameraState("Switching camera...", "warn");
        const attempts = getCameraConstraintAttempts(deviceId);
        const errors = [];
        let newStream = null;
        for (let index = 0; index < attempts.length; index += 1) {
          const attempt = attempts[index];
          try {
            debugLog("trying camera: " + attempt.label);
            newStream = await navigator.mediaDevices.getUserMedia({
              video: attempt.video,
              audio: false,
            });
            debugLog("camera opened with: " + attempt.label);
            break;
          } catch (attemptError) {
            errors.push(attempt.label + " -> " + (attemptError.name || "Error") + ": " + (attemptError.message || attemptError));
            debugLog("camera attempt failed: " + errors[errors.length - 1]);
          }
        }

        if (!newStream) {
          throw new Error(errors.join(newline));
        }

        stopCameraStream();
        cameraStream = newStream;
        video.srcObject = cameraStream;
        await video.play();
        streamStarted = true;
        const activeTrack = cameraStream.getVideoTracks()[0];
        setCameraState(activeTrack.label || "Camera live", "");
        await refreshCameraDevices();
        cameraSelectEl.value = (activeTrack.getSettings && activeTrack.getSettings().deviceId) || cameraSelectEl.value;
        setStatus("Camera started. Waiting for redeems or counting the active one.");
        if (!renderLoopStarted) {
          renderLoopStarted = true;
          requestAnimationFrame(renderLoop);
        }
      } catch (error) {
        console.error(error);
        setCameraState("Camera unavailable", "bad");
        const errorMessage = "Camera start/switch failed:" + newline + (error.message || error);
        setStatus(errorMessage);
        showError(errorMessage);
      }
    }

    async function startCamera() {
      if(isCameraOverlay&&Date.now()>=cameraLeaseUntil){showError('Another camera page is active, or the server is unavailable. Close other camera pages and wait a few seconds.');return;}
      debugLog("start camera clicked");
      clearError();
      if (!isCameraOverlay || cameraMode === 'capture') await ensurePoseLandmarker();
      await openCamera(cameraSelectEl.value || "");
    }

    function average(values) {
      const total = values.reduce((sum, value) => sum + value, 0);
      return total / values.length;
    }

    function landmarkVisibility(landmark) {
      return landmark && landmark.visibility != null ? landmark.visibility : 1;
    }

    function landmarkVisible(landmark) {
      return landmark && landmarkVisibility(landmark) > 0.35;
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

      const leftLeg = [leftHip, leftKnee, leftAnkle];
      const rightLeg = [rightHip, rightKnee, rightAnkle];
      const leftVisible = leftLeg.every(landmarkVisible);
      const rightVisible = rightLeg.every(landmarkVisible);

      if ((!leftVisible && !rightVisible) || !landmarkVisible(leftShoulder) || !landmarkVisible(rightShoulder)) {
        phaseEl.textContent = "Move back so at least one full leg and both shoulders are visible.";
        angleValueEl.textContent = "--°";
        setPoseState("Pose lost", "bad");
        return;
      }

      const leftAngle = computeKneeAngle(leftHip, leftKnee, leftAnkle);
      const rightAngle = computeKneeAngle(rightHip, rightKnee, rightAnkle);
      let kneeAngle;
      if (leftVisible && rightVisible) {
        const leftConfidence = average(leftLeg.map(landmarkVisibility));
        const rightConfidence = average(rightLeg.map(landmarkVisibility));
        kneeAngle = leftConfidence >= rightConfidence ? leftAngle : rightAngle;
      } else {
        kneeAngle = leftVisible ? leftAngle : rightAngle;
      }

      const downNow = kneeAngle <= downAngleThreshold;
      const upNow = kneeAngle >= upAngleThreshold;
      const depthPercent = Math.max(
        0,
        Math.min(100, (180 - kneeAngle) / (180 - downAngleThreshold) * 100)
      );
      angleValueEl.textContent = Math.round(kneeAngle) + "°";
      depthFillEl.style.width = depthPercent + "%";

      if (cooldownFrames > 0) cooldownFrames -= 1;

      if (downNow) {
        downCandidateFrames += 1;
        upCandidateFrames = 0;
        standIndicatorEl.classList.remove("active");
        downIndicatorEl.classList.add("active");
        if (downCandidateFrames >= stableFramesRequired) {
          lastDepth = "down";
          squatPhase = "down";
          phaseEl.textContent = "Depth reached. Now stand all the way up to count the rep.";
          setPoseState("DOWN ✓", "");
        } else {
          phaseEl.textContent = "Hold that depth for a moment...";
          setPoseState("Confirming depth", "warn");
        }
        return;
      }

      if (upNow) {
        upCandidateFrames += 1;
        downCandidateFrames = 0;
        standIndicatorEl.classList.add("active");
        downIndicatorEl.classList.remove("active");
        if (upCandidateFrames >= stableFramesRequired) {
          if (lastDepth === "down" && cooldownFrames === 0) {
            squatCount += 1;
            if (isCameraOverlay) {
              countEl.textContent = String(squatCount);
              const segment=queueTicket||'free';
              const total=(cameraCounts.get(segment)||0)+1;cameraCounts.set(segment,total);
              const payload={capture_session_id:captureSessionId+':'+segment,count:total,queue_run:queueTicket};
              cameraPending.set(payload.capture_session_id,payload);persistCamera(payload);
              flushCameraCounts().catch(e=>showError(e.message));
              lastDepth = 'up'; squatPhase = 'up'; cooldownFrames = 12;
              return;
            }
            cooldownFrames = 12;
            const target = squatTargetTotal;
            if (squatCount >= target) {
              phaseEl.textContent = "Completed " + target + " squats. Nice work.";
              setStatus("Target reached.");
              bannerEl.textContent = "Queue finished at " + target + " squats";
              updateCountUi("complete", true);
              reportSquatComplete(target);
            } else {
              phaseEl.textContent = "Rep " + squatCount + " counted. Go down again for the next rep.";
              updateCountUi("active", true);
            }
          }
          lastDepth = "up";
          squatPhase = "up";
          setPoseState("STAND ✓", "");
        } else {
          phaseEl.textContent = lastDepth === "down"
            ? "Stand tall and hold briefly to finish the rep..."
            : "Hold your standing position for calibration...";
          setPoseState("Confirming stand", "warn");
        }
        return;
      }

      downCandidateFrames = 0;
      upCandidateFrames = 0;
      squatPhase = "transition";
      standIndicatorEl.classList.remove("active");
      downIndicatorEl.classList.remove("active");
      phaseEl.textContent = lastDepth === "down"
        ? "Stand " + Math.max(0, Math.ceil(upAngleThreshold - kneeAngle)) + "° taller to finish the rep."
        : "Go about " + Math.max(0, Math.ceil(kneeAngle - downAngleThreshold)) + "° lower to reach depth.";
      setPoseState("MIDPOINT", "warn");
    }

    async function renderLoop() {
      if(isCameraOverlay&&!streamStarted){requestAnimationFrame(renderLoop);return;}
      if (isCameraOverlay && (cameraMode !== 'capture' || !poseDetector)) { requestAnimationFrame(renderLoop); return; }
      if (!streamStarted || !poseDetector) return;
      if (video.currentTime !== lastVideoTime && !poseFrameInFlight) {
        poseFrameInFlight = true;
        try {
          await poseDetector.send({ image: video });
          lastVideoTime = video.currentTime;
        } catch (error) {
          showError('Pose detection failed: ' + error.message);
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

    cameraSelectEl.addEventListener("change", function () {
      if (!streamStarted || !cameraSelectEl.value) return;
      clearError();
      debugLog("switching selected camera");
      openCamera(cameraSelectEl.value);
    });

    refreshCamerasButton.addEventListener("click", function () {
      refreshCameraDevices().catch(function (error) {
        showError("Could not refresh cameras:" + newline + (error.message || error));
      });
    });

    if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) {
      navigator.mediaDevices.addEventListener("devicechange", function () {
        refreshCameraDevices().catch(function (error) {
          debugLog("camera device refresh failed: " + (error.message || error));
        });
      });
    }

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
    refreshCameraDevices().catch(function (error) {
      debugLog("initial camera list unavailable: " + (error.message || error));
    });
    window.addEventListener("error", function (event) {
      showError("Window error:" + newline + event.message);
    });
    window.addEventListener("unhandledrejection", function (event) {
      showError("Unhandled promise rejection:" + newline + event.reason);
    });
    if (!isCameraOverlay) connectEventStream();
    if (isCameraOverlay) {
      document.title='Squat Capture · Camera Overlay';
      document.body.dataset.cameraMode='webcam';
      const tools=document.createElement('div');tools.id='cameraTools';
      const help=document.createElement('p');help.textContent='Release your camera in Streamlabs first. Start here, then window-capture this page. H toggles controls; keep this window open, not minimized.';
      const hide=document.createElement('button');hide.textContent='Hide controls (H)';hide.onclick=()=>document.body.classList.add('clean');
      tools.append(help,startButton,cameraSelectEl,refreshCamerasButton,hide);document.body.append(tools);
      const warning=document.createElement('div');warning.id='cameraWarning';document.body.append(warning);
      const syncInfo=document.createElement('p');syncInfo.setAttribute('role','status');tools.append(syncInfo);
      recoverCamera();
      window.addEventListener('beforeunload',e=>{if(cameraPending.size){e.preventDefault();e.returnValue=''}});
      document.addEventListener('keydown',e=>{if(e.key.toLowerCase()==='h'&&!['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))document.body.classList.toggle('clean')});
      async function cameraHeartbeat(){
        if(cameraModeBusy)return;cameraModeBusy=true;
        try{
          syncInfo.textContent=cameraPending.size?'Waiting to sync · '+cameraPending.size+' saved batches':'All reps synced';
          const response=await fetch('/api/camera',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({heartbeat:true,page_id:cameraPageId,telemetry:{camera_live:!!cameraStream?.getVideoTracks().some(t=>t.readyState==='live'&&!t.muted),model_ready:!!poseDetector,body_detected:Date.now()-lastBodySeen<2000,storage_ok:cameraStorageOk,actual_mode:cameraMode,pending:cameraPending.size}}),signal:AbortSignal.timeout(4000)});
          if(!response.ok)throw Error('Control connection unavailable');
          const state=await response.json();
          if(!state.owns_camera){cameraLeaseUntil=0;stopCameraStream();streamStarted=false;throw Error('Another camera page owns capture. Close it and wait 8 seconds, then Start Camera here.');}
          cameraLeaseUntil=Date.now()+3500;
          if(!cameraStorageOk&&cameraPending.size===0)throw Error('Local storage unavailable; capture disabled');
          await flushCameraCounts();
          const newTicket=state.queue?.run||null;
          if(newTicket!==queueTicket){lastDepth='up';downCandidateFrames=0;upCandidateFrames=0;queueTicket=newTicket;}
          if(state.mode!==cameraMode){
            // Disable counting while the model loads or a mode change is pending.
            cameraMode='webcam';document.body.dataset.cameraMode='webcam';
            lastDepth='up';downCandidateFrames=0;upCandidateFrames=0;cooldownFrames=0;
            if(state.mode==='capture')await ensurePoseLandmarker();
            cameraMode=state.mode;document.body.dataset.cameraMode=cameraMode;
            bannerEl.textContent='Squat capture';targetEl.textContent='reps this window';
          }
          const head=state.queue?.items?.[0];
          if(queueTicket&&head){bannerEl.textContent=head.viewer+' · '+head.title;targetEl.textContent=head.done+' / '+head.target+' · queued challenge';}
          else{bannerEl.textContent='Free capture';targetEl.textContent='reps this window';}
          warning.textContent=errorBoxEl ? errorBoxEl.textContent : '';
        }catch(e){cameraLeaseUntil=0;cameraMode='webcam';lastDepth='up';downCandidateFrames=0;upCandidateFrames=0;document.body.dataset.cameraMode='webcam';warning.textContent='Capture paused: '+e.message}
        finally{cameraModeBusy=false}
      }
      cameraHeartbeat();setInterval(cameraHeartbeat,1500);
    }
    fetch("/api/stats").then(function (response) { return response.json(); }).then(function (stats) {
      owedCountEl.textContent = String(stats.owed_squats || 0);
      completedCountEl.textContent = String(stats.completed_squats || 0);
    }).catch(function () {});
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

OVERLAY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Twitch Squat Overlay</title>
  <style>
    :root {
      --accent: #66f0c9;
      --accent-2: #ffb347;
      --danger: #ff6b8a;
      --text: #f7fbff;
      --muted: #b7c3d8;
      --panel: rgba(12, 16, 28, 0.78);
    }
    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: transparent;
      color: var(--text);
      font-family: ui-rounded, "SF Pro Rounded", "Avenir Next", "Trebuchet MS", sans-serif;
    }
    .overlay {
      position: fixed;
      left: 28px;
      bottom: 28px;
      width: 430px;
      padding: 18px 20px;
      border-radius: 24px;
      background:
        radial-gradient(circle at top left, rgba(102, 240, 201, 0.22), transparent 42%),
        linear-gradient(145deg, rgba(16, 21, 36, 0.86), rgba(10, 13, 22, 0.76));
      border: 1px solid rgba(255, 255, 255, 0.12);
      box-shadow: 0 20px 70px rgba(0, 0, 0, 0.42);
      backdrop-filter: blur(12px);
      opacity: 0;
      transform: translateY(16px);
      transition: opacity 220ms ease, transform 220ms ease;
    }
    .overlay.visible {
      opacity: 1;
      transform: translateY(0);
    }
    .top-row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
      margin-bottom: 12px;
    }
    .eyebrow {
      color: var(--accent);
      font-size: 12px;
      font-weight: 900;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    h1 {
      margin: 4px 0 0;
      font-size: 28px;
      line-height: 1;
      text-shadow: 0 3px 22px rgba(0, 0, 0, 0.5);
    }
    .lock-pill {
      flex: 0 0 auto;
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 12px;
      font-weight: 900;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      background: rgba(255, 179, 71, 0.14);
      border: 1px solid rgba(255, 179, 71, 0.38);
      color: #ffd89b;
    }
    .lock-pill.complete {
      background: rgba(102, 240, 201, 0.14);
      border-color: rgba(102, 240, 201, 0.42);
      color: #a8ffe9;
    }
    .message {
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.35;
    }
    .viewer {
      color: var(--text);
      font-weight: 900;
    }
    .count-row {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 10px;
    }
    .count {
      font-size: 54px;
      line-height: 0.9;
      font-weight: 1000;
      letter-spacing: -0.04em;
    }
    .target {
      color: var(--muted);
      font-size: 15px;
      font-weight: 800;
    }
    .bar {
      height: 14px;
      border-radius: 999px;
      overflow: hidden;
      background: rgba(255, 255, 255, 0.12);
      border: 1px solid rgba(255, 255, 255, 0.08);
    }
    .fill {
      height: 100%;
      width: 0%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
      box-shadow: 0 0 22px rgba(102, 240, 201, 0.55);
      transition: width 260ms ease;
    }
    .footer {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-top: 12px;
      color: rgba(247, 251, 255, 0.72);
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
  </style>
</head>
<body>
  <style>
    .overlay{left:16px;bottom:16px;width:min(420px,calc(100vw - 32px));padding:20px;border-radius:20px;background:linear-gradient(140deg,rgba(24,33,46,.97),rgba(10,15,24,.97));border:1px solid #ffffff20;box-shadow:0 8px 24px #0004;backdrop-filter:none;font-family:Inter,"Segoe UI",sans-serif;overflow:hidden}
    .overlay:before{content:"";position:absolute;top:0;left:22px;right:22px;height:2px;background:linear-gradient(90deg,#68efd0,transparent)}
    .top-row{align-items:center;margin:0 0 18px}.brand-mark{display:flex;align-items:center;gap:10px}.mark{width:34px;height:34px;border-radius:11px;display:grid;place-items:center;background:#68efd015;color:#68efd0}.icon{width:19px;height:19px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
    h1{font-size:15px;letter-spacing:-.02em;margin:0;text-shadow:none;font-weight:750}.eyebrow{font-size:9px;letter-spacing:.16em;color:#8d9eb6;margin-top:4px;font-weight:600}
    .lock-pill{padding:6px 9px;font-size:9px;letter-spacing:.09em;border-color:#ffffff12;background:#ffffff06;color:#a7b5c9;display:flex;align-items:center;gap:6px}.lock-pill:before{content:"";height:5px;width:5px;border-radius:50%;background:currentColor}.overlay[data-state="active"] .lock-pill{color:#ffbf7d;background:#ffb36b10;border-color:#ffb36b30}.lock-pill.complete{color:#68efd0;background:#68efd010;border-color:#68efd030}
    .totals{display:grid;grid-template-columns:1fr 1fr;gap:10px}.total{padding:14px;border:1px solid #ffffff0b;border-radius:12px;background:#ffb36b08;min-width:0}.total.done{background:#68efd008}.total-label{display:flex;align-items:center;gap:6px;font-size:10px;font-weight:650;letter-spacing:.1em;color:#a7b5c9;text-transform:uppercase}.total-label .icon{width:13px;height:13px}.total strong{display:block;color:#ffbf7d;font-size:38px;line-height:1.2;font-weight:750;letter-spacing:-.04em;font-variant-numeric:tabular-nums;margin-top:8px;overflow-wrap:anywhere}.total.done strong{color:#68efd0}.total small{font-size:10px;color:#8292a9}
    .challenge{margin-top:16px;padding-top:16px;border-top:1px solid #ffffff12}.count-row{align-items:center;margin-bottom:12px}.count-group{display:flex;align-items:baseline;gap:8px;min-width:0}.count{font-size:46px;font-weight:750;line-height:1;overflow-wrap:anywhere}.target{font-size:13px;font-weight:500;color:#8d9eb6}.bar{height:5px;border:0;background:#ffffff10}.fill{background:linear-gradient(90deg,#36cfa9,#8bf7dc);box-shadow:none}.message{margin:12px 0 0;font-size:12px;color:#a7b5c9;overflow-wrap:anywhere}.footer{margin-top:14px;padding-top:12px;border-top:1px solid #ffffff0b;font-size:10px;font-weight:500;letter-spacing:.02em;text-transform:none;color:#8292a9}.footer span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.footer #viewer{max-width:72%}
    .overlay[data-state="idle"] .challenge,.overlay[data-state="skipped"] .count-row,.overlay[data-state="skipped"] .bar{display:none}.overlay[data-state="skipped"] .message{margin:0}.overlay[data-state="complete"] .count{color:#68efd0}
    @media(max-width:340px){.overlay{padding:14px;left:8px;bottom:8px;width:calc(100vw - 16px)}.total{padding:10px}.total strong{font-size:30px}.top-row{gap:6px}h1{font-size:13px}}
    @media(prefers-reduced-motion:reduce){.overlay,.fill{transition:none}}
  </style>
  <main id="overlay" class="overlay visible" data-state="idle" aria-label="Squat Capture live stats">
    <div class="top-row">
      <div class="brand-mark"><span class="mark"><svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg></span><div><h1>Squat Capture</h1><div class="eyebrow">EVERY REP COUNTS</div></div></div>
      <div id="lockPill" class="lock-pill">Standby</div>
    </div>
    <div class="totals">
      <div class="total"><div class="total-label"><svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>Owed</div><strong id="owed">0</strong><small>overall remaining</small></div>
      <div class="total done"><div class="total-label"><svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg>Completed</div><strong id="completed">0</strong><small id="sessionLabel">checking Twitch session</small></div>
    </div>
    <div class="challenge">
    <div class="count-row">
      <div class="count-group">
        <div id="count" class="count">0</div>
        <div id="target" class="target">/ 0 reps</div>
      </div>
      <div id="percent" class="target">0%</div>
    </div>
    <div class="bar"><div id="fill" class="fill"></div></div>
    <p id="message" class="message"></p>
    </div>
    <div class="footer">
      <span id="viewer">Your next rep starts here</span>
      <span id="status">Ready</span>
    </div>
  </main>
  <script>
    const overlayEventsPath = "%OVERLAY_EVENTS_PATH%";
    const overlayStatePath = "%OVERLAY_STATE_PATH%";
    const overlayEl = document.getElementById("overlay");
    const lockPillEl = document.getElementById("lockPill");
    const messageEl = document.getElementById("message");
    const countEl = document.getElementById("count");
    const targetEl = document.getElementById("target");
    const percentEl = document.getElementById("percent");
    const fillEl = document.getElementById("fill");
    const viewerEl = document.getElementById("viewer");
    const owedEl = document.getElementById("owed");
    const completedEl = document.getElementById("completed");
    const statusEl = document.getElementById("status");
    let hideTimer = null;
    let lastOverlaySignature = "";

    function showOverlay() {
      overlayEl.classList.add("visible");
      if (hideTimer) {
        clearTimeout(hideTimer);
        hideTimer = null;
      }
    }

    function maybeHideOverlay(state) {
      return;
    }

    function updateOverlay(state) {
      if (!state || !state.status) return;
      const stateSignature = [
        state.sequence || "",
        state.status || "",
        state.locked ? "1" : "0",
        state.user_login || "",
        state.user_name || "",
        state.reward_title || "",
        state.squat_count || 0,
        state.squat_target || 0,
        state.owed_squats || 0,
        state.completed_squats || 0,
        state.stream_status || "unknown",
        state.progress_updated_at || "",
      ].join("|");
      if (stateSignature === lastOverlaySignature) return;
      lastOverlaySignature = stateSignature;

      const squatCount = Number(state.squat_count || 0);
      const squatTarget = Number(state.squat_target || 0);
      const percent = squatTarget > 0 ? Math.min(100, Math.round(squatCount / squatTarget * 100)) : 0;
      const viewer = state.user_name || state.user_login || "No active viewer";
      const reward = state.reward_title || "squat redeem";

      countEl.textContent = String(squatCount);
      overlayEl.dataset.state = ['active','complete','skipped'].includes(state.status) ? state.status : 'idle';
      targetEl.textContent = "/ " + squatTarget + " reps";
      percentEl.textContent = percent + "%";
      fillEl.style.width = percent + "%";
      viewerEl.textContent = viewer;
      owedEl.textContent = Number(state.owed_squats || 0).toLocaleString('en-US');
      completedEl.textContent = Number(state.completed_squats || 0).toLocaleString('en-US');
      document.getElementById('sessionLabel').textContent = state.stream_status === 'live' ? 'this stream' : state.stream_status === 'offline' ? 'last stream · offline' : 'session · Twitch unavailable';

      if (state.status === "complete") {
        lockPillEl.textContent = "Unlocked";
        lockPillEl.classList.add("complete");
        statusEl.textContent = "Complete";
        messageEl.textContent = "Challenge complete. Nicely done!";
      } else if (state.status === "active") {
        lockPillEl.textContent = state.locked ? "Locked" : "Active";
        lockPillEl.classList.remove("complete");
        statusEl.textContent = "In Progress";
        messageEl.textContent = reward;
      } else if (state.status === "skipped") {
        lockPillEl.textContent = "Skipped";
        lockPillEl.classList.remove("complete");
        statusEl.textContent = "Skipped";
        messageEl.textContent = state.message || "Redeem skipped.";
      } else {
        lockPillEl.textContent = "Standby";
        lockPillEl.classList.remove("complete");
        statusEl.textContent = "Ready";
        viewerEl.textContent = "Your next rep starts here";
        messageEl.textContent = "";
      }

      showOverlay();
      maybeHideOverlay(state);
    }

    function connectOverlayEvents() {
      const eventSource = new EventSource(overlayEventsPath);
      eventSource.onmessage = function (message) {
        updateOverlay(JSON.parse(message.data));
      };
      eventSource.onerror = function () {
        pollOverlayState();
      };
    }

    async function pollOverlayState() {
      try {
        const response = await fetch(overlayStatePath + "?_=" + Date.now(), {
          cache: "no-store",
        });
        if (!response.ok) return;
        updateOverlay(await response.json());
      } catch (error) {
        // Streamlabs browser sources can be noisy; the next poll will try again.
      }
    }

    connectOverlayEvents();
    pollOverlayState();
    setInterval(pollOverlayState, 1000);
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
        self.session_squats_accepted = 0
        self.current_squat_count = 0
        self.current_squat_target = 0
        self.last_progress_at = 0.0

    def remaining_session_squats(self):
        if MAX_SESSION_SQUATS <= 0:
            return None
        return max(0, MAX_SESSION_SQUATS - self.session_squats_accepted)

    def can_accept(self, squat_target):
        remaining = self.remaining_session_squats()
        if remaining is None:
            return True, "session_limit_disabled", None
        if squat_target <= remaining:
            return True, "within_session_limit", remaining
        return False, "session_squat_limit_reached", remaining

    def publish(self, redemption):
        with self.condition:
            squat_target = extract_squat_target(redemption.get("reward_title"))
            can_accept, reason, remaining = self.can_accept(squat_target)
            if not can_accept:
                return None, {
                    "accepted": False,
                    "reason": reason,
                    "requested_squats": squat_target,
                    "session_squats_accepted": self.session_squats_accepted,
                    "max_session_squats": MAX_SESSION_SQUATS,
                    "remaining_session_squats": remaining,
                }

            self.sequence += 1
            payload = dict(redemption)
            payload["sequence"] = self.sequence
            payload["squat_target"] = squat_target
            self.session_squats_accepted += squat_target
            payload["session_squats_accepted"] = self.session_squats_accepted
            payload["queue_squat_target"] = self.session_squats_accepted
            payload["max_session_squats"] = MAX_SESSION_SQUATS
            payload["remaining_session_squats"] = self.remaining_session_squats()
            self.current_squat_target = self.session_squats_accepted
            self.current_job = payload
            self.condition.notify_all()
            return payload, {
                "accepted": True,
                "reason": reason,
                "requested_squats": squat_target,
                "session_squats_accepted": self.session_squats_accepted,
                "queue_squat_target": self.session_squats_accepted,
                "max_session_squats": MAX_SESSION_SQUATS,
                "remaining_session_squats": self.remaining_session_squats(),
            }

    def record_progress(self, progress_payload, squat_target=None):
        with self.condition:
            try:
                squat_count = max(0, int(progress_payload.get("squat_count", 0)))
            except (TypeError, ValueError):
                squat_count = self.current_squat_count

            if squat_target is None:
                reported_target = progress_payload.get("squat_target", self.current_squat_target)
                try:
                    squat_target = int(reported_target)
                except (TypeError, ValueError):
                    squat_target = self.current_squat_target

            squat_target = max(
                0,
                int(squat_target or 0),
                int(self.session_squats_accepted or 0),
                int(self.current_squat_target or 0),
            )
            self.current_squat_count = min(squat_count, squat_target) if squat_target else squat_count
            self.current_squat_target = squat_target
            self.last_progress_at = time.time()
            return {
                "squat_count": self.current_squat_count,
                "squat_target": self.current_squat_target,
                "progress_updated_at": self.last_progress_at,
            }

    def progress_snapshot(self):
        with self.condition:
            return {
                "squat_count": self.current_squat_count,
                "squat_target": self.current_squat_target,
                "progress_updated_at": self.last_progress_at,
            }

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


class ChallengeOverlayState:
    def __init__(self):
        self.condition = threading.Condition()
        self.sequence = 0
        self.state = {
            "status": "idle",
            "locked": False,
            "user_login": None,
            "user_name": None,
            "reward_title": None,
            "squat_count": 0,
            "squat_target": 0,
            "message": "Waiting for a channel point redeem.",
            "updated_at": time.time(),
        }

    def publish(self, updates):
        with self.condition:
            self.sequence += 1
            self.state.update(updates)
            self.state["sequence"] = self.sequence
            self.state["updated_at"] = time.time()
            snapshot = dict(self.state)
            self.condition.notify_all()
            return snapshot

    def snapshot(self):
        with self.condition:
            snapshot = dict(self.state)
            snapshot["sequence"] = self.sequence
            return snapshot

    def wait_for_next(self, last_seen_sequence, timeout=25.0):
        with self.condition:
            if self.sequence > last_seen_sequence:
                return dict(self.state)

            self.condition.wait(timeout)
            if self.sequence > last_seen_sequence:
                return dict(self.state)
            return None


OVERLAY_STATE = ChallengeOverlayState()
SOFT_LOCK_STATE = {
    "locked": False,
    "sequence": None,
    "started_at": None,
    "released_at": None,
}
SOFT_LOCK_STATE_LOCK = threading.Lock()


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
    if CAMERA_CONTROL.snapshot()["page_connected"]:
        return
    if not AUTO_OPEN_POPUP:
        return

    now = time.time()
    if now - POPUP_STATE.last_popup_connected_at < 20:
        return

    if now - POPUP_STATE.last_popup_opened_at < 2:
        return

    open_commands = [
        ["explorer.exe", POPUP_OPEN_URL],
        ["wslview", POPUP_OPEN_URL],
        ["xdg-open", POPUP_OPEN_URL],
        ["open", POPUP_OPEN_URL],
    ]
    errors = []
    for command in open_commands:
        try:
            subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            POPUP_STATE.last_popup_opened_at = now
            print(
                json.dumps({"popup_opened": True, "command": command[0], "url": POPUP_OPEN_URL}),
                flush=True,
            )
            return
        except OSError as error:
            errors.append(f"{command[0]}:{error}")

    print(
        json.dumps(
            {
                "popup_open_error": "no_supported_open_command",
                "attempts": errors,
                "url": POPUP_OPEN_URL,
            }
        ),
        flush=True,
    )


def soft_lock_game_windows(popup_job):
    if not SOFT_LOCK_ENABLED:
        return {"enabled": False, "locked": False, "reason": "soft_lock_disabled"}

    powershell_script = r"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WindowTools {
    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
}
"@

$targets = @(
    "League of Legends",
    "LeagueClient",
    "LeagueClientUx",
    "LeagueClientUxRender",
    "Riot Client",
    "RiotClientServices"
)

$matched = @()
Get-Process | Where-Object { $_.MainWindowHandle -ne 0 } | ForEach-Object {
    $process = $_
    $isTarget = $targets -contains $process.ProcessName
    if (-not $isTarget -and $process.MainWindowTitle) {
        foreach ($target in $targets) {
            if ($process.MainWindowTitle -like "*$target*") {
                $isTarget = $true
                break
            }
        }
    }

    if ($isTarget) {
        [WindowTools]::ShowWindowAsync($process.MainWindowHandle, 6) | Out-Null
        $matched += [PSCustomObject]@{
            process = $process.ProcessName
            title = $process.MainWindowTitle
        }
    }
}

$matched | ConvertTo-Json -Compress
"""

    with SOFT_LOCK_STATE_LOCK:
        SOFT_LOCK_STATE["locked"] = True
        SOFT_LOCK_STATE["sequence"] = popup_job.get("sequence")
        SOFT_LOCK_STATE["started_at"] = time.time()
        SOFT_LOCK_STATE["released_at"] = None

    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", powershell_script],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as error:
        return {
            "enabled": True,
            "locked": True,
            "window_action": "failed",
            "reason": str(error),
            "sequence": popup_job.get("sequence"),
        }

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    return {
        "enabled": True,
        "locked": True,
        "window_action": "minimize",
        "returncode": result.returncode,
        "matched_windows": stdout,
        "error": stderr,
        "sequence": popup_job.get("sequence"),
    }


def release_soft_lock(completion_payload):
    with SOFT_LOCK_STATE_LOCK:
        was_locked = SOFT_LOCK_STATE["locked"]
        SOFT_LOCK_STATE["locked"] = False
        SOFT_LOCK_STATE["released_at"] = time.time()
        released_sequence = SOFT_LOCK_STATE["sequence"]

    return {
        "released": was_locked,
        "sequence": released_sequence,
        "completion": completion_payload,
    }


def publish_overlay_active(popup_job, soft_lock_result=None):
    locked = bool(soft_lock_result and soft_lock_result.get("locked"))
    queued_target = (
        popup_job.get("queue_squat_target")
        or popup_job.get("session_squats_accepted")
        or popup_job.get("squat_target")
        or DEFAULT_SQUAT_TARGET
    )
    stats = APP_STATS.snapshot()
    return OVERLAY_STATE.publish(
        {
            "status": "active",
            "locked": locked,
            "user_login": popup_job.get("user_login"),
            "user_name": popup_job.get("user_name"),
            "reward_title": popup_job.get("reward_title"),
            "squat_count": 0,
            "squat_target": queued_target,
            "message": "Redeem received. Squat challenge started.",
            "session_squats_accepted": popup_job.get("session_squats_accepted"),
            "max_session_squats": popup_job.get("max_session_squats"),
            "remaining_session_squats": popup_job.get("remaining_session_squats"),
            "owed_squats": stats["owed_squats"],
            "completed_squats": stats["completed_squats"],
        }
    )


def publish_overlay_progress(progress_payload):
    status = progress_payload.get("status") or "active"
    with SOFT_LOCK_STATE_LOCK:
        locked = status == "active" and bool(SOFT_LOCK_STATE["locked"])
    reported_target = progress_payload.get("squat_target", DEFAULT_SQUAT_TARGET)
    try:
        squat_target = max(int(reported_target), int(POPUP_STATE.session_squats_accepted))
    except (TypeError, ValueError):
        squat_target = POPUP_STATE.session_squats_accepted or DEFAULT_SQUAT_TARGET
    progress_state = POPUP_STATE.record_progress(progress_payload, squat_target)
    stats = APP_STATS.record_count(
        progress_payload.get("capture_session_id"),
        progress_state["squat_count"],
    )

    return OVERLAY_STATE.publish(
        {
            "status": status,
            "locked": locked,
            "user_login": progress_payload.get("user_login"),
            "user_name": progress_payload.get("user_name"),
            "reward_title": progress_payload.get("reward_title"),
            "squat_count": progress_state["squat_count"],
            "squat_target": progress_state["squat_target"],
            "message": "Squat progress updated.",
            "progress_updated_at": progress_state["progress_updated_at"],
            "owed_squats": stats["owed_squats"],
            "completed_squats": stats["completed_squats"],
        }
    )


def publish_overlay_skipped(reason, user_login=None, reward_title=None):
    return OVERLAY_STATE.publish(
        {
            "status": "skipped",
            "locked": False,
            "user_login": user_login,
            "user_name": user_login,
            "reward_title": reward_title,
            "squat_count": 0,
            "squat_target": 0,
            "message": f"Redeem skipped: {reason}",
        }
    )


def html_escape(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def build_refresh_overlay_html(page_background="rgba(0, 0, 0, 0)"):
    state = OVERLAY_STATE.snapshot()
    if state.get("status") in ("active", "complete"):
        state.update(POPUP_STATE.progress_snapshot())
    status = state.get("status") or "idle"
    viewer = state.get("user_name") or state.get("user_login") or "No active viewer"
    reward = state.get("reward_title") or "squat redeem"
    squat_count = int(state.get("squat_count") or 0)
    squat_target = int(state.get("squat_target") or 0)
    percent = min(100, round(squat_count / squat_target * 100)) if squat_target > 0 else 0

    if status == "complete":
        pill = "Unlocked"
        pill_class = "pill complete"
        message = f"{viewer}'s challenge is complete."
        footer_status = "Complete"
    elif status == "active":
        pill = "Locked" if state.get("locked") else "Active"
        pill_class = "pill"
        message = f"{viewer} redeemed {reward}."
        footer_status = "In Progress"
    elif status == "skipped":
        pill = "Skipped"
        pill_class = "pill"
        message = state.get("message") or "Redeem skipped."
        footer_status = "Skipped"
    else:
        pill = "Waiting"
        pill_class = "pill"
        message = "Waiting for a channel point redeem..."
        footer_status = "Idle"

    visible_class = "visible"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Twitch Squat Overlay Refresh</title>
  <style>
    * {{ box-sizing: border-box; }}
    :root {{
      background: {page_background} !important;
    }}
    html, body {{
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: {page_background} !important;
      color: #f7fbff;
      font-family: ui-rounded, "SF Pro Rounded", "Avenir Next", "Trebuchet MS", sans-serif;
    }}
    .overlay {{
      position: fixed;
      left: 28px;
      bottom: 28px;
      width: 430px;
      padding: 18px 20px;
      border-radius: 24px;
      background:
        radial-gradient(circle at top left, rgba(102, 240, 201, 0.22), transparent 42%),
        linear-gradient(145deg, rgba(16, 21, 36, 0.86), rgba(10, 13, 22, 0.76));
      border: 1px solid rgba(255, 255, 255, 0.12);
      box-shadow: 0 20px 70px rgba(0, 0, 0, 0.42);
      backdrop-filter: blur(12px);
      opacity: 0;
    }}
    .overlay.visible {{ opacity: 1; }}
    .top {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 12px; }}
    .eyebrow {{ color: #66f0c9; font-size: 12px; font-weight: 900; letter-spacing: 0.14em; text-transform: uppercase; }}
    h1 {{ margin: 4px 0 0; font-size: 28px; line-height: 1; }}
    .pill {{ border-radius: 999px; padding: 8px 12px; font-size: 12px; font-weight: 900; letter-spacing: 0.06em; text-transform: uppercase; background: rgba(255, 179, 71, 0.14); border: 1px solid rgba(255, 179, 71, 0.38); color: #ffd89b; }}
    .pill.complete {{ background: rgba(102, 240, 201, 0.14); border-color: rgba(102, 240, 201, 0.42); color: #a8ffe9; }}
    .message {{ margin: 0 0 14px; color: #b7c3d8; font-size: 15px; line-height: 1.35; font-weight: 800; }}
    .count-row {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 10px; }}
    .count {{ font-size: 54px; line-height: 0.9; font-weight: 1000; letter-spacing: -0.04em; }}
    .target {{ color: #b7c3d8; font-size: 15px; font-weight: 800; }}
    .bar {{ height: 14px; border-radius: 999px; overflow: hidden; background: rgba(255, 255, 255, 0.12); border: 1px solid rgba(255, 255, 255, 0.08); }}
    .fill {{ height: 100%; width: {percent}%; border-radius: inherit; background: linear-gradient(90deg, #66f0c9, #ffb347); box-shadow: 0 0 22px rgba(102, 240, 201, 0.55); }}
    .footer {{ display: flex; justify-content: space-between; gap: 12px; margin-top: 12px; color: rgba(247, 251, 255, 0.72); font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.08em; }}
  </style>
</head>
<body>
  <main id="overlay" class="overlay {visible_class}">
    <div class="top">
      <div>
        <div class="eyebrow">Live Redeem Challenge</div>
        <h1>Squat Lock</h1>
      </div>
      <div id="pill" class="{pill_class}">{html_escape(pill)}</div>
    </div>
    <p id="message" class="message">{html_escape(message)}</p>
    <div class="count-row">
      <div>
        <div id="count" class="count">{squat_count}</div>
        <div id="target" class="target">of {squat_target} squats</div>
      </div>
      <div id="percent" class="target">{percent}%</div>
    </div>
    <div class="bar"><div id="fill" class="fill"></div></div>
    <div class="footer">
      <span id="viewer">{html_escape(viewer)}</span>
      <span id="footerStatus">{html_escape(footer_status)}</span>
    </div>
  </main>
  <script>
    const overlayStatePath = "{OVERLAY_STATE_PATH}";
    const overlayEl = document.getElementById("overlay");
    const pillEl = document.getElementById("pill");
    const messageEl = document.getElementById("message");
    const countEl = document.getElementById("count");
    const targetEl = document.getElementById("target");
    const percentEl = document.getElementById("percent");
    const fillEl = document.getElementById("fill");
    const viewerEl = document.getElementById("viewer");
    const footerStatusEl = document.getElementById("footerStatus");
    let lastSignature = "";

    function setText(element, text) {{
      element.textContent = text == null ? "" : String(text);
    }}

    function updateOverlay(state) {{
      if (!state || !state.status) return;
      const stateSignature = [
        state.sequence || "",
        state.status || "",
        state.locked ? "1" : "0",
        state.user_login || "",
        state.user_name || "",
        state.reward_title || "",
        state.squat_count || 0,
        state.squat_target || 0,
        state.progress_updated_at || "",
      ].join("|");
      if (stateSignature === lastSignature) return;
      lastSignature = stateSignature;

      const status = state.status || "idle";
      const viewer = state.user_name || state.user_login || "No active viewer";
      const reward = state.reward_title || "squat redeem";
      const squatCount = Number(state.squat_count || 0);
      const squatTarget = Number(state.squat_target || 0);
      const progress = squatTarget > 0 ? Math.min(100, Math.round(squatCount / squatTarget * 100)) : 0;

      overlayEl.classList.add("visible");
      setText(countEl, squatCount);
      setText(targetEl, "of " + squatTarget + " squats");
      setText(percentEl, progress + "%");
      fillEl.style.width = progress + "%";
      setText(viewerEl, viewer);

      if (status === "complete") {{
        setText(pillEl, "Unlocked");
        pillEl.className = "pill complete";
        setText(messageEl, viewer + "'s challenge is complete.");
        setText(footerStatusEl, "Complete");
      }} else if (status === "active") {{
        setText(pillEl, state.locked ? "Locked" : "Active");
        pillEl.className = "pill";
        setText(messageEl, viewer + " redeemed " + reward + ".");
        setText(footerStatusEl, "In Progress");
      }} else if (status === "skipped") {{
        setText(pillEl, "Skipped");
        pillEl.className = "pill";
        setText(messageEl, state.message || "Redeem skipped.");
        setText(footerStatusEl, "Skipped");
      }} else {{
        setText(pillEl, "Waiting");
        pillEl.className = "pill";
        setText(messageEl, "Waiting for a channel point redeem...");
        setText(footerStatusEl, "Idle");
      }}
    }}

    async function pollOverlayState() {{
      try {{
        const response = await fetch(overlayStatePath + "?_=" + Date.now(), {{
          cache: "no-store",
        }});
        if (!response.ok) return;
        updateOverlay(await response.json());
      }} catch (error) {{
        // Try again on the next interval.
      }}
    }}

    pollOverlayState();
    setInterval(pollOverlayState, 1000);
  </script>
</body>
</html>
"""


def should_trigger_popup_from_riot_check():
    configured_enabled = APP_CONFIG.get("riot_check_enabled")
    riot_check_enabled = configured_enabled == "1" if configured_enabled != "" else RIOT_CHECK_ENABLED
    if not riot_check_enabled:
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
        return False, "riot_in_game_or_unknown"

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

    configured_login = APP_CONFIG.get("broadcaster_login") or BROADCASTER_LOGIN
    configured_reward_id = APP_CONFIG.get("target_reward_id") or TARGET_REWARD_ID
    configured_reward_title = APP_CONFIG.get("target_reward_title") or TARGET_REWARD_TITLE
    if not configured_reward_id and not configured_reward_title:
        return None
    if configured_login and broadcaster_login != configured_login.lower():
        return None

    if configured_reward_id and reward_id != configured_reward_id:
        return None

    if not configured_reward_id and configured_reward_title and reward_title != configured_reward_title:
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


def process_eventsub_notification(payload):
    if SUPPORT_SERVICE.twitch(payload):
        return
    if payload.get('subscription', {}).get('type') != 'channel.channel_points_custom_reward_redemption.add':
        return
    matched = get_matching_redemption(payload)
    if not matched:
        return
    event = payload.get('event', {})
    if not event.get('id') or event.get('status') == 'canceled':
        return
    import re
    amount = re.search(r'\d+', matched.get('reward_title') or '')
    target = int(amount.group()) if amount else DEFAULT_SQUAT_TARGET
    APP_STATS.enqueue(str(event.get('broadcaster_user_id', '')) + ':' + event['id'],
                      matched.get('user_name') or matched.get('user_login') or 'Viewer',
                      matched.get('reward_title') or 'Squats', target)
    OVERLAY_STATE.publish(APP_STATS.snapshot())


def legacy_process_eventsub_notification(payload):
    """Shared notification path for WebSocket and legacy webhook transports."""
    if SUPPORT_SERVICE.twitch(payload):
        return
    if CAMERA_CONTROL.snapshot()["page_connected"]:
        publish_overlay_skipped("Camera Overlay is in manual mode; switch to Capture in /control", "", "")
        return
    summary = summarize_redemption(payload)
    print(json.dumps({"incoming_redemption": summary}), flush=True)
    matched = get_matching_redemption(payload)
    if matched is None:
        print(json.dumps({"matched": False}), flush=True)
        return

    user_login = matched.get("user_login") or "unknown_user"
    reward_title = matched.get("reward_title") or "unknown_reward"
    should_trigger, trigger_reason = should_trigger_popup_from_riot_check()
    print(json.dumps({"riot_gate": {"allowed": should_trigger, "reason": trigger_reason,
        "user_login": user_login, "reward_title": reward_title}}), flush=True)
    if not should_trigger:
        publish_overlay_skipped(trigger_reason, user_login, reward_title)
        return

    popup_job, session_limit = POPUP_STATE.publish(matched)
    print(json.dumps({"session_limit": session_limit}), flush=True)
    if popup_job is None:
        publish_overlay_skipped(session_limit["reason"], user_login, reward_title)
        return

    soft_lock_result = soft_lock_game_windows(popup_job)
    print(json.dumps({"soft_lock": soft_lock_result}), flush=True)
    print(json.dumps({"overlay": publish_overlay_active(popup_job, soft_lock_result)}), flush=True)
    maybe_open_popup()
    print(f"{user_login} redeemed {reward_title}", flush=True)


SUPPORT_SERVICE = SupportService(APP_CONFIG, APP_STATS, OVERLAY_STATE.publish)
def update_stream_session(stream_id, status):
    stats = APP_STATS.observe_stream(stream_id, status)
    OVERLAY_STATE.publish(stats)


TWITCH_SERVICE = TwitchService(APP_CONFIG, process_eventsub_notification, update_stream_session)


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

    def safe_write(self, body):
        try:
            self.wfile.write(body)
            return True
        except (BrokenPipeError, ConnectionResetError):
            print(json.dumps({"client_disconnected": self.path}), flush=True)
            return False

    def send_json_response(self, status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.safe_write(body)

    def read_json_body(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def send_api_error(self, error):
        print(json.dumps({"control_api_error": str(error)}), flush=True)
        self.send_json_response(400, {"ok": False, "error": str(error)})

    def serve_control_page(self):
        body = CONTROL_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.safe_write(body)

    def serve_popup_page(self):
        html = (
            (POPUP_HTML.replace('</head>', CAMERA_STYLE + '</head>') if urlparse(self.path).path == '/camera-overlay' else POPUP_HTML)
            .replace("%POPUP_EVENTS_PATH%", POPUP_EVENTS_PATH)
            .replace("%SQUAT_PROGRESS_PATH%", SQUAT_PROGRESS_PATH)
            .replace("%SQUAT_COMPLETE_PATH%", SQUAT_COMPLETE_PATH)
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

    def serve_overlay_page(self):
        html = (
            OVERLAY_HTML
            .replace("%OVERLAY_EVENTS_PATH%", OVERLAY_EVENTS_PATH)
            .replace("%OVERLAY_STATE_PATH%", OVERLAY_STATE_PATH)
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.safe_write(html)

    def serve_overlay_refresh_page(self):
        html = build_refresh_overlay_html().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.safe_write(html)

    def serve_overlay_key_page(self):
        html = build_refresh_overlay_html("#00ff00").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.safe_write(html)

    def serve_overlay_magenta_key_page(self):
        html = build_refresh_overlay_html("#ff00ff").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.safe_write(html)

    def serve_overlay_events(self):
        last_event_id = self.headers.get("Last-Event-ID", "-1")
        try:
            last_seen_sequence = int(last_event_id or "-1")
        except ValueError:
            last_seen_sequence = -1

        event = OVERLAY_STATE.wait_for_next(last_seen_sequence, timeout=25.0)
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
            self.safe_write(payload)
            return

        event_id = event.get("sequence", 0)
        body = f"id: {event_id}\ndata: {json.dumps(event)}\n\n".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Connection", "keep-alive")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.safe_write(body)

    def serve_overlay_state(self):
        state = OVERLAY_STATE.snapshot()
        state.update(APP_STATS.snapshot())
        if state.get("status") in ("active", "complete"):
            progress_state = POPUP_STATE.progress_snapshot()
            state.update(
                {
                    "squat_count": progress_state["squat_count"],
                    "squat_target": progress_state["squat_target"],
                    "progress_updated_at": progress_state["progress_updated_at"],
                }
            )
        self.send_json_response(200, state)

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
            self.safe_write(payload)
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
        self.safe_write(body)

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/control":
            self.serve_control_page()
            return

        if parsed_path.path == "/api/settings":
            self.send_json_response(200, {
                "ok": True,
                "settings": APP_CONFIG.public(),
                "twitch": {**TWITCH_SERVICE.status, "auth_state": TWITCH_SERVICE.auth_state},
                "support": SUPPORT_SERVICE.status,
            })
            return

        if parsed_path.path == "/api/diagnostics":
            self.send_json_response(200, {"health": TWITCH_SERVICE.health(),
                "providers": dict(SUPPORT_SERVICE.status), "activity": APP_STATS.activity(),
                "events": SUPPORT_SERVICE.diagnostics()})
            return

        if parsed_path.path == "/api/stats":
            self.send_json_response(200, {"ok": True, **APP_STATS.snapshot()})
            return

        if parsed_path.path == "/api/twitch/rewards":
            try:
                self.send_json_response(200, {"ok": True, "rewards": TWITCH_SERVICE.rewards()})
            except Exception as error:
                self.send_api_error(error)
            return

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
                    "overlay_path": OVERLAY_PATH,
                    "overlay_refresh_path": OVERLAY_REFRESH_PATH,
                    "overlay_key_path": OVERLAY_KEY_PATH,
                    "overlay_magenta_key_path": OVERLAY_MAGENTA_KEY_PATH,
                    "overlay_events_path": OVERLAY_EVENTS_PATH,
                    "overlay_state_path": OVERLAY_STATE_PATH,
                    "squat_progress_path": SQUAT_PROGRESS_PATH,
                    "squat_complete_path": SQUAT_COMPLETE_PATH,
                    "auto_open_popup": AUTO_OPEN_POPUP,
                    "soft_lock_enabled": SOFT_LOCK_ENABLED,
                    "max_session_squats": MAX_SESSION_SQUATS,
                    "session_squats_accepted": POPUP_STATE.session_squats_accepted,
                    "remaining_session_squats": POPUP_STATE.remaining_session_squats(),
                },
            )
            return

        if parsed_path.path == "/api/camera":
            self.send_json_response(200, {**CAMERA_CONTROL.snapshot(), "queue": APP_STATS.queue_snapshot()})
            return

        if parsed_path.path == "/api/queue":
            self.send_json_response(200, APP_STATS.queue_snapshot())
            return

        if parsed_path.path == POPUP_PATH or parsed_path.path in ("/", "/camera-overlay"):
            self.serve_popup_page()
            return

        if parsed_path.path == POPUP_EVENTS_PATH:
            self.serve_popup_events()
            return

        if parsed_path.path == OVERLAY_PATH:
            self.serve_overlay_page()
            return

        if parsed_path.path == OVERLAY_REFRESH_PATH:
            self.serve_overlay_refresh_page()
            return

        if parsed_path.path == OVERLAY_KEY_PATH:
            self.serve_overlay_key_page()
            return

        if parsed_path.path == OVERLAY_MAGENTA_KEY_PATH:
            self.serve_overlay_magenta_key_page()
            return

        if parsed_path.path == OVERLAY_EVENTS_PATH:
            self.serve_overlay_events()
            return

        if parsed_path.path == OVERLAY_STATE_PATH:
            self.serve_overlay_state()
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/api/camera":
            try:
                payload = self.read_json_body()
                camera = CAMERA_CONTROL.update(payload)
                if payload.get('mode') == 'webcam':
                    APP_STATS.set_queue_active(False)
                self.send_json_response(200, {**camera, "queue": APP_STATS.queue_snapshot()})
            except (ValueError, TypeError) as error:
                self.send_api_error(error)
            return
        if parsed_path.path == "/api/queue":
            try:
                action = self.read_json_body().get('action')
                if action not in ('start', 'pause'):
                    raise ValueError('Choose start or pause')
                if action == 'start':
                    if not CAMERA_CONTROL.snapshot().get('telemetry', {}).get('camera_live'):
                        raise ValueError('Open Camera Overlay and start the camera first')
                    allowed, reason = should_trigger_popup_from_riot_check()
                    if not allowed:
                        raise ValueError('League check: ' + reason)
                queue = APP_STATS.set_queue_active(action == 'start')
                CAMERA_CONTROL.update({'mode': 'capture' if action == 'start' else 'webcam'})
                self.send_json_response(200, queue)
            except ValueError as error:
                self.send_api_error(error)
            return
        if parsed_path.path == "/api/camera/progress":
            try:
                payload = self.read_json_body()
                if not CAMERA_CONTROL.owns(payload.get('page_id')):
                    raise ValueError('Camera ownership expired; reconnect before syncing')
                count = payload.get("count")
                session = payload.get("capture_session_id")
                if not isinstance(count, int) or isinstance(count, bool) or count < 0 or count > 1000000 or not isinstance(session, str) or not 1 <= len(session) <= 100:
                    raise ValueError("Invalid camera progress")
                stats = APP_STATS.record_count("camera:" + session, count, payload.get('queue_run'))
                OVERLAY_STATE.publish(stats)
                self.send_json_response(200, stats)
            except (ValueError, TypeError) as error:
                self.send_api_error(error)
            return
        if parsed_path.path == "/api/test-rule":
            try:
                payload = self.read_json_body()
                result = SUPPORT_SERVICE.preview(payload.get("source"), payload.get("amount", 1), payload.get("currency"))
                self.send_json_response(200, {"test_only": True, **result})
            except (ValueError, TypeError, AttributeError) as error:
                self.send_api_error(ValueError("Invalid test input") if not isinstance(error, ValueError) else error)
            return
        if parsed_path.path == "/api/settings":
            try:
                values = self.read_json_body()
                old_twitch = (APP_CONFIG.get("subs_enabled"), APP_CONFIG.get("bits_enabled"))
                APP_CONFIG.update(values)
                SUPPORT_SERVICE.start()
                if old_twitch != (APP_CONFIG.get("subs_enabled"), APP_CONFIG.get("bits_enabled")):
                    TWITCH_SERVICE.reconfigure()
                self.send_json_response(200, {"ok": True, "settings": APP_CONFIG.public()})
            except ValueError as error:
                self.send_api_error(error)
            return

        if parsed_path.path == "/api/stats":
            try:
                payload = self.read_json_body()
                stats = APP_STATS.set_counters(
                    owed=payload.get("owed_squats"),
                    completed=payload.get("completed_squats"),
                )
                OVERLAY_STATE.publish(stats)
                self.send_json_response(200, {"ok": True, **stats})
            except ValueError as error:
                self.send_api_error(error)
            return

        if parsed_path.path == "/api/twitch/login":
            try:
                login = TWITCH_SERVICE.start_device_login()
                self.send_json_response(200, {"ok": True, **login})
            except Exception as error:
                self.send_api_error(error)
            return

        if parsed_path.path == "/api/riot/test":
            allowed, reason = should_trigger_popup_from_riot_check()
            self.send_json_response(200, {"ok": True, "allowed": allowed, "reason": reason})
            return

        if parsed_path.path == SQUAT_PROGRESS_PATH:
            raw_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            try:
                progress_payload = json.loads(raw_body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                progress_payload = {}

            overlay_update = publish_overlay_progress(progress_payload)
            print(json.dumps({"squat_progress": overlay_update}), flush=True)
            self.send_json_response(200, {"ok": True, "overlay": overlay_update})
            return

        if parsed_path.path == SQUAT_COMPLETE_PATH:
            raw_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            try:
                completion_payload = json.loads(raw_body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                completion_payload = {}

            release_result = release_soft_lock(completion_payload)
            overlay_update = publish_overlay_progress(
                dict(completion_payload, status="complete")
            )
            print(json.dumps({"soft_lock_released": release_result}), flush=True)
            self.send_json_response(
                200,
                {"ok": True, "soft_lock": release_result, "overlay": overlay_update},
            )
            return

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

        if message_type == 'notification':
            process_eventsub_notification({**payload, "message_id": message_id})
            self.send_response(204)
            self.end_headers()
            return

        if CAMERA_CONTROL.snapshot()["page_connected"]:
            publish_overlay_skipped("Camera Overlay is in manual mode; switch to Capture in /control", "", "")
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
                publish_overlay_skipped(trigger_reason, user_login, reward_title)
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

            popup_job, session_limit = POPUP_STATE.publish(matched)
            print(json.dumps({"session_limit": session_limit}), flush=True)
            if popup_job is None:
                publish_overlay_skipped(session_limit["reason"], user_login, reward_title)
                print(
                    json.dumps(
                        {
                            "redeemed": False,
                            "skipped": True,
                            "skip_reason": session_limit["reason"],
                            "user_login": user_login,
                            "reward_title": reward_title,
                            "requested_squats": session_limit["requested_squats"],
                            "session_squats_accepted": session_limit["session_squats_accepted"],
                            "max_session_squats": session_limit["max_session_squats"],
                            "remaining_session_squats": session_limit["remaining_session_squats"],
                        }
                    ),
                    flush=True,
                )
                self.send_response(204)
                self.end_headers()
                return

            soft_lock_result = soft_lock_game_windows(popup_job)
            print(json.dumps({"soft_lock": soft_lock_result}), flush=True)
            overlay_update = publish_overlay_active(popup_job, soft_lock_result)
            print(json.dumps({"overlay": overlay_update}), flush=True)
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
    from startup_check import dependency_errors, check_storage
    if dependency_errors():
        print("Startup blocked: missing / incompatible dependencies. Run start_wsl.sh or start_windows.ps1 to repair.", file=sys.stderr)
        return 1
    if not check_storage():
        print("Startup blocked: cannot write app data. Check directory permissions and free disk space.", file=sys.stderr)
        return 1
    try:
        server = ThreadingHTTPServer((HOST, PORT), EventSubHandler)
    except OSError:
        print(f"Cannot listen on {HOST}:{PORT}. Another instance may already be running. Check http://127.0.0.1:{PORT}/control, or stop the old instance. No process was stopped automatically.", file=sys.stderr)
        return 1
    TWITCH_SERVICE.start()
    SUPPORT_SERVICE.start()
    print(
        json.dumps(
            {
                "listening": True,
                "host": HOST,
                "port": PORT,
                "path": CALLBACK_PATH,
                "channel": APP_CONFIG.get("broadcaster_login") or BROADCASTER_LOGIN,
                "reward_title": APP_CONFIG.get("target_reward_title") or TARGET_REWARD_TITLE,
                "reward_id": APP_CONFIG.get("target_reward_id") or TARGET_REWARD_ID,
                "popup_path": POPUP_PATH,
                "overlay_path": OVERLAY_PATH,
                "overlay_url": f"http://127.0.0.1:{PORT}{OVERLAY_PATH}",
                "overlay_refresh_url": f"http://127.0.0.1:{PORT}{OVERLAY_REFRESH_PATH}",
                "overlay_key_url": f"http://127.0.0.1:{PORT}{OVERLAY_KEY_PATH}",
                "overlay_magenta_key_url": f"http://127.0.0.1:{PORT}{OVERLAY_MAGENTA_KEY_PATH}",
                "popup_open_url": POPUP_OPEN_URL,
                "auto_open_popup": AUTO_OPEN_POPUP,
                "soft_lock_enabled": SOFT_LOCK_ENABLED,
                "max_session_squats": MAX_SESSION_SQUATS,
                "control_url": f"http://127.0.0.1:{PORT}/control",
                "eventsub_transport": "websocket" if APP_CONFIG.get("twitch_access_token") else "setup_required",
                "legacy_webhook_enabled": bool(EVENTSUB_SECRET),
            }
        ),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    sys.exit(main())

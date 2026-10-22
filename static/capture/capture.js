import {config} from '/static/shared/config.js';
import {SquatDetector} from './squat-detector.mjs';
document.getElementById('popupVersion').textContent = config.popupVersion;
if (['/camera-overlay', '/capture', '/capture/'].includes(location.pathname)) document.getElementById('cameraOverlayStyle').media = 'all';
async function initPopupPage() {
    const popupEventsPath = config.popupEventsPath;
    const squatProgressPath = config.squatProgressPath;
    const squatCompletePath = config.squatCompletePath;
    const defaultSquatTarget = Number(config.defaultSquatTarget) || 10;
    const isCameraOverlay = ['/camera-overlay', '/capture', '/capture/'].includes(location.pathname);
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
    const metricEls = {
      currentAngle: document.getElementById('metricCurrentAngle'),
      standingAngle: document.getElementById('metricStandingAngle'),
      squatAngle: document.getElementById('metricSquatAngle'),
      hipDrop: document.getElementById('metricHipDrop'),
      depthScore: document.getElementById('metricDepthScore'),
      tracking: document.getElementById('metricTracking'),
    };
    const cameraSelectEl = document.getElementById("cameraSelect");
    const refreshCamerasButton = document.getElementById("refreshCamerasButton");
    const calibrateButton = document.getElementById('calibrateButton');
    const cancelCalibration = document.getElementById('cancelCalibration');
    const calibrationLabel = document.getElementById('calibrationLabel');
    const calibrationHint = document.getElementById('calibrationHint');
    let calibrationBusy = false;
    let calibrationGeneration = 0;

    let poseDetector;
    let poseHasResults = false;
    let cameraErrorCode = '';
    let cameraStream = null;
    let streamStarted = false;
    let renderLoopStarted = false;
    let lastVideoTime = -1;
    let currentJob = null;
    let squatCount = 0;
    let squatTargetTotal = defaultSquatTarget;
    const squatDetector = new SquatDetector();
    if(squatDetector.fixedAngleMode) document.getElementById('calibrationControls').hidden=true;
    document.addEventListener('visibilitychange', () => squatDetector.reset());
    const newline = String.fromCharCode(10);
    let poseScriptsLoaded = false;
    let poseFrameInFlight = false;
    let completionReported = false;
    let lastProgressSignature = "";

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
      squatDetector.reset();
      squatCount = 0;
      squatTargetTotal = currentJob ? currentJob.squat_target : defaultSquatTarget;
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
      if (document.hidden) { squatDetector.reset(); return; }
      poseHasResults = true;
      if (cameraErrorCode === 'model_failed') cameraErrorCode = '';
      if (isCameraOverlay && ((cameraMode !== 'capture' && !squatDetector.calibrating) || Date.now()>=cameraLeaseUntil || !cameraStorageOk)) { squatDetector.reset(); return; }
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvasContext.clearRect(0, 0, canvas.width, canvas.height);
      if (!results.poseLandmarks || !results.poseLandmarks.length) {
        detectSquatPhase(null);
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
      poseHasResults = false;
      if (cameraErrorCode === 'model_failed') cameraErrorCode = '';
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
        poseDetector = null;
        cameraErrorCode = 'model_failed';
        const errorMessage = "Failed to load pose model:" + newline + (error.message || error);
        setStatus(errorMessage);
        showError(errorMessage);
        throw error;
      }
    }

    function stopCameraStream() {
      calibrationGeneration++;
      streamStarted=false;
      squatDetector.clearCalibration();
      canvasContext.clearRect(0,0,canvas.width,canvas.height);
      calibrateButton.disabled=true;
      cancelCalibration.hidden=true;
      document.body.dataset.calibrating='false';
      calibrationLabel.textContent='Calibration needed';
      calibrationHint.textContent='Start your camera, then calibrate. The demo does not count.';
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
      cameraErrorCode = '';
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
            cameraErrorCode = attemptError.name === 'NotAllowedError' ? 'permission_denied' : 'camera_unavailable';
            errors.push(attempt.label + " -> " + (attemptError.name || "Error") + ": " + (attemptError.message || attemptError));
            debugLog("camera attempt failed: " + errors[errors.length - 1]);
          }
        }

        if (!newStream) {
          throw new Error(errors.join(newline));
        }

        stopCameraStream();
        cameraStream = newStream;
        cameraErrorCode = '';
        video.srcObject = cameraStream;
        await video.play();
        streamStarted = true;
        calibrateButton.disabled=false;
        calibrateButton.textContent='Calibrate';
        const activeTrack = cameraStream.getVideoTracks()[0];
        setCameraState(activeTrack.label || "Camera live", "");
        await refreshCameraDevices();
        cameraSelectEl.value = (activeTrack.getSettings && activeTrack.getSettings().deviceId) || cameraSelectEl.value;
        setStatus("Camera started. Calibrate your stance before counting.");
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

    function detectSquatPhase(landmarks) {
      const detection = squatDetector.update(landmarks, video.videoWidth, video.videoHeight, performance.now());
      const metrics=detection.metrics || {};
      const degrees=value=>Number.isFinite(value) ? Math.round(value)+'°' : '—';
      const percent=value=>Number.isFinite(value) ? Math.round(value*100)+'%' : '—';
      metricEls.currentAngle.textContent=degrees(detection.angle);
      metricEls.standingAngle.textContent=degrees(metrics.standingAngle);
      metricEls.squatAngle.textContent=degrees(metrics.squatAngle);
      metricEls.hipDrop.textContent=percent(metrics.hipDrop);
      metricEls.depthScore.textContent=percent(metrics.score);
      metricEls.tracking.textContent=metrics.side ? metrics.side+' leg · '+(metrics.signal==='angle'?'fixed angle':metrics.signal==='hip'?'hip':metrics.signal==='blend'?'angle + hip':'calibrating') : '—';
      document.body.dataset.calibrating=String(squatDetector.calibrating);
      cancelCalibration.hidden=!squatDetector.calibrating;
      calibrationLabel.textContent=detection.label;
      calibrationHint.textContent=detection.message;
      calibrateButton.textContent=squatDetector.calibrating ? 'Restart calibration' : squatDetector.calibrated ? 'Recalibrate' : 'Calibrate';
      phaseEl.textContent=detection.message;
      angleValueEl.textContent=detection.angle===null ? '—' : Math.round(detection.angle)+'°';
      depthFillEl.style.width=Math.round(detection.progress*100)+'%';
      standIndicatorEl.classList.toggle('active',detection.calibrated && detection.phase==='up');
      downIndicatorEl.classList.toggle('active',detection.calibrated && detection.phase==='down');
      setPoseState(detection.label,detection.angle===null || !detection.calibrated ? 'warn' : '');
      // Calibration and Webcam previews must never touch real counters/outboxes.
      if (!detection.rep || (isCameraOverlay && cameraMode!=='capture')) return;
      squatCount += 1;
      if (isCameraOverlay) {
        countEl.textContent=String(squatCount);
        const segment=queueTicket||'free';
        const total=(cameraCounts.get(segment)||0)+1;cameraCounts.set(segment,total);
        const payload={capture_session_id:captureSessionId+':'+segment,count:total,queue_run:queueTicket};
        cameraPending.set(payload.capture_session_id,payload);persistCamera(payload);
        flushCameraCounts().catch(e=>showError(e.message));
      } else if (squatCount>=squatTargetTotal) {
        setStatus('Target reached.');
        bannerEl.textContent='Queue finished at '+squatTargetTotal+' squats';
        updateCountUi('complete',true);reportSquatComplete(squatTargetTotal);
      } else updateCountUi('active',true);
    }

    calibrateButton.onclick=async()=>{
      if(calibrationBusy || !streamStarted)return;
      const generation=++calibrationGeneration;
      calibrationBusy=true;calibrateButton.disabled=true;
      try {
        calibrationLabel.textContent='Loading pose model…';
        await ensurePoseLandmarker();
        if(generation!==calibrationGeneration || !streamStarted)return;
        squatDetector.startCalibration();
        cancelCalibration.hidden=false;
        document.body.dataset.calibrating='true';
        calibrationLabel.textContent='1 / 3 · Stand';
        calibrationHint.textContent='Stand naturally with your feet still. Calibration does not count.';
      }catch(error){calibrationLabel.textContent='Model unavailable';calibrationHint.textContent='Check your connection, then retry Calibrate.';}
      finally{calibrationBusy=false;calibrateButton.disabled=!streamStarted;}
    };
    cancelCalibration.onclick=()=>{
      calibrationGeneration++;squatDetector.clearCalibration();
      document.body.dataset.calibrating='false';cancelCalibration.hidden=true;
      calibrationLabel.textContent='Calibration needed';calibrationHint.textContent='Calibration canceled. No demo reps were counted.';
      calibrateButton.textContent='Calibrate';
      canvasContext.clearRect(0,0,canvas.width,canvas.height);
    };

    async function renderLoop() {
      if(isCameraOverlay&&!streamStarted){requestAnimationFrame(renderLoop);return;}
      if (isCameraOverlay && ((cameraMode !== 'capture' && !squatDetector.calibrating) || !poseDetector)) { requestAnimationFrame(renderLoop); return; }
      if (!streamStarted || !poseDetector) return;
      if (video.currentTime !== lastVideoTime && !poseFrameInFlight) {
        poseFrameInFlight = true;
        try {
          await poseDetector.send({ image: video });
          lastVideoTime = video.currentTime;
        } catch (error) {
          showError('Pose detection failed: ' + error.message);
          poseHasResults = false;
          cameraErrorCode = 'model_failed';
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
      const header=document.createElement('div');header.className='sidebar-header';
      const heading=document.createElement('div');heading.className='sidebar-heading';
      const title=document.createElement('strong');title.textContent='Squat Capture';
      const subtitle=document.createElement('span');subtitle.textContent='Camera monitor';heading.append(title,subtitle);
      const hide=document.createElement('button');hide.className='sidebar-close';hide.textContent='×';hide.title='Hide sidebar (H)';hide.setAttribute('aria-label','Hide camera controls sidebar');hide.onclick=()=>document.body.classList.add('clean');header.append(heading,hide);
      const help=document.createElement('p');help.className='sidebar-help';help.textContent='Keep this window open and use Window Capture in OBS or Streamlabs.';
      const cameraSection=document.createElement('section');cameraSection.className='camera-section';
      const cameraTitle=document.createElement('strong');cameraTitle.className='section-title';cameraTitle.textContent='Camera';
      const cameraActions=document.createElement('div');cameraActions.className='camera-actions';cameraActions.append(startButton,refreshCamerasButton);
      cameraSection.append(cameraTitle,cameraSelectEl,cameraActions);
      const show=document.createElement('button');show.id='cameraPanelToggle';show.textContent='Show controls';show.setAttribute('aria-label','Show camera controls sidebar');show.onclick=()=>document.body.classList.remove('clean');
      tools.append(header,help,cameraSection,document.getElementById('calibrationControls'),document.getElementById('detectionDetailsCard'));
      document.body.append(tools,show);
      const warning=document.createElement('div');warning.id='cameraWarning';document.body.append(warning);
      const syncInfo=document.createElement('p');syncInfo.className='sync-state';syncInfo.setAttribute('role','status');tools.append(syncInfo);
      recoverCamera();
      window.addEventListener('beforeunload',e=>{if(cameraPending.size){e.preventDefault();e.returnValue=''}});
      document.addEventListener('keydown',e=>{if(e.key.toLowerCase()==='h'&&!['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))document.body.classList.toggle('clean')});
      async function cameraHeartbeat(){
        if(cameraModeBusy)return;cameraModeBusy=true;
        try{
          syncInfo.textContent=cameraPending.size?'Waiting to sync · '+cameraPending.size+' saved batches':'All reps synced';
          const response=await fetch('/api/camera',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({heartbeat:true,page_id:cameraPageId,telemetry:{error_code:cameraErrorCode,camera_live:!!cameraStream?.getVideoTracks().some(t=>t.readyState==='live'&&!t.muted),model_ready:poseHasResults,body_detected:Date.now()-lastBodySeen<2000,storage_ok:cameraStorageOk,actual_mode:cameraMode,calibration:squatDetector.stage,pending:cameraPending.size}}),signal:AbortSignal.timeout(4000)});
          if(!response.ok)throw Error('Control connection unavailable');
          const state=await response.json();
          if(!state.owns_camera){cameraLeaseUntil=0;stopCameraStream();streamStarted=false;throw Error('Another camera page owns capture. Close it and wait 8 seconds, then Start Camera here.');}
          cameraLeaseUntil=Date.now()+3500;
          if(!cameraStorageOk&&cameraPending.size===0)throw Error('Local storage unavailable; capture disabled');
          await flushCameraCounts();
          const newTicket=state.queue?.run||null;
          if(newTicket!==queueTicket){squatDetector.reset();queueTicket=newTicket;}
          if(state.mode!==cameraMode){
            // Disable counting while the model loads or a mode change is pending.
            cameraMode='webcam';document.body.dataset.cameraMode='webcam';
            squatDetector.reset();
            if(state.mode==='capture')await ensurePoseLandmarker();
            cameraMode=state.mode;document.body.dataset.cameraMode=cameraMode;
            bannerEl.textContent='Squat capture';targetEl.textContent='reps this window';
          }
          const head=state.queue?.items?.[0];
          if(queueTicket&&head){bannerEl.textContent=head.viewer+' · '+head.title;targetEl.textContent=head.done+' / '+head.target+' · queued challenge';}
          else{bannerEl.textContent='Free capture';targetEl.textContent='reps this window';}
          warning.textContent=errorBoxEl ? errorBoxEl.textContent : '';
        }catch(e){cameraLeaseUntil=0;cameraMode='webcam';squatDetector.reset();document.body.dataset.cameraMode='webcam';document.body.dataset.calibrating='false';warning.textContent='Capture paused: '+e.message}
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
      const message = "Bootstrap failure:\n" + (error && error.message ? error.message : error);
      if (errorBoxEl) {
        errorBoxEl.textContent = message;
        errorBoxEl.classList.add("visible");
      }
      if (debugBoxEl) {
        debugBoxEl.textContent = message + newline + debugBoxEl.textContent;
      }
      console.error(error);
    });

import {config} from '/static/shared/config.js';
const overlayEventsPath = config.overlayEventsPath;
    const overlayStatePath = config.overlayStatePath;
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

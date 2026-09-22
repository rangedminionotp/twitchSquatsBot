import {config} from '/static/shared/config.js';
const overlayStatePath = config.overlayStatePath;
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

    function setText(element, text) {
      element.textContent = text == null ? "" : String(text);
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

      if (status === "complete") {
        setText(pillEl, "Unlocked");
        pillEl.className = "pill complete";
        setText(messageEl, viewer + "'s challenge is complete.");
        setText(footerStatusEl, "Complete");
      } else if (status === "active") {
        setText(pillEl, state.locked ? "Locked" : "Active");
        pillEl.className = "pill";
        setText(messageEl, viewer + " redeemed " + reward + ".");
        setText(footerStatusEl, "In Progress");
      } else if (status === "skipped") {
        setText(pillEl, "Skipped");
        pillEl.className = "pill";
        setText(messageEl, state.message || "Redeem skipped.");
        setText(footerStatusEl, "Skipped");
      } else {
        setText(pillEl, "Waiting");
        pillEl.className = "pill";
        setText(messageEl, "Waiting for a channel point redeem...");
        setText(footerStatusEl, "Idle");
      }
    }

    async function pollOverlayState() {
      try {
        const response = await fetch(overlayStatePath + "?_=" + Date.now(), {
          cache: "no-store",
        });
        if (!response.ok) return;
        updateOverlay(await response.json());
      } catch (error) {
        // Try again on the next interval.
      }
    }

    pollOverlayState();
    setInterval(pollOverlayState, 1000);

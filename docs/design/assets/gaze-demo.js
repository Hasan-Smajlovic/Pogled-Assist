window.createReferenceGaze = () => {
  'use strict';
  const ring = document.getElementById('gaze-ring');
  const toggle = document.getElementById('gaze-demo');
  const GAZE_PAUSE_MS = 250, GAZE_FILL_MS = 850, GAZE_EDGE_MARGIN = 24;
  const storedEdgeHold = Number(ReferenceDesign.readSession('edge-hold-ms', 120));
  const GAZE_LEAVE_GRACE_MS = Number.isFinite(storedEdgeHold) ? Math.min(300, Math.max(0, Math.round(storedEdgeHold / 20) * 20)) : 120;
  let gazeTarget = null;
  let gazeStart = 0;
  let gazeFrame = 0;
  let gazeButton = null;
  let gazePoint = null;
  let gazeAwayStart = null;
  let gazeLastSeen = 0;
  let clickFromGaze = false;
  let lastGazeClick = { target: null, time: 0 };
  let blockedGaze = null;
  let firedTimer = 0;
  function enabledButton(button) {
    return button?.isConnected && !button.disabled;
  }
  function usableButton(button) {
    return enabledButton(button) && button.getClientRects().length;
  }
  function nearButton(button) {
    const rect = button.getBoundingClientRect();
    const margin = Math.min(GAZE_EDGE_MARGIN, rect.width / 4, rect.height / 4);
    return gazePoint.x >= rect.left - margin && gazePoint.x <= rect.right + margin
      && gazePoint.y >= rect.top - margin && gazePoint.y <= rect.bottom + margin;
  }
  function resumeNearTarget(candidate, now) {
    if (gazeButton !== candidate || gazeAwayStart === null) return false;
    if (edgeExpired(now)) return false;
    gazeStart += now - gazeLastSeen;
    gazeAwayStart = null;
    gazeLastSeen = now;
    return true;
  }
  function holdNearTarget(candidate, now) {
    if (!usableButton(candidate) || !gazePoint) return false;
    const speechControl = candidate.hasAttribute('data-action') || candidate.hasAttribute('data-edge-control');
    const leaving = gazeButton !== candidate && speechControl;
    if (leaving && nearButton(candidate)) {
      gazeAwayStart ??= now;
      return now - gazeAwayStart < GAZE_LEAVE_GRACE_MS;
    }
    return resumeNearTarget(candidate, now);
  }
  function edgeExpired(now) {
    return gazeAwayStart !== null && now - gazeAwayStart >= GAZE_LEAVE_GRACE_MS;
  }
  function updateGazeTarget(now) {
    if (holdNearTarget(gazeTarget || blockedGaze, now)) return;
    if (gazeButton === gazeTarget && gazeAwayStart === null) return;
    if (edgeExpired(now)) blockedGaze = null;
    resetGaze();
    if (gazeButton === blockedGaze) return;
    blockedGaze = null;
    if (!usableButton(gazeButton)) return;
    gazeTarget = gazeButton;
    gazeStart = gazeLastSeen = now;
  }

  function canTickGaze() {
    if (gazeTarget === blockedGaze && gazeAwayStart === null) return false;
    // A completed button still needs departure checks while its ring is hidden.
    if (!gazeTarget && gazeAwayStart !== null) {
      gazeFrame = requestAnimationFrame(tickGaze);
      return false;
    }
    if (!enabledButton(gazeTarget) || document.hidden) { resetGaze(); return false; }
    return true;
  }
  function tickGaze(now) {
    gazeFrame = 0;
    updateGazeTarget(now);
    if (!canTickGaze()) return;
    const held = gazeAwayStart !== null;
    if (!held) gazeLastSeen = now;
    const elapsed = gazeLastSeen - gazeStart;
    if (elapsed >= GAZE_PAUSE_MS) renderGazeRing(elapsed, held);
    if (!held && elapsed >= GAZE_PAUSE_MS + GAZE_FILL_MS) {
      activateGaze(now);
      return;
    }
    gazeFrame = requestAnimationFrame(tickGaze);
  }

  function renderGazeRing(elapsed, held) {
    clearTimeout(firedTimer);
    ring.dataset.state = held ? 'held' : 'active';
    const rect = gazeTarget.getBoundingClientRect();
    (gazeTarget.closest('dialog') || document.body).append(ring);
    ring.style.left = `${rect.left + rect.width / 2}px`;
    ring.style.top = `${rect.top + rect.height / 2}px`;
    ring.style.setProperty('--progress', `${Math.min(1, (elapsed - GAZE_PAUSE_MS) / GAZE_FILL_MS) * 360}deg`);
    ring.hidden = false;
    gazeTarget.classList.add('gaze-target');
  }
  function activateGaze(now) {
    const target = gazeTarget;
    blockedGaze = target;
    lastGazeClick = { target, time: now };
    clickFromGaze = true;
    target.click();
    clickFromGaze = false;
    (document.querySelector('dialog[open]') || document.body).append(ring);
    ring.dataset.state = 'fired';
    ring.hidden = false;
    firedTimer = setTimeout(() => { ring.hidden = true; }, 220);
    // Require leaving the target before another dwell can start.
    gazeTarget = target;
  }

  function resetGaze() {
    clearTimeout(firedTimer);
    cancelAnimationFrame(gazeFrame);
    gazeFrame = 0;
    gazeAwayStart = null;
    gazeTarget?.classList.remove('gaze-target');
    gazeTarget = null;
    ring.hidden = true;
  }

  function ensureGazeFrame() {
    if (gazeFrame) return;
    if (gazeTarget || gazeAwayStart !== null) gazeFrame = requestAnimationFrame(tickGaze);
  }
  document.addEventListener('pointermove', event => {
    if (event.pointerType === 'touch' || !toggle.checked) return;
    const button = event.target.closest('button[data-action], button[data-edge-control]');
    gazeButton = button && !button.disabled ? button : null;
    gazePoint = { x: event.clientX, y: event.clientY };
    updateGazeTarget(performance.now());
    ensureGazeFrame();
  });
  document.documentElement.addEventListener('pointerleave', resetGaze);
  document.addEventListener('pointerdown', resetGaze);
  document.addEventListener('visibilitychange', resetGaze);
  document.addEventListener('scroll', resetGaze, true);
  window.addEventListener('blur', resetGaze);
  window.addEventListener('resize', resetGaze);
  window.addEventListener('pagehide', resetGaze);
  toggle.addEventListener('change', resetGaze);
  return {
    reset: resetGaze,
    blockCurrent() { if (gazeTarget) blockedGaze = gazeTarget; },
    isDuplicateClick(button) { return !clickFromGaze && button === lastGazeClick.target && performance.now() - lastGazeClick.time < 350; },
  };
};

window.createReferenceGaze = () => {
  'use strict';
  const ring = document.getElementById('gaze-ring');
  const toggle = document.getElementById('gaze-demo');
  const GAZE_PAUSE_MS = 500, GAZE_FILL_MS = 500, GAZE_LEAVE_GRACE_MS = 120, GAZE_EDGE_MARGIN = 24;
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
  function updateGazeTarget(now) {
    const candidate = gazeTarget || blockedGaze;
    if (candidate?.isConnected && !candidate.disabled && candidate.getClientRects().length && gazePoint) {
      const rect = candidate.getBoundingClientRect();
      const margin = Math.min(GAZE_EDGE_MARGIN, rect.width / 4, rect.height / 4);
      const near = gazePoint.x >= rect.left - margin && gazePoint.x <= rect.right + margin && gazePoint.y >= rect.top - margin && gazePoint.y <= rect.bottom + margin;
      const speechControl = candidate.hasAttribute('data-action') || candidate.hasAttribute('data-edge-control');
      if (gazeButton !== candidate && speechControl && near) {
        gazeAwayStart ??= now;
        if (now - gazeAwayStart < GAZE_LEAVE_GRACE_MS) return;
      } else if (gazeButton === candidate && gazeAwayStart !== null && now - gazeAwayStart < GAZE_LEAVE_GRACE_MS) {
        gazeStart += now - gazeLastSeen;
        gazeAwayStart = null;
        gazeLastSeen = now;
        return;
      }
    }
    if (gazeButton === gazeTarget && gazeAwayStart === null) return;
    if (gazeAwayStart !== null && now - gazeAwayStart >= GAZE_LEAVE_GRACE_MS) blockedGaze = null;
    resetGaze();
    if (gazeButton === blockedGaze) return;
    blockedGaze = null;
    if (!gazeButton?.isConnected || gazeButton.disabled || !gazeButton.getClientRects().length) return;
    gazeTarget = gazeButton;
    gazeStart = gazeLastSeen = now;
  }

  function tickGaze(now) {
    gazeFrame = 0;
    updateGazeTarget(now);
    if (gazeTarget === blockedGaze && gazeAwayStart === null) return;
    // A completed button still needs departure checks while its ring is hidden.
    if (!gazeTarget && gazeAwayStart !== null) {
      gazeFrame = requestAnimationFrame(tickGaze);
      return;
    }
    if (!gazeTarget?.isConnected || gazeTarget.disabled || document.hidden) { resetGaze(); return; }
    const held = gazeAwayStart !== null;
    if (!held) gazeLastSeen = now;
    const elapsed = gazeLastSeen - gazeStart;
    if (elapsed >= GAZE_PAUSE_MS) {
      const rect = gazeTarget.getBoundingClientRect();
      (gazeTarget.closest('dialog') || document.body).append(ring);
      ring.style.left = `${rect.left + rect.width / 2}px`;
      ring.style.top = `${rect.top + rect.height / 2}px`;
      ring.style.setProperty('--progress', `${Math.min(1, (elapsed - GAZE_PAUSE_MS) / GAZE_FILL_MS) * 360}deg`);
      ring.hidden = false;
      gazeTarget.classList.add('gaze-target');
    }
    if (!held && elapsed >= GAZE_PAUSE_MS + GAZE_FILL_MS) {
      const target = gazeTarget;
      blockedGaze = target;
      lastGazeClick = { target, time: now };
      clickFromGaze = true;
      target.click();
      clickFromGaze = false;
      // Require leaving the target before another dwell can start.
      gazeTarget = target;
      return;
    }
    gazeFrame = requestAnimationFrame(tickGaze);
  }

  function resetGaze() {
    cancelAnimationFrame(gazeFrame);
    gazeFrame = 0;
    gazeAwayStart = null;
    gazeTarget?.classList.remove('gaze-target');
    gazeTarget = null;
    ring.hidden = true;
  }

  document.addEventListener('pointermove', event => {
    if (event.pointerType === 'touch' || !toggle.checked) return;
    const button = event.target.closest('button[data-action], button[data-edge-control]');
    gazeButton = button && !button.disabled ? button : null;
    gazePoint = { x: event.clientX, y: event.clientY };
    updateGazeTarget(performance.now());
    if (!gazeFrame && (gazeTarget || gazeAwayStart !== null)) gazeFrame = requestAnimationFrame(tickGaze);
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

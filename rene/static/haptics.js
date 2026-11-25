/* Vibrations partagées (Assistance, carte cadeau).
   Android : API Vibration standard.
   iPhone : Safari n'a pas navigator.vibrate ; depuis iOS 18, basculer un interrupteur
   <input type="checkbox" switch> déclenche le retour haptique du système. On en crée un,
   invisible, et on le bascule pour chaque impulsion. */
(function (root) {
  'use strict';
  const hasVibrate = typeof navigator.vibrate === 'function';
  const isApple = /iPhone|iPad|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const MIN_PULSE = 20;
  const IOS_GAP = 110; // deux tics iOS trop rapprochés se fondent en un seul

  function iosTick() {
    try {
      const label = document.createElement('label');
      label.setAttribute('aria-hidden', 'true');
      label.style.display = 'none';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.setAttribute('switch', '');
      label.appendChild(input);
      document.head.appendChild(label);
      label.click();
      document.head.removeChild(label);
    } catch {}
  }

  function play(pattern) {
    const steps = (Array.isArray(pattern) ? pattern : [pattern]).map(Number).filter(n => n >= 0);
    if (!steps.length) return;
    if (hasVibrate) {
      try { navigator.vibrate(steps.map((ms, i) => i % 2 ? ms : Math.max(MIN_PULSE, ms))); } catch {}
      return;
    }
    if (!isApple) return;
    // Chaque impulsion devient un tic système, au même rythme que le motif Android.
    let at = 0, last = -Infinity;
    steps.forEach((ms, i) => {
      if (i % 2 === 0) {
        const when = Math.max(at, last + IOS_GAP);
        if (when === 0) iosTick(); else setTimeout(iosTick, when);
        last = when;
      }
      at += ms;
    });
  }

  const PATTERNS = {
    tap: [25], select: [32], success: [40, 70, 60], error: [70, 60, 70, 60, 70],
    warning: [55, 80, 55], toggle: [30],
  };

  root.reneHaptics = {
    play: pattern => play(typeof pattern === 'string' ? PATTERNS[pattern] || PATTERNS.tap : pattern),
    mode: hasVibrate ? 'vibrate' : isApple ? 'ios-switch' : 'none',
  };
})(window);

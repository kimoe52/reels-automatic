/* Source-pixel-safe entrances for extracted raster card layers.
 * There is no text reconstruction or glyph transformation: type and numbers
 * stay in their original image pixels.
 */
(function (global) {
  "use strict";

  const DURATIONS_MS = Object.freeze({
    "": 300, settle_fade: 320, rise_fade: 360, slide_left: 340,
    slide_right: 340, scale_pop: 300, reveal: 360, fade: 240,
    wipe_up: 360, wipe_down: 360, iris_reveal: 380, spring_settle: 440,
    bounce_settle: 420, path_arc: 440, gentle_tilt: 400, stepped_reveal: 400
  });
  const FINAL = Object.freeze({ opacity: 1, x: 0, y: 0, scale: 1, rotation: 0, clipPath: "inset(0 0% 0 0)" });

  function durationMs(itemOrEffect) {
    const item = typeof itemOrEffect === "object" && itemOrEffect ? itemOrEffect : null;
    const effect = item ? item.effect : itemOrEffect;
    const requested = item && Number(item.duration_ms != null ? item.duration_ms : item.durationMs);
    const fallback = DURATIONS_MS[effect || ""] == null ? DURATIONS_MS.settle_fade : DURATIONS_MS[effect || ""];
    return Number.isFinite(requested) ? Math.max(1, Math.min(600, requested)) : fallback;
  }

  function animationFor(effect) {
    switch (effect) {
      case "rise_fade": return { from: { opacity: 0, y: 24 }, ease: "power3.out" };
      case "slide_left": return { from: { opacity: 0, x: -30 }, ease: "power3.out" };
      case "slide_right": return { from: { opacity: 0, x: 30 }, ease: "power3.out" };
      case "scale_pop": return { from: { opacity: 0, scale: 0.96 }, ease: "power3.out", origin: "50% 50%" };
      case "reveal": return { from: { opacity: 1, clipPath: "inset(0 100% 0 0)" }, ease: "power2.out" };
      case "wipe_up": return { from: { opacity: 1, clipPath: "inset(100% 0 0 0)" }, ease: "power2.out" };
      case "wipe_down": return { from: { opacity: 1, clipPath: "inset(0 0 100% 0)" }, ease: "power2.out" };
      case "iris_reveal": return { from: { opacity: 1, clipPath: "inset(48% 48% 48% 48% round 50%)" }, ease: "power2.out" };
      case "stepped_reveal": return { from: { opacity: 1, clipPath: "inset(0 100% 0 0)" }, ease: "steps(4)" };
      case "spring_settle": return { from: { opacity: 0, y: 18, scale: 0.985 }, ease: "back.out(1.15)", origin: "50% 100%" };
      case "bounce_settle": return { from: { opacity: 0, y: 17, scale: 0.97 }, ease: "back.out(1.35)", origin: "50% 100%" };
      case "path_arc": return { from: { opacity: 0, x: -18, y: 13 }, ease: "power3.out" };
      case "gentle_tilt": return { from: { opacity: 0, y: 13, rotation: -1.2 }, ease: "power3.out", origin: "50% 100%" };
      case "fade": return { from: { opacity: 0 }, ease: "power2.out" };
      case "settle_fade":
      default: return { from: { opacity: 0, y: 16 }, ease: "power3.out" };
    }
  }

  function animate(timeline, target, item, at) {
    if (!timeline || !target) return timeline;
    const effect = (item && item.effect) || "settle_fade";
    const spec = animationFor(effect);
    const seconds = durationMs(item) / 1000;
    // A wrapper is supplied by the renderer; clip-path therefore reveals the
    // original raster pixels as one unit instead of rebuilding its contents.
    timeline.set(target, { transformOrigin: spec.origin || "50% 50%" }, at);
    if (effect === "path_arc") {
      // Two bounded segments give a small rigid-body arc; the raster itself is
      // never warped or continuously floated after arriving.
      const crest = Math.min(0.18, seconds * 0.42);
      timeline.fromTo(target, spec.from,
        { opacity: 1, x: -6, y: -8, scale: 1, rotation: 0, clipPath: FINAL.clipPath, duration: crest, ease: "power2.out" }, at);
      timeline.fromTo(target, { opacity: 1, x: -6, y: -8, scale: 1, rotation: 0, clipPath: FINAL.clipPath },
        Object.assign({}, FINAL, { duration: seconds - crest, ease: "power3.out" }), at + crest);
    } else {
      timeline.fromTo(target, spec.from, Object.assign({}, FINAL, { duration: seconds, ease: spec.ease }), at);
    }
    // Make the held/read state exact even if a timeline is seeked to its end.
    // GSAP annotates tween vars (including set vars) while compiling them.
    // Keep the shared final-state contract frozen, but hand GSAP a fresh copy.
    timeline.set(target, Object.assign({}, FINAL), at + seconds);
    return timeline;
  }

  global.CardMotionEffects = Object.freeze({ animate: animate, durationMs: durationMs, EFFECTS: Object.freeze(Object.keys(DURATIONS_MS)) });
}(window));

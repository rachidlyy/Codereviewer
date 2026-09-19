import { useEffect, useRef } from 'react';

/**
 * Animated drifting-light-beams background.
 *
 * Ported from the shadcn/Tailwind version. The beam simulation is plain canvas
 * code, so it needed no rewriting; only the wrapper was adapted - Tailwind
 * class strings became the `.beams*` rules in styles.css, and the two
 * framer-motion elements became one CSS keyframe. That keeps this project's
 * zero-UI-dependency stance intact (no Tailwind, no shadcn, no motion).
 *
 * Purely decorative: the root is aria-hidden and pointer-events:none, so it
 * can never intercept a click meant for the app underneath.
 */

type Intensity = 'subtle' | 'medium' | 'strong';

interface Beam {
  x: number;
  y: number;
  width: number;
  length: number;
  angle: number;
  speed: number;
  opacity: number;
  hue: number;
  pulse: number;
  pulseSpeed: number;
}

type Props = {
  intensity?: Intensity;
  className?: string;
};

const OPACITY_BY_INTENSITY: Record<Intensity, number> = {
  subtle: 0.7,
  medium: 0.85,
  strong: 1,
};

const MINIMUM_BEAMS = 20;

/**
 * Rendering at full devicePixelRatio means a 4K display gets an 8M-pixel
 * canvas redrawn every frame, for a background nobody is looking at directly.
 */
const MAX_DPR = 1.5;

/** The beams drift slowly, so 30fps is indistinguishable from 60 and costs half. */
const TARGET_FPS = 30;

function createBeam(width: number, height: number): Beam {
  return {
    x: Math.random() * width * 1.5 - width * 0.25,
    y: Math.random() * height * 1.5 - height * 0.25,
    width: 30 + Math.random() * 60,
    length: height * 2.5,
    angle: -35 + Math.random() * 10,
    speed: 0.6 + Math.random() * 1.2,
    opacity: 0.12 + Math.random() * 0.16,
    hue: 190 + Math.random() * 70,
    pulse: Math.random() * Math.PI * 2,
    pulseSpeed: 0.02 + Math.random() * 0.03,
  };
}

export default function BeamsBackground({ intensity = 'subtle', className }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Beam geometry is kept in CSS pixels; the transform handles density. The
    // original mixed the two, which made beams scale with devicePixelRatio.
    const size = { width: 0, height: 0 };
    let beams: Beam[] = [];

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
      size.width = window.innerWidth;
      size.height = window.innerHeight;
      canvas.width = Math.round(size.width * dpr);
      canvas.height = Math.round(size.height * dpr);
      canvas.style.width = `${size.width}px`;
      canvas.style.height = `${size.height}px`;
      // setTransform, not scale(): scale() compounds, so every resize used to
      // multiply the existing transform again.
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      beams = Array.from({ length: MINIMUM_BEAMS * 1.5 }, () =>
        createBeam(size.width, size.height),
      );
    };

    const resetBeam = (beam: Beam, index: number, total: number) => {
      const column = index % 3;
      const spacing = size.width / 3;
      beam.y = size.height + 100;
      beam.x = column * spacing + spacing / 2 + (Math.random() - 0.5) * spacing * 0.5;
      beam.width = 100 + Math.random() * 100;
      beam.speed = 0.5 + Math.random() * 0.4;
      beam.hue = 190 + (index * 70) / total;
      beam.opacity = 0.2 + Math.random() * 0.1;
    };

    const drawBeam = (beam: Beam) => {
      ctx.save();
      ctx.translate(beam.x, beam.y);
      ctx.rotate((beam.angle * Math.PI) / 180);

      const pulsing =
        beam.opacity * (0.8 + Math.sin(beam.pulse) * 0.2) * OPACITY_BY_INTENSITY[intensity];

      const gradient = ctx.createLinearGradient(0, 0, 0, beam.length);
      const stop = (at: number, alpha: number) =>
        gradient.addColorStop(at, `hsla(${beam.hue}, 85%, 65%, ${alpha})`);

      stop(0, 0);
      stop(0.1, pulsing * 0.5);
      stop(0.4, pulsing);
      stop(0.6, pulsing);
      stop(0.9, pulsing * 0.5);
      stop(1, 0);

      ctx.fillStyle = gradient;
      ctx.fillRect(-beam.width / 2, 0, beam.width, beam.length);
      ctx.restore();
    };

    const render = () => {
      ctx.clearRect(0, 0, size.width, size.height);
      ctx.filter = 'blur(35px)';
      const total = beams.length;
      beams.forEach((beam, index) => {
        beam.y -= beam.speed;
        beam.pulse += beam.pulseSpeed;
        if (beam.y + beam.length < -100) resetBeam(beam, index, total);
        drawBeam(beam);
      });
    };

    let frame = 0;
    let last = 0;

    const animate = (now: number) => {
      frame = requestAnimationFrame(animate);
      if (now - last < 1000 / TARGET_FPS) return;
      last = now;
      render();
    };

    const start = () => {
      if (!frame) frame = requestAnimationFrame(animate);
    };
    const stop = () => {
      if (frame) {
        cancelAnimationFrame(frame);
        frame = 0;
      }
    };

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');

    const applyMotionPreference = () => {
      stop();
      // Honour the OS setting by drawing one static frame and leaving it there.
      if (reduced.matches) render();
      else start();
    };

    const onVisibility = () => {
      // Don't hold a core animating a tab nobody is looking at.
      if (document.hidden) stop();
      else applyMotionPreference();
    };

    resize();
    applyMotionPreference();
    window.addEventListener('resize', resize);
    document.addEventListener('visibilitychange', onVisibility);
    reduced.addEventListener('change', applyMotionPreference);

    return () => {
      stop();
      window.removeEventListener('resize', resize);
      document.removeEventListener('visibilitychange', onVisibility);
      reduced.removeEventListener('change', applyMotionPreference);
    };
  }, [intensity]);

  return (
    <div className={className ? `beams ${className}` : 'beams'} aria-hidden="true">
      <canvas ref={canvasRef} className="beams-canvas" />
      <div className="beams-veil" />
    </div>
  );
}

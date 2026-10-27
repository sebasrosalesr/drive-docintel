// Animated status glyphs for the chat. One per phase the backend reports. All honour reduced motion.
import { useRef } from "react";
import { MotionPathPlugin } from "gsap/MotionPathPlugin";
import { gsap, reduced, useGSAP } from "../lib/gsap";

gsap.registerPlugin(MotionPathPlugin);

export type Phase = "connecting" | "search" | "read" | "sql" | "write";

const NAVY = "#0f2319", GOLD = "#e0a920";

/** The two-circle mark: navy and gold swap places, arcing past each other, over and over. */
export function MarkSwap({ size = 26 }: { size?: number }) {
  const ref = useRef<SVGSVGElement>(null);
  useGSAP(() => {
    if (reduced() || !ref.current) return;
    const [a, b] = Array.from(ref.current.querySelectorAll("circle"));
    const tl = gsap.timeline({ repeat: -1, defaults: { ease: "sine.inOut" } });
    tl.to(a, { x: 6, duration: 0.9 }, 0).to(a, { y: -3.5, duration: 0.45, yoyo: true, repeat: 1 }, 0)
      .to(b, { x: -6, duration: 0.9 }, 0).to(b, { y: 3.5, duration: 0.45, yoyo: true, repeat: 1 }, 0)
      .to(a, { x: 0, duration: 0.9 }, 1.1).to(a, { y: 3.5, duration: 0.45, yoyo: true, repeat: 1 }, 1.1)
      .to(b, { x: 0, duration: 0.9 }, 1.1).to(b, { y: -3.5, duration: 0.45, yoyo: true, repeat: 1 }, 1.1);
  }, { scope: ref });
  return (
    <svg ref={ref} className="glyph" width={size} height={size} viewBox="0 0 28 28" aria-hidden="true">
      <circle cx="11" cy="14" r="7" fill="none" stroke={NAVY} strokeWidth="1.8" />
      <circle cx="17" cy="14" r="7" fill="none" stroke={GOLD} strokeWidth="1.8" />
    </svg>
  );
}

/** Lens sweeping over stacked pages. */
export function GlyphSearch() {
  const ref = useRef<SVGSVGElement>(null);
  useGSAP(() => {
    if (reduced()) return;
    gsap.to(".lens", { x: -8, y: -8, duration: 1.1, ease: "sine.inOut", repeat: -1, yoyo: true });
    gsap.fromTo(".lens circle", { attr: { r: 5 } }, { attr: { r: 5.8 }, duration: 0.55, repeat: -1, yoyo: true, ease: "sine.inOut" });
  }, { scope: ref });
  return (
    <svg ref={ref} className="glyph" viewBox="0 0 28 28" aria-hidden="true">
      <rect x="4" y="6" width="14" height="18" rx="2" fill="none" stroke={NAVY} strokeWidth="1.5" />
      <rect x="7" y="3" width="14" height="18" rx="2" fill="#fffdf8" stroke={NAVY} strokeWidth="1.5" />
      <line x1="10" y1="8" x2="18" y2="8" stroke={GOLD} strokeWidth="1.5" /><line x1="10" y1="12" x2="18" y2="12" stroke={GOLD} strokeWidth="1.5" /><line x1="10" y1="16" x2="15" y2="16" stroke={GOLD} strokeWidth="1.5" />
      <g className="lens"><circle cx="18" cy="18" r="5" fill="rgba(223,249,186,.55)" stroke={NAVY} strokeWidth="1.8" /><line x1="22" y1="22" x2="26" y2="26" stroke={NAVY} strokeWidth="2" strokeLinecap="round" /></g>
    </svg>
  );
}

/** A page whose lines light up as a gold highlight scans down. */
export function GlyphRead() {
  const ref = useRef<SVGSVGElement>(null);
  useGSAP(() => {
    if (reduced()) return;
    gsap.to(".hl", { y: 12, duration: 1.6, ease: "none", repeat: -1 });
    gsap.fromTo(".ln", { opacity: 0.35 }, { opacity: 1, duration: 0.4, stagger: { each: 0.4, repeat: -1, yoyo: true } });
  }, { scope: ref });
  return (
    <svg ref={ref} className="glyph" viewBox="0 0 28 28" aria-hidden="true">
      <rect x="5" y="3" width="18" height="22" rx="2" fill="#fffdf8" stroke={NAVY} strokeWidth="1.5" />
      <rect className="hl" x="7" y="7" width="14" height="4" fill="rgba(223,249,186,.9)" />
      <g stroke={NAVY} strokeWidth="1.5" strokeLinecap="round"><line className="ln" x1="8" y1="9" x2="20" y2="9" /><line className="ln" x1="8" y1="13" x2="20" y2="13" /><line className="ln" x1="8" y1="17" x2="17" y2="17" /><line className="ln" x1="8" y1="21" x2="19" y2="21" /></g>
    </svg>
  );
}

/** Bars growing and settling. */
export function GlyphFigures() {
  const ref = useRef<SVGSVGElement>(null);
  useGSAP(() => {
    if (reduced()) return;
    gsap.fromTo(".bar", { scaleY: 0.2, transformOrigin: "50% 100%" }, { scaleY: 1, duration: 0.7, ease: "power2.out", stagger: { each: 0.15, repeat: -1, yoyo: true, repeatDelay: 0.3 } });
  }, { scope: ref });
  return (
    <svg ref={ref} className="glyph" viewBox="0 0 28 28" aria-hidden="true">
      <line x1="4" y1="24" x2="26" y2="24" stroke={NAVY} strokeWidth="1.5" />
      <rect className="bar" x="6" y="12" width="3.5" height="12" fill={GOLD} /><rect className="bar" x="11" y="8" width="3.5" height="16" fill={NAVY} />
      <rect className="bar" x="16" y="14" width="3.5" height="10" fill={GOLD} /><rect className="bar" x="21" y="5" width="3.5" height="19" fill={NAVY} />
    </svg>
  );
}

/** A quill drawing a gold ink line. */
export function GlyphWrite() {
  const ref = useRef<SVGSVGElement>(null);
  useGSAP(() => {
    if (reduced() || !ref.current) return;
    const ink = ref.current.querySelector("path.ink") as SVGPathElement;
    const L = ink.getTotalLength();
    gsap.set(ink, { strokeDasharray: L, strokeDashoffset: L });
    const tl = gsap.timeline({ repeat: -1, repeatDelay: 0.5 });
    tl.to(ink, { strokeDashoffset: 0, duration: 1.6, ease: "power1.inOut" }, 0)
      .to(".nib", { motionPath: { path: ink, align: ink, alignOrigin: [0.1, 1], autoRotate: false }, duration: 1.6, ease: "power1.inOut" }, 0)
      .to(".nib", { y: "-=5", opacity: 0, duration: 0.3 }, ">")
      .set(".nib", { opacity: 1 });
  }, { scope: ref });
  return (
    <svg ref={ref} className="glyph" viewBox="0 0 28 28" aria-hidden="true" style={{ overflow: "visible" }}>
      <path className="ink" d="M4 22 C 9 20, 11 24, 16 21 S 23 18, 25 20" fill="none" stroke={GOLD} strokeWidth="2" strokeLinecap="round" />
      <g className="nib"><path d="M0 0 L 7 -12 L 9 -10 L 2 1 Z" fill={NAVY} /><circle cx="1" cy="0" r="1.2" fill={GOLD} /></g>
    </svg>
  );
}

export function PhaseGlyph({ phase }: { phase: Phase }) {
  if (phase === "search") return <GlyphSearch />;
  if (phase === "read") return <GlyphRead />;
  if (phase === "sql") return <GlyphFigures />;
  if (phase === "write") return <GlyphWrite />;
  return <MarkSwap />;
}

/** Small spinning arc for a step still running. */
export function Spinner() {
  const ref = useRef<SVGSVGElement>(null);
  useGSAP(() => { if (!reduced()) gsap.to(ref.current, { rotation: 360, transformOrigin: "50% 50%", duration: 1, ease: "none", repeat: -1 }); }, { scope: ref });
  return <svg ref={ref} viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeDasharray="14 10" /></svg>;
}

export function Check() {
  const ref = useRef<SVGSVGElement>(null);
  useGSAP(() => {
    if (reduced() || !ref.current) return;
    const p = ref.current.querySelector("path")!;
    const L = (p as SVGPathElement).getTotalLength();
    gsap.fromTo(p, { strokeDasharray: L, strokeDashoffset: L }, { strokeDashoffset: 0, duration: 0.35, ease: "power2.out" });
  }, { scope: ref });
  return <svg ref={ref} viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path d="M2 6.5 L5 9 L10 3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>;
}

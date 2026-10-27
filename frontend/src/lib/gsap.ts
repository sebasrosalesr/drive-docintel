// One place to register GSAP and share motion helpers. Respects prefers-reduced-motion.
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import type { RefObject } from "react";

gsap.registerPlugin(useGSAP);
gsap.defaults({ ease: "power3.out", duration: 0.55 });

export const reduced = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Stagger-in the elements matching `selector` inside `ref` once on mount. transform/opacity are cleared afterwards
 *  so no ancestor keeps a transform (which would re-anchor the fixed drawer). */
export function useReveal(ref: RefObject<HTMLElement | null>, selector = "[data-reveal]", deps: unknown[] = []) {
  useGSAP(() => {
    if (reduced() || !ref.current) return;
    const items = ref.current.querySelectorAll(selector);
    if (!items.length) return;
    gsap.from(items, { y: 16, opacity: 0, duration: 0.6, stagger: 0.06, clearProps: "transform,opacity" });
  }, { scope: ref, dependencies: deps });
}

export { gsap, useGSAP };

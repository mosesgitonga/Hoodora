import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { endSession } from "../api";
import { stopIdleWatch } from "../session";

// Ant Design's grid and responsive props ask the browser about the screen: a
// laptop, so the side menu is open and shows its labels.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: query.includes("min-width"),
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

// jsdom has no layout, and some Ant Design pieces measure scrollbars.
const getComputedStyle = window.getComputedStyle.bind(window);
window.getComputedStyle = (element: Element) => getComputedStyle(element);

afterEach(() => {
  cleanup();
  endSession("signed_out");
  stopIdleWatch();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});

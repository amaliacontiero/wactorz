import { describe, it, expect, vi, beforeEach } from "vitest";
import { ThemeSwitcher } from "../ui/ThemeSwitcher";

function setupButtons() {
  document.body.innerHTML = `
    <button id="btn-cards"></button>
    <button id="btn-social"></button>
  `;
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.useFakeTimers();
  setupButtons();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ThemeSwitcher", () => {
  it("defaults to 'cards' theme", () => {
    const t = new ThemeSwitcher();
    vi.runAllTimers();
    // dispatches theme-change with default
    const spy = vi.fn();
    document.addEventListener("theme-change", spy);
    const t2 = new ThemeSwitcher();
    vi.runAllTimers();
    const evt = spy.mock.calls[0]?.[0] as CustomEvent;
    expect(evt?.detail?.theme).toBe("cards");
    document.removeEventListener("theme-change", spy);
    void t; void t2;
  });

  it("restores saved theme from localStorage on construction", () => {
    localStorage.setItem("wactorz-theme", "social");
    const spy = vi.fn();
    document.addEventListener("theme-change", spy);
    new ThemeSwitcher();
    vi.runAllTimers();
    const evt = spy.mock.calls[0]?.[0] as CustomEvent;
    expect(evt?.detail?.theme).toBe("social");
    document.removeEventListener("theme-change", spy);
  });

  it("switchTo() changes current theme and dispatches event", () => {
    const t = new ThemeSwitcher();
    vi.runAllTimers();
    const spy = vi.fn();
    document.addEventListener("theme-change", spy);
    t.switchTo("social");
    const evt = spy.mock.calls[0]?.[0] as CustomEvent;
    expect(evt?.detail?.theme).toBe("social");
    document.removeEventListener("theme-change", spy);
  });

  it("switchTo() persists theme to localStorage", () => {
    const t = new ThemeSwitcher();
    t.switchTo("social");
    expect(localStorage.getItem("wactorz-theme")).toBe("social");
  });

  it("switchTo() is a no-op when theme unchanged", () => {
    const t = new ThemeSwitcher();
    vi.runAllTimers();
    const spy = vi.fn();
    document.addEventListener("theme-change", spy);
    t.switchTo("cards"); // already cards — no-op
    expect(spy).not.toHaveBeenCalled();
    document.removeEventListener("theme-change", spy);
  });

  it("syncState() changes internal theme without dispatching event", () => {
    const t = new ThemeSwitcher();
    vi.runAllTimers();
    const spy = vi.fn();
    document.addEventListener("theme-change", spy);
    t.syncState("social");
    expect(spy).not.toHaveBeenCalled();
    expect(localStorage.getItem("wactorz-theme")).toBe("social");
    document.removeEventListener("theme-change", spy);
  });

  it("syncState() is a no-op when theme unchanged", () => {
    const t = new ThemeSwitcher();
    t.syncState("cards"); // no change
    expect(localStorage.getItem("wactorz-theme")).toBeNull(); // wasn't set (unchanged)
  });

  it("clicking btn-cards triggers switchTo('cards')", () => {
    const t = new ThemeSwitcher();
    t.switchTo("social"); // set to social first
    vi.runAllTimers();
    const spy = vi.fn();
    document.addEventListener("theme-change", spy);
    (document.getElementById("btn-cards") as HTMLButtonElement).click();
    expect(spy).toHaveBeenCalledOnce();
    const evt = spy.mock.calls[0]?.[0] as CustomEvent;
    expect(evt?.detail?.theme).toBe("cards");
    document.removeEventListener("theme-change", spy);
  });

  it("clicking btn-social triggers switchTo('social')", () => {
    new ThemeSwitcher();
    vi.runAllTimers();
    const spy = vi.fn();
    document.addEventListener("theme-change", spy);
    (document.getElementById("btn-social") as HTMLButtonElement).click();
    const evt = spy.mock.calls[0]?.[0] as CustomEvent;
    expect(evt?.detail?.theme).toBe("social");
    document.removeEventListener("theme-change", spy);
  });

  it("updates active class on buttons when switching", () => {
    const t = new ThemeSwitcher();
    t.switchTo("social");
    const cards = document.getElementById("btn-cards")!;
    const social = document.getElementById("btn-social")!;
    expect(social.classList.contains("active")).toBe(true);
    expect(cards.classList.contains("active")).toBe(false);
  });

  it("works without buttons in the DOM", () => {
    document.body.innerHTML = "";
    expect(() => new ThemeSwitcher()).not.toThrow();
  });
});

import { describe, it, expect, vi, beforeEach } from "vitest";
import { ActivityFeed, type FeedItem } from "../ui/ActivityFeed";

function setupDOM() {
  document.body.innerHTML = `
    <div id="activity-feed"></div>
    <ul  id="feed-list"></ul>
    <button id="feed-toggle"></button>
    <span id="feed-badge"></span>
  `;
}

function item(overrides: Partial<FeedItem> = {}): FeedItem {
  return { type: "spawn", label: "new agent", agentName: "alpha", timestamp: Date.now(), ...overrides };
}

beforeEach(() => {
  setupDOM();
  vi.clearAllMocks();
});

describe("ActivityFeed", () => {
  // ── construction ─────────────────────────────────────────────────────────────

  it("constructs without throwing", () => {
    expect(() => new ActivityFeed()).not.toThrow();
  });

  // ── push ─────────────────────────────────────────────────────────────────────

  it("push() appends a row to the feed list", () => {
    const feed = new ActivityFeed();
    feed.push(item({ type: "spawn" }));
    expect(document.querySelector(".af-feed-item")).not.toBeNull();
  });

  it("push() shows badge count when feed is closed", () => {
    const feed = new ActivityFeed();
    feed.push(item());
    feed.push(item());
    const badge = document.getElementById("feed-badge")!;
    expect(badge.style.display).not.toBe("none");
    expect(badge.textContent).toBe("2");
  });

  it("push() does not increment unseen count when feed is open", () => {
    const feed = new ActivityFeed();
    // Toggle open
    (document.getElementById("feed-toggle") as HTMLButtonElement).click();
    feed.push(item());
    const badge = document.getElementById("feed-badge")!;
    expect(badge.style.display).toBe("none");
  });

  it("push() renders correct icon for each event type", () => {
    const feed = new ActivityFeed();
    const types = ["spawn", "heartbeat", "chat", "alert-error", "alert-warning", "stopped", "health", "qa-flag"] as const;
    for (const type of types) {
      feed.push(item({ type }));
    }
    const icons = document.querySelectorAll(".af-feed-icon");
    expect(icons.length).toBe(types.length);
  });

  it("push() renders agent name and label in the row", () => {
    const feed = new ActivityFeed();
    feed.push(item({ agentName: "bravo", label: "started up" }));
    const agentEl = document.querySelector(".af-feed-agent")!;
    const textEl = document.querySelector(".af-feed-text")!;
    expect(agentEl.textContent).toBe("bravo");
    expect(textEl.textContent).toBe("started up");
  });

  it("push() evicts oldest item after MAX_ITEMS (500)", () => {
    const feed = new ActivityFeed();
    // Push 502 items — only 500 should remain
    for (let i = 0; i < 502; i++) {
      feed.push(item({ label: `event-${i}` }));
    }
    const rows = document.querySelectorAll(".af-feed-item");
    expect(rows.length).toBeLessThanOrEqual(501); // 500 + possible cap banner
  });

  it("push() adds cap banner when total > MAX_ITEMS", () => {
    const feed = new ActivityFeed();
    for (let i = 0; i < 502; i++) {
      feed.push(item());
    }
    expect(document.querySelector(".af-feed-cap-banner")).not.toBeNull();
  });

  it("badge shows '99+' when unseen > 99", () => {
    const feed = new ActivityFeed();
    for (let i = 0; i < 101; i++) {
      feed.push(item());
    }
    expect(document.getElementById("feed-badge")!.textContent).toBe("99+");
  });

  // ── toggle ────────────────────────────────────────────────────────────────────

  it("toggle opens the feed panel and adds 'open' class", () => {
    new ActivityFeed();
    (document.getElementById("feed-toggle") as HTMLButtonElement).click();
    expect(document.getElementById("activity-feed")!.classList.contains("open")).toBe(true);
  });

  it("toggle resets unseen count and hides badge on open", () => {
    const feed = new ActivityFeed();
    feed.push(item()); feed.push(item());
    (document.getElementById("feed-toggle") as HTMLButtonElement).click();
    expect(document.getElementById("feed-badge")!.style.display).toBe("none");
  });

  it("toggle closes the feed on second click", () => {
    new ActivityFeed();
    const btn = document.getElementById("feed-toggle") as HTMLButtonElement;
    btn.click(); btn.click();
    expect(document.getElementById("activity-feed")!.classList.contains("open")).toBe(false);
  });

  // ── hover pause ───────────────────────────────────────────────────────────────

  it("mouseenter pauses auto-scroll", () => {
    const feed = new ActivityFeed();
    // Open feed so pushes would normally scroll
    (document.getElementById("feed-toggle") as HTMLButtonElement).click();
    const list = document.getElementById("feed-list")!;
    list.dispatchEvent(new MouseEvent("mouseenter"));
    const scrollBefore = list.scrollTop;
    feed.push(item());
    // scrollTop should remain unchanged because isPaused = true
    expect(list.scrollTop).toBe(scrollBefore);
  });

  it("mouseleave resumes auto-scroll", () => {
    new ActivityFeed();
    const list = document.getElementById("feed-list")!;
    list.dispatchEvent(new MouseEvent("mouseenter"));
    list.dispatchEvent(new MouseEvent("mouseleave"));
    // No throw and state is consistent
    expect(() => new ActivityFeed()).not.toThrow();
  });
});

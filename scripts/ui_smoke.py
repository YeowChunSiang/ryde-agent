"""Browser smoke test for the Phase 3 UI (Playwright, headless Chromium).

Verifies prompt3 testing requirement 3:
  * the Evidence panel renders a real <video> player for DISP-007
  * extracted keyframes render as images
  * the Miora agent avatars load (no 404s anywhere in the run)
  * no uncaught JavaScript errors
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"

FAILED_404: list[str] = []
JS_ERRORS: list[str] = []

#: Vite's HMR socket is unreachable through the sandbox proxy — dev-server
#: noise, not an application error.
DEV_NOISE = ("websocket", "[vite]", "hmr")


def _is_dev_noise(text: str) -> bool:
    low = text.lower()
    return any(token in low for token in DEV_NOISE)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})

        page.on(
            "response",
            lambda r: FAILED_404.append(f"{r.status} {r.url}") if r.status >= 400 else None,
        )
        page.on("pageerror", lambda e: JS_ERRORS.append(str(e)))
        page.on(
            "console",
            lambda m: JS_ERRORS.append(f"console.{m.type}: {m.text}")
            if m.type == "error" and not _is_dev_noise(m.text)
            else None,
        )

        page.goto(BASE, wait_until="networkidle")
        print(f"loaded {BASE} — title={page.title()!r}")

        def run_case(case_id: str) -> None:
            """Select a case and wait for arbitration to finish.

            Note: 'COMPENSATE DRIVER' also appears in the case rail as the
            *expected* outcome, so waiting on that text alone matches instantly.
            The reliable signal is the run button returning to its idle label.
            """
            page.get_by_role("button", name=case_id).first.click()
            run_btn = page.get_by_role("button", name="Run Arbitration")
            run_btn.click()
            page.wait_for_function(
                """() => {
                    const b = [...document.querySelectorAll('button')]
                        .find(x => /Run Arbitration|Arbitrating/.test(x.textContent || ''));
                    return b && /Run Arbitration/.test(b.textContent || '') && !b.disabled;
                }""",
                timeout=120_000,
            )
            page.wait_for_timeout(800)

        # ---------------- DISP-007: video pipeline ----------------
        print("\n[1/3] selecting DISP-007 and running arbitration…")
        run_case("DISP-007")

        page.get_by_role("tab", name="Evidence").click()
        page.wait_for_timeout(1200)

        videos = page.locator("video")
        count = videos.count()
        print(f"  <video> elements rendered: {count}")
        if count == 0:
            print("  FAIL: no video player in the Evidence panel")
            return 1

        info = page.evaluate(
            """() => {
                const v = document.querySelector('video');
                return {
                    src: v?.querySelector('source')?.src ?? v?.currentSrc ?? null,
                    readyState: v?.readyState,
                    videoWidth: v?.videoWidth,
                    videoHeight: v?.videoHeight,
                    duration: v?.duration,
                };
            }"""
        )
        print(f"  video src={info['src']}")
        print(f"  readyState={info['readyState']} "
              f"{info['videoWidth']}x{info['videoHeight']} dur={info['duration']}")
        if not info["src"]:
            print("  FAIL: video element has no source")
            return 1

        # ---------------- keyframes ----------------
        print("\n[2/3] checking extracted keyframes…")
        page.wait_for_timeout(1200)
        frames = page.evaluate(
            """() => {
                const imgs = [...document.querySelectorAll('img')]
                    .filter(i => (i.getAttribute('src') || '').includes('/media/frames/'));
                return {
                    total: imgs.length,
                    loaded: imgs.filter(i => i.naturalWidth > 0).length,
                    sample: imgs.slice(0, 3).map(i => i.getAttribute('src')),
                };
            }"""
        )
        print(f"  keyframe <img>: {frames['total']} rendered, "
              f"{frames['loaded']} decoded")
        print(f"  sample: {frames['sample']}")
        if frames["total"] == 0:
            print("  FAIL: no keyframe thumbnails rendered")
            return 1
        if frames["loaded"] == 0:
            print("  FAIL: keyframes failed to decode (broken URLs)")
            return 1

        # ---------------- DISP-006: audio pipeline + avatars ----------------
        print("\n[3/3] selecting DISP-006 and checking audio + avatars…")
        run_case("DISP-006")
        page.get_by_role("tab", name="Evidence").click()
        page.wait_for_timeout(1200)

        audio = page.evaluate(
            """() => {
                const a = document.querySelector('audio');
                return a ? {src: a.querySelector('source')?.src ?? a.currentSrc} : null;
            }"""
        )
        print(f"  <audio> element: {audio}")

        # Avatars stream in as agents fire, and are lazy-loaded (correct for a
        # long feed). Force every one eager so the check proves each URL
        # actually decodes, rather than skipping off-screen ones.
        page.evaluate(
            """() => {
                document.querySelectorAll('img[loading="lazy"]')
                    .forEach(i => { i.loading = 'eager'; });
            }"""
        )
        page.wait_for_function(
            """() => {
                const imgs = [...document.querySelectorAll('img')]
                    .filter(i => (i.getAttribute('src') || '').includes('/assets/miora/agents/'));
                return imgs.length > 0 && imgs.every(i => i.complete);
            }""",
            timeout=30_000,
        )

        avatars = page.evaluate(
            """() => {
                const imgs = [...document.querySelectorAll('img')]
                    .filter(i => (i.getAttribute('src') || '').includes('/assets/miora/agents/'));
                return {
                    total: imgs.length,
                    loaded: imgs.filter(i => i.naturalWidth > 0).length,
                    roles: [...new Set(imgs.map(i => i.getAttribute('src').split('/').pop()))],
                };
            }"""
        )
        print(f"  agent avatars: {avatars['total']} rendered, "
              f"{avatars['loaded']} decoded")
        print(f"  roles seen: {sorted(avatars['roles'])}")
        if avatars["total"] == 0:
            print("  FAIL: no agent avatars rendered")
            return 1
        if avatars["loaded"] != avatars["total"]:
            print("  FAIL: some avatars failed to load")
            return 1

        page.screenshot(path="/tmp/phase3_ui.png", full_page=False)
        browser.close()

    # ---------------- report ----------------
    print("\n" + "=" * 60)
    real_404 = [f for f in FAILED_404 if "favicon" not in f]
    print(f"HTTP >=400 responses: {len(real_404)}")
    for f in real_404[:20]:
        print(f"  {f}")
    print(f"JS errors: {len(JS_ERRORS)}")
    for e in JS_ERRORS[:20]:
        print(f"  {e}")

    ok = not real_404 and not JS_ERRORS
    print("\nUI SMOKE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

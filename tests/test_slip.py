"""Test the tick-and-copy slip in a real browser.

The slip is the one bit of the tool that only exists in the browser, so it
needs a browser to test. Uses Playwright if available; skips cleanly if not.

What matters here:
  - only TICKED picks are copied, not the whole table
  - a pick listed in two tables ticks together but counts once
  - two picks from the same match warn, because they aren't independent
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def build_page():
    from accatool import demo, model, names, odds as odds_mod, rank, report

    matches = demo.synthetic_history()
    models = model.fit_all(matches, verbose=False)
    fixtures = [f for f in odds_mod.mock_fixtures() if f.is_3pm_saturday()]
    resolved, _ = names.resolve_fixtures(fixtures, models)
    legs, _ = rank.build_legs(resolved, models)
    safest, value, both = rank.shortlists(legs)
    sweet = rank.sweet_spot(legs)

    html = report.render(safest, value, both, legs, {
        "date": "22 August 2026", "n_fixtures": len(resolved),
        "n_matches": len(matches), "mode": "test",
    }, sweet=sweet, sweet_summary=rank.acca_summary(sweet[:6]))

    out = ROOT / ".slip-test.html"
    out.write_text(html, encoding="utf-8")
    return out


def test_slip():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  SKIP: playwright not installed (pip install playwright)")
        return

    page_path = build_page()
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception as exc:
                print(f"  SKIP: no browser available ({exc})")
                return

            ctx = browser.new_context(viewport={"width": 1240, "height": 900})
            ctx.grant_permissions(["clipboard-read", "clipboard-write"])
            pg = ctx.new_page()

            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))

            def reset():
                """Clear the slip. The Clear button lives in a bar that is
                hidden when nothing is ticked, so clicking it blindly fails
                whenever a case above found nothing to tick."""
                if pg.eval_on_selector("#slip", "e=>e.classList.contains('on')"):
                    pg.click("#slip-clear")
                else:
                    pg.evaluate("document.querySelectorAll('.pk')"
                                ".forEach(b=>{if(b.checked) b.click()})")
                pg.wait_for_timeout(250)
            pg.goto(page_path.as_uri())
            pg.wait_for_timeout(300)

            assert not errors, f"JavaScript errors on load: {errors}"
            print("  no javascript errors on load")

            n_boxes = pg.eval_on_selector_all(".pk", "e=>e.length")
            n_legs = pg.evaluate("LEGS.length")
            print(f"  {n_boxes} checkboxes across the tables, {n_legs} distinct picks")
            assert n_boxes > 0 and n_legs > 0

            # Slip stays hidden until something is ticked.
            assert not pg.eval_on_selector("#slip", "e=>e.classList.contains('on')")

            # --- only ticked picks are copied
            # Tick up to three, whatever the list length happens to be -- an
            # empty sweet-spot section is a legitimate outcome.
            n_ticked = pg.evaluate("""(()=>{
              const els=[...document.querySelectorAll('.pk')];
              const take=Math.min(3, els.length);
              for(let i=0;i<take;i++) els[i].click();
              return take;
            })()""")
            assert n_ticked >= 2, "not enough picks on the page to test the slip"
            pg.wait_for_timeout(400)   # let the slide-up transition finish
            assert pg.eval_on_selector("#slip", "e=>e.classList.contains('on')")

            pg.click("#slip-copy")
            pg.wait_for_timeout(300)
            text = pg.evaluate("navigator.clipboard.readText()")

            print("  copied slip:")
            for line in text.split("\n"):
                print("    " + line)

            picked_labels = pg.evaluate("""(()=>{
              const s=[];document.querySelectorAll('.pk').forEach(b=>{
                if(b.checked) s.push(LEGS[+b.dataset.i].label)});
              return [...new Set(s)];
            })()""")
            all_labels = pg.evaluate("LEGS.map(l=>l.label)")

            for lab in picked_labels:
                assert lab in text, f"ticked pick missing from clipboard: {lab}"
            unpicked = [l for l in all_labels if l not in picked_labels]
            leaked = [l for l in unpicked if l in text]
            assert not leaked, f"unticked picks leaked into the clipboard: {leaked[:3]}"
            print(f"  contains all {len(picked_labels)} ticked, none of the "
                  f"{len(unpicked)} unticked")

            # --- a pick in two tables ticks together, counts once
            reset()
            dup = pg.evaluate("""(()=>{
              const byI={};
              document.querySelectorAll('.pk').forEach(b=>{
                (byI[b.dataset.i]=byI[b.dataset.i]||[]).push(b)});
              const k=Object.keys(byI).find(k=>byI[k].length>1);
              if(!k) return {found:false};
              byI[k][0].click();
              return {found:true, copies:byI[k].length,
                      allChecked:byI[k].every(b=>b.checked),
                      n:document.getElementById('slip-n').textContent};
            })()""")
            if dup["found"]:
                assert dup["allChecked"], "duplicate checkboxes did not stay in sync"
                assert dup["n"] == "1 pick", f"counted more than once: {dup['n']}"
                print(f"  a pick listed {dup['copies']}x ticks together, counts once")

            # --- same-match picks warn
            reset()
            warn = pg.evaluate("""(()=>{
              const byFix={};
              document.querySelectorAll('.pk').forEach(b=>{
                const f=LEGS[+b.dataset.i].fixture;
                (byFix[f]=byFix[f]||new Set()).add(+b.dataset.i)});
              const f=Object.keys(byFix).find(f=>byFix[f].size>1);
              if(!f) return {found:false};
              [...byFix[f]].slice(0,2).forEach(i=>
                document.querySelector('.pk[data-i="'+i+'"]').click());
              return {found:true, fixture:f,
                      shown:document.getElementById('slip-warn').style.display};
            })()""")
            if warn["found"]:
                assert warn["shown"] == "block", "same-match warning did not appear"
                print(f"  warns on two picks from {warn['fixture']}")
            else:
                print("  (no two shortlisted picks share a match this run)")

            # --- clearing resets everything
            if not pg.eval_on_selector("#slip", "e=>e.classList.contains('on')"):
                pg.evaluate("document.querySelectorAll('.pk')[0].click()")
                pg.wait_for_timeout(300)
            pg.click("#slip-clear"); pg.wait_for_timeout(300)
            assert not pg.eval_on_selector("#slip", "e=>e.classList.contains('on')")
            assert pg.eval_on_selector_all(".pk", "e=>e.filter(b=>b.checked).length") == 0
            print("  clear resets the slip")

            assert not errors, f"JavaScript errors during interaction: {errors}"
            browser.close()
    finally:
        page_path.unlink(missing_ok=True)

    print("  PASS slip")


if __name__ == "__main__":
    print("test_slip")
    test_slip()
    print("\nSlip tests passed.")

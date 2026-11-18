# Browser check: Resume split button (port 8797, server PID 87452, stopped)

1 Board: PASS. Joined pill, divider visible, both halves 27.5px, inside sidebar. Menu stays inside hero tile (no clipping seen; at 390px it paints above the neighbour tile, so no :has() z-index rule needed). Escape returns focus to caret.
2 Session header: PASS. Enter opens (focus on first item), Down/Up move, Escape refocuses caret, Tab closes. Caret aria-label and tooltip are "More Resume options", aria-expanded toggles. Primary tooltip names the Option key; the caret tooltip does not.
3 Terminals toolbar: NOT TESTED. 0 terminals running.
4 Classic: PASS. No double seam; menu still open after 3s.
5 Light/Dark: PASS.
6 Caret width: 24px at 390px (iframe emulation; window resize did not take effect). FLAG: below 28px. Selectors: .cr-tile-action.tsplit-caret, .crd-btn.tsplit-caret, .mini.extlaunchbtn.tsplit-caret.
7 Console errors: none.

## Re-check (after review fixes)
Port 8797, PID 36886 (stopped), Board via localStorage tracker.ui=next, --ico-scale set on :root.
1 Hero tile (primary right / caret left / caret right / caret width; tile right 1331):
  - 100%: 1287 / 1287 / 1311 / 24 PASS
  - 150%: 1287 / 1287 / 1311 / 24 PASS, label ellipsizes (text-overflow ellipsis, scrollWidth > clientWidth)
  - 200%: same numbers PASS, label ellipsizes
  Primary never overlaps caret; caret inside tile (<= 1331) and sidebar column (1864). Caret width unchanged at 24px.
2 Menu aria-label "Resume options"; caret aria-label/title "More Resume options"; aria-expanded true; items "Open terminal", "Resume externally". NOTE: menu bounds were NOT fully inside the hero tile's box at 1864px (menuInTile=false; not a requested criterion, not investigated).
3 Console errors: none.

/*
 * addon-fit.js -- vendored alongside xterm.js for ai-tracker's Tier 3 "xterm" TRACKER_TERM_
 * RENDERER path (see xterm.js's own header comment in this same aitracker/web/vendor/ directory
 * for the full story of why two renderer implementations coexist).
 *
 * What: @xterm/addon-fit, the UMD browser build (lib/addon-fit.js) -- resizes an xterm.js
 *   Terminal's cols/rows to fill its container, the xterm-side equivalent of ext_vt.js's own
 *   computeColsRows() for the grid renderer. Exposes `window.FitAddon.FitAddon` when loaded via a
 *   plain <script> tag, same as xterm.js itself.
 * Version: 0.11.0
 * Copied from (not downloaded -- see xterm.js's header comment for why):
 *   /Users/pritammondal/Documents/Projects/AIengg/link-page/LinkPage/client/node_modules/@xterm/addon-fit/lib/addon-fit.js
 * Licence: MIT (xterm.js authors -- see xterm.js's header comment in this directory for the full
 *   notice text; @xterm/addon-fit ships under the same licence)
 *
 * Unmodified below this header.
 */
!function(e,t){"object"==typeof exports&&"object"==typeof module?module.exports=t():"function"==typeof define&&define.amd?define([],t):"object"==typeof exports?exports.FitAddon=t():e.FitAddon=t()}(globalThis,(()=>(()=>{"use strict";var e={};return(()=>{var t=e;Object.defineProperty(t,"__esModule",{value:!0}),t.FitAddon=void 0,t.FitAddon=class{activate(e){this._terminal=e}dispose(){}fit(){const e=this.proposeDimensions();if(!e||!this._terminal||isNaN(e.cols)||isNaN(e.rows))return;const t=this._terminal._core;this._terminal.rows===e.rows&&this._terminal.cols===e.cols||(t._renderService.clear(),this._terminal.resize(e.cols,e.rows))}proposeDimensions(){if(!this._terminal)return;if(!this._terminal.element||!this._terminal.element.parentElement)return;const e=this._terminal._core._renderService.dimensions;if(0===e.css.cell.width||0===e.css.cell.height)return;const t=0===this._terminal.options.scrollback?0:this._terminal.options.overviewRuler?.width||14,r=window.getComputedStyle(this._terminal.element.parentElement),i=parseInt(r.getPropertyValue("height")),o=Math.max(0,parseInt(r.getPropertyValue("width"))),s=window.getComputedStyle(this._terminal.element),n=i-(parseInt(s.getPropertyValue("padding-top"))+parseInt(s.getPropertyValue("padding-bottom"))),l=o-(parseInt(s.getPropertyValue("padding-right"))+parseInt(s.getPropertyValue("padding-left")))-t;return{cols:Math.max(2,Math.floor(l/e.css.cell.width)),rows:Math.max(1,Math.floor(n/e.css.cell.height))}}}})(),e})()));

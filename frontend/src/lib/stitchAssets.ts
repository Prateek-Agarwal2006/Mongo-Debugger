/** Bump when Stitch HTML or stitch-nav assets change — busts iframe + nav script cache. */
export const STITCH_ASSET_V = "20260629-copyright-2026";

export function stitchPageUrl(page: string): string {
  return `/static/stitch/${page}.html?v=${STITCH_ASSET_V}`;
}

export const STITCH_NAV_CSS = `/static/css/stitch-nav.css?v=${STITCH_ASSET_V}`;
export const STITCH_NAV_JS = `/static/js/stitch-nav.js?v=${STITCH_ASSET_V}`;

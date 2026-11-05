// nature kit · quality tiers. 'auto' → 'low' on software GL (SwiftShader / llvmpipe), else 'high'.
// Tiers trade instance counts, internal render scale (smooth upscale in the final pass), MSAA, rays and
// bake resolution; the look (palette, composition, motion) is identical across tiers.

export const TIERS = {
  high: { scale: 1.0, samples: 4, raySamples: 28, field: 15000, fg: 120, frame: 8, petals: 900, rays: true, ca: 1.0, skyTpd: 24, flyerTex: 1280, terrain: [190, 170] },
  medium: { scale: 0.75, samples: 0, raySamples: 24, field: 9000, fg: 90, frame: 8, petals: 560, rays: true, ca: 1.0, skyTpd: 18, flyerTex: 960, terrain: [150, 140] },
  low: { scale: 0.5, samples: 0, raySamples: 16, field: 3600, fg: 60, frame: 7, petals: 340, rays: true, ca: 0.0, skyTpd: 11, flyerTex: 640, terrain: [110, 100] },
};

/** Name of the GL renderer (unmasked when the browser allows it). */
export function glRendererName(renderer) {
  try {
    const gl = renderer.getContext();
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    return String(gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER) || '');
  } catch { return ''; }
}

/** True for CPU rasterisers. */
export const isSoftwareGL = (name) => /swiftshader|llvmpipe|software|basic render/i.test(name);

/** Resolve a tier: 'auto' | 'high' | 'medium' | 'low' | object overrides. */
export function resolveQuality(q, renderer) {
  const name = glRendererName(renderer);
  let tier = typeof q === 'string' ? q : 'auto';
  if (tier === 'auto' || !TIERS[tier]) tier = isSoftwareGL(name) ? 'low' : 'high';
  const base = { ...TIERS[tier], tier, gl: name };
  return typeof q === 'object' && q ? { ...base, ...q } : base;
}

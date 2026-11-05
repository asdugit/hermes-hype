// Font loading through the FontFace API (film.json fonts, kit fonts, scene fonts).
// Fails loudly: a missing or broken font rejects __sr.ready with the family and path.

const loaded = new Map();   // key -> Promise<FontFace>

/**
 * Load one font descriptor {family, src, weight?, style?, stretch?, display?}.
 * @param url resolved URL of src
 */
export function loadFont(desc, url, label) {
  const key = `${desc.family}|${desc.weight ?? ''}|${desc.style ?? ''}|${url}`;
  if (loaded.has(key)) return loaded.get(key);
  const p = (async () => {
    if (!desc.family || !desc.src) throw new Error(`font entry ${label || ''} needs "family" and "src"`);
    const face = new FontFace(desc.family, `url("${url}")`, {
      weight: desc.weight != null ? String(desc.weight) : 'normal',
      style: desc.style || 'normal',
      stretch: desc.stretch || 'normal',
      display: 'block',
    });
    try {
      await face.load();
    } catch (err) {
      throw new Error(`font '${desc.family}' (${desc.src}${label ? `, from ${label}` : ''}) failed to load: ${err && err.message ? err.message : err}`);
    }
    document.fonts.add(face);
    return face;
  })();
  loaded.set(key, p);
  return p;
}

/** Load a list of descriptors; resolveUrl(src) maps each src to a URL. Rejects on the first failure. */
export async function loadFonts(list, resolveUrl, label) {
  await Promise.all((list || []).map((d) => loadFont(d, resolveUrl(d.src), label)));
}

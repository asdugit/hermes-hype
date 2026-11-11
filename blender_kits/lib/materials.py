"""Premium materials for product / studio / device scenes (runs inside Blender >= 4.2).

Every factory returns a ``bpy.types.Material`` and is idempotent per name (call twice -> same material).
Principled v2 socket names (Blender 4.0+) are used through ``_set`` so a missing socket on another version
degrades to a no-op instead of raising.

Screens: ``screen()`` reproduces UI pixels exactly. Measured (EEVEE, emission plane, 24-patch UI chart, 8-bit):
view Standard + sRGB texture -> delta 0.0 (exact); Filmic + "Filmic sRGB" inverse -> mean 1.7 / max 18;
AgX + "AgX Base sRGB" inverse -> mean 16 / max 141 (AgX cannot reach saturated UI colours); AgX naive -> white
becomes 197. So scenes that show UI use the Standard view (``studio.setup_render(..., view="standard")``) and
``screen()`` picks the texture colourspace that matches whatever view the scene uses.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:  # pure helpers (cover_window, hex_rgb) stay importable without Blender (tests)
    import bpy
except ImportError:  # pragma: no cover - outside Blender
    bpy = None  # type: ignore[assignment]

_INV_VIEW = {  # view transform -> image colourspace that inverts it ("View Inverse" family in Blender's OCIO)
    "Standard": "sRGB",
    "Filmic": "Filmic sRGB",
    "AgX": "AgX Base sRGB",
    "Khronos PBR Neutral": "Khronos PBR Neutral sRGB",
}


def hex_rgb(h: str | tuple | list, default: tuple = (0.5, 0.5, 0.5)) -> tuple[float, float, float]:
    """'#7c3aed' / (r, g, b) 0-1 or 0-255 -> LINEAR rgb (for shader colour sockets)."""
    if isinstance(h, (tuple, list)) and len(h) >= 3:
        c = [float(v) for v in h[:3]]
        if max(c) > 1.0:
            c = [v / 255.0 for v in c]
    else:
        s = str(h or "").strip().lstrip("#")
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        try:
            c = [int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        except ValueError:
            return default
    return tuple(srgb_to_linear(v) for v in c)  # type: ignore[return-value]


def srgb_to_linear(v: float) -> float:
    """sRGB transfer -> linear."""
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _set(node: Any, name: str, value: Any) -> None:
    sock = node.inputs.get(name)
    if sock is not None:
        try:
            sock.default_value = value
        except (TypeError, ValueError):
            pass


def _new(name: str) -> tuple[bpy.types.Material, Any, Any, bool]:
    """Fresh material with a Principled BSDF + output; returns (mat, nodes, bsdf, existed)."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        return mat, mat.node_tree.nodes, bsdf, True
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    return mat, nodes, bsdf, False


def principled(name: str, color=(0.5, 0.5, 0.5), *, metallic: float = 0.0, roughness: float = 0.5,
               coat: float = 0.0, coat_roughness: float = 0.03, specular: float = 0.5, alpha: float = 1.0,
               emission=None, emission_strength: float = 0.0) -> bpy.types.Material:
    """Generic Principled material; ``color`` is hex or linear rgb."""
    mat, _nodes, b, existed = _new(name)
    if existed:
        return mat
    rgb = hex_rgb(color) if isinstance(color, str) else tuple(color)[:3]
    _set(b, "Base Color", (*rgb, 1.0))
    _set(b, "Metallic", metallic)
    _set(b, "Roughness", roughness)
    _set(b, "Specular IOR Level", specular)
    _set(b, "Coat Weight", coat)
    _set(b, "Coat Roughness", coat_roughness)
    if emission is not None:
        e = hex_rgb(emission) if isinstance(emission, str) else tuple(emission)[:3]
        _set(b, "Emission Color", (*e, 1.0))
        _set(b, "Emission Strength", emission_strength)
    if alpha < 1.0:
        _set(b, "Alpha", alpha)
    return mat


def car_paint(color="#b5121b", *, name: str | None = None, flake: float = 0.6, flake_scale: float = 900.0,
              roughness: float = 0.32, metallic: float = 0.55, coat: float = 1.0) -> bpy.types.Material:
    """Metallic car paint: tinted metallic base with micro-flake normal sparkle under a glossy clear coat."""
    mat, nodes, b, existed = _new(name or f"sr_carpaint_{str(color).lstrip('#')}")
    if existed:
        return mat
    links = mat.node_tree.links
    rgb = hex_rgb(color)
    _set(b, "Base Color", (*rgb, 1.0))
    _set(b, "Metallic", metallic)
    _set(b, "Roughness", roughness)
    _set(b, "Coat Weight", coat)
    _set(b, "Coat Roughness", 0.025)
    _set(b, "Coat IOR", 1.5)
    if flake > 0:
        tc = nodes.new("ShaderNodeTexCoord")
        vor = nodes.new("ShaderNodeTexVoronoi")
        vor.inputs["Scale"].default_value = flake_scale
        links.new(tc.outputs["Object"], vor.inputs["Vector"])
        # random per-cell colour -> perturbed normal for flakes
        sub = nodes.new("ShaderNodeVectorMath")
        sub.operation = "SUBTRACT"
        sub.inputs[1].default_value = (0.5, 0.5, 0.5)
        links.new(vor.outputs["Color"], sub.inputs[0])
        nmap = nodes.new("ShaderNodeBump")
        nmap.inputs["Strength"].default_value = 0.12 * flake
        sep = nodes.new("ShaderNodeSeparateXYZ")
        links.new(sub.outputs[0], sep.inputs[0])
        links.new(sep.outputs[0], nmap.inputs["Height"])
        links.new(nmap.outputs["Normal"], b.inputs["Normal"])
    return mat


def glass(name: str = "sr_glass", tint=(0.92, 0.95, 0.97), *, roughness: float = 0.02,
          ior: float = 1.45, dark: float = 0.0) -> bpy.types.Material:
    """Clear (or tinted/dark) glass. EEVEE: refraction needs ray tracing; blend mode stays opaque-raytraced."""
    mat, _n, b, existed = _new(name)
    if existed:
        return mat
    t = hex_rgb(tint) if isinstance(tint, str) else tint
    t = tuple(v * (1 - dark) for v in t)
    _set(b, "Base Color", (*t, 1.0))
    _set(b, "Roughness", roughness)
    _set(b, "IOR", ior)
    _set(b, "Transmission Weight", 1.0)
    try:
        mat.surface_render_method = "DITHERED"
        mat.use_raytrace_refraction = True
    except AttributeError:
        pass
    return mat


def chrome(name: str = "sr_chrome", *, roughness: float = 0.06) -> bpy.types.Material:
    """Polished chrome."""
    return principled(name, (0.92, 0.92, 0.94), metallic=1.0, roughness=roughness)


def aluminium(name: str = "sr_alu", color=(0.80, 0.81, 0.83), *, roughness: float = 0.28,
              brushed: float = 0.6, axis: str = "X") -> bpy.types.Material:
    """Anodised / brushed aluminium: metallic with stretched-noise roughness streaks (EEVEE has no anisotropy)."""
    mat, nodes, b, existed = _new(name)
    if existed:
        return mat
    links = mat.node_tree.links
    rgb = hex_rgb(color) if isinstance(color, str) else color
    _set(b, "Base Color", (*rgb, 1.0))
    _set(b, "Metallic", 1.0)
    _set(b, "Roughness", roughness)
    if brushed > 0:
        tc = nodes.new("ShaderNodeTexCoord")
        mp = nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (1.0, 260.0, 260.0) if axis == "X" else (260.0, 1.0, 260.0)
        links.new(tc.outputs["Object"], mp.inputs["Vector"])
        nz = nodes.new("ShaderNodeTexNoise")
        nz.inputs["Scale"].default_value = 3.0
        nz.inputs["Detail"].default_value = 6.0
        links.new(mp.outputs[0], nz.inputs["Vector"])
        mr = nodes.new("ShaderNodeMapRange")
        mr.inputs["To Min"].default_value = roughness * (1 - 0.35 * brushed)
        mr.inputs["To Max"].default_value = roughness * (1 + 0.35 * brushed)
        links.new(nz.outputs["Fac"], mr.inputs["Value"])
        links.new(mr.outputs["Result"], b.inputs["Roughness"])
    return mat


def rubber(name: str = "sr_rubber") -> bpy.types.Material:
    """Tyre rubber: near-black, rough, low specular."""
    return principled(name, (0.018, 0.018, 0.02), roughness=0.82, specular=0.3)


def matte_plastic(color="#1d1f24", name: str | None = None, *, roughness: float = 0.55) -> bpy.types.Material:
    """Matte plastic / soft-touch."""
    return principled(name or f"sr_plastic_{str(color).lstrip('#')}", color, roughness=roughness, specular=0.4)


def black_glass(name: str = "sr_blackglass", *, roughness: float = 0.04) -> bpy.types.Material:
    """Glossy black glass (device bezels / off screens)."""
    return principled(name, (0.004, 0.004, 0.005), roughness=roughness, specular=0.6, coat=1.0, coat_roughness=0.02)


def emissive(name: str, color=(1, 1, 1), strength: float = 5.0) -> bpy.types.Material:
    """Pure emission (softbox cards, light strips)."""
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs[0].default_value = (*(hex_rgb(color) if isinstance(color, str) else color), 1.0)
    em.inputs[1].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs[0])
    return mat


def load_image(path: str | Path, *, colorspace: str = "sRGB", sequence: bool = False) -> bpy.types.Image:
    """Load an image / movie / first frame of a sequence once (check_existing)."""
    img = bpy.data.images.load(str(path), check_existing=True)
    try:
        img.colorspace_settings.name = colorspace
    except TypeError:
        pass
    if sequence:
        img.source = "SEQUENCE"
    return img


def screen_colorspace(scene: bpy.types.Scene | None = None) -> str:
    """Texture colourspace that makes UI pixels display exactly under the scene's current view transform."""
    sc = scene or bpy.context.scene
    return _INV_VIEW.get(sc.view_settings.view_transform, "sRGB")


def screen(name: str, image: bpy.types.Image | None, *, scene: bpy.types.Scene | None = None,
           glare: float = 0.12, brightness: float = 1.0, off_color=(0.002, 0.002, 0.003),
           uv_window: bool = True) -> bpy.types.Material:
    """Emissive display that shows ``image`` with exact UI colours.

    - Colour: emission = texture (colourspace chosen by ``screen_colorspace``), strength = brightness / 2**exposure,
      so a pixel #faf8ff renders #faf8ff under the Standard view with look None.
    - ``glare``: weight of a glossy cover-glass coat (reflections of the studio on the glass; 0 = matte, exact).
    - ``uv_window``: a Mapping node named "sr_window" (Location/Scale on UV) lets scenes scroll/crop the image
      (``set_window``); default shows the full image.
    - A Value node "sr_power" (0..1) multiplies the emission, used for "screen turns on" animation.
    """
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    sc = scene or bpy.context.scene
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    b = nodes.get("Principled BSDF")
    _set(b, "Base Color", (*off_color, 1.0))
    _set(b, "Roughness", 0.3)
    _set(b, "Specular IOR Level", 0.0)
    _set(b, "Coat Weight", glare)
    _set(b, "Coat Roughness", 0.015)
    _set(b, "Coat IOR", 1.5)
    power = nodes.new("ShaderNodeValue")
    power.name = power.label = "sr_power"
    power.outputs[0].default_value = 1.0
    strength = brightness / (2.0 ** sc.view_settings.exposure)
    mul = nodes.new("ShaderNodeMath")
    mul.name = "sr_strength"
    mul.operation = "MULTIPLY"
    mul["sr_brightness"] = float(brightness)
    mul.inputs[1].default_value = strength
    links.new(power.outputs[0], mul.inputs[0])
    links.new(mul.outputs[0], b.inputs["Emission Strength"])
    if image is not None:
        try:
            image.colorspace_settings.name = screen_colorspace(sc)
        except TypeError:
            pass
        tex = nodes.new("ShaderNodeTexImage")
        tex.name = "sr_tex"
        tex.image = image
        tex.interpolation = "Cubic"
        tex.extension = "EXTEND"
        if image.source in ("MOVIE", "SEQUENCE"):
            tex.image_user.use_auto_refresh = True
            tex.image_user.frame_start = 1
            tex.image_user.frame_duration = max(1, image.frame_duration)
        if uv_window:
            uv = nodes.new("ShaderNodeTexCoord")
            mp = nodes.new("ShaderNodeMapping")
            mp.name = "sr_window"
            links.new(uv.outputs["UV"], mp.inputs["Vector"])
            links.new(mp.outputs[0], tex.inputs["Vector"])
        # letterbox fill: where the (contain-fit) window leaves the image the texture CLIPs to alpha 0 and the
        # screen shows the page colour ``set_fill`` puts in "sr_fill" (black until then); opaque pixels pass
        # through exactly (factor 1 -> B)
        mix = nodes.new("ShaderNodeMix")
        mix.name = "sr_fill"
        mix.data_type = "RGBA"
        mix.blend_type = "MIX"
        _mix_socket(mix, "A").default_value = (0.0, 0.0, 0.0, 1.0)
        links.new(tex.outputs["Alpha"], mix.inputs[0])
        links.new(tex.outputs["Color"], _mix_socket(mix, "B"))
        links.new(_mix_socket(mix, "Result", out=True), b.inputs["Emission Color"])
    else:
        _set(b, "Emission Color", (0, 0, 0, 1))
    try:
        mat.surface_render_method = "DITHERED"
    except AttributeError:
        pass
    return mat


def sync_screens(scene: bpy.types.Scene | None = None) -> int:
    """Re-apply the exact-UI colourspace + exposure compensation to every ``screen()`` material (call after the
    view transform is final). Returns how many screens were synced."""
    sc = scene or bpy.context.scene
    cs = screen_colorspace(sc)
    n = 0
    for mat in bpy.data.materials:
        nt = mat.node_tree if mat.use_nodes else None
        if nt is None or nt.nodes.get("sr_power") is None:
            continue
        for tname in ("sr_tex", "sr_tex_fill"):
            tex = nt.nodes.get(tname)
            if tex is not None and tex.image is not None:
                try:
                    tex.image.colorspace_settings.name = cs
                except TypeError:
                    pass
        for nd in nt.nodes:
            if nd.type == "MATH" and nd.operation == "MULTIPLY" and nd.name.startswith("sr_strength"):
                nd.inputs[1].default_value = float(nd.get("sr_brightness", 1.0)) / (2.0 ** sc.view_settings.exposure)
        n += 1
    return n


def set_window(mat: bpy.types.Material, *, x0: float = 0.0, y0: float = 0.0, sx: float = 1.0, sy: float = 1.0,
               frame: int | None = None) -> None:
    """Show the image window [x0, x0+sx] x [y0, y0+sy] (UV fractions, y from the BOTTOM) on the screen.

    Optionally keyframes it at ``frame`` (linear interpolation is applied by the caller via ``linearize``).
    """
    mp = mat.node_tree.nodes.get("sr_window")
    if mp is None:
        return
    mp.inputs["Location"].default_value = (x0, y0, 0.0)
    mp.inputs["Scale"].default_value = (sx, sy, 1.0)
    if frame is not None:
        mp.inputs["Location"].keyframe_insert("default_value", frame=frame)
        mp.inputs["Scale"].keyframe_insert("default_value", frame=frame)


def _mix_socket(node: Any, name: str, *, out: bool = False) -> Any:
    """The colour socket ``name`` of a Mix node (it has float/vector/colour sockets of the same name)."""
    socks = node.outputs if out else node.inputs
    for sk in socks:
        if sk.name == name and sk.type == "RGBA":
            return sk
    return socks[name]


def set_fill(mat: bpy.types.Material, fill_image: bpy.types.Image | None) -> None:
    """Letterbox colour of a screen: a 1x1 image sampled through the SAME colour management as the screen
    texture (so a page colour #0e0e10 next to the capture renders #0e0e10 too)."""
    nt = mat.node_tree
    mix = nt.nodes.get("sr_fill")
    if mix is None or fill_image is None:
        return
    tex = nt.nodes.get("sr_tex")
    ft = nt.nodes.get("sr_tex_fill") or nt.nodes.new("ShaderNodeTexImage")
    ft.name = "sr_tex_fill"
    ft.image = fill_image
    ft.interpolation = "Closest"
    ft.extension = "EXTEND"
    if tex is not None and tex.image is not None:
        try:
            fill_image.colorspace_settings.name = tex.image.colorspace_settings.name
        except TypeError:
            pass
    nt.links.new(ft.outputs["Color"], _mix_socket(mix, "A"))


def set_clip(mat: bpy.types.Material, clip: bool) -> None:
    """CLIP the screen texture outside its image (letterboxed window -> fill colour) or EXTEND it (cover)."""
    tex = mat.node_tree.nodes.get("sr_tex") if mat.node_tree else None
    if tex is not None:
        tex.extension = "CLIP" if clip else "EXTEND"


def fit_window(img_w: float, img_h: float, scr_w: float, scr_h: float, *, align: str = "top",
               fit: str = "auto", max_crop: float = 0.12) -> tuple[tuple[float, float, float, float], str]:
    """Window + the fit actually used. ``auto`` = cover when cover loses at most ``max_crop`` of the image along
    the cropped axis (a 16:9 capture on a 16:10 laptop) or when the image is a long scrolling page (at least 2:1
    tall and taller than the screen: its top shows, scenes scroll it), else contain: an element crop, a portrait
    card or a desktop capture on a phone is shown WHOLE inside the bezel (letterboxed in its page colour), never
    magnified past the screen edges."""
    if fit == "auto":
        ia, sa = img_w / max(img_h, 1e-6), scr_w / max(scr_h, 1e-6)
        lost = 1.0 - (sa / ia if ia > sa else ia / sa)
        page = img_h >= 2.0 * img_w and ia < sa
        fit = "cover" if page or lost <= max_crop + 1e-9 else "contain"
    return cover_window(img_w, img_h, scr_w, scr_h, align=align, fit=fit), fit


def set_power(mat: bpy.types.Material, value: float, frame: int | None = None) -> None:
    """Screen on/off level (0..1); keyframed when ``frame`` is given."""
    nd = mat.node_tree.nodes.get("sr_power")
    if nd is None:
        return
    nd.outputs[0].default_value = value
    if frame is not None:
        nd.outputs[0].keyframe_insert("default_value", frame=frame)


def cover_window(img_w: float, img_h: float, scr_w: float, scr_h: float, *, align: str = "top",
                 fit: str = "cover") -> tuple[float, float, float, float]:
    """UV window (x0, y0, sx, sy) that fits an img_w x img_h image on a scr_w x scr_h screen without distortion.

    ``cover`` crops the overflow (web pages: keep the top, ``align='top'``); ``contain`` letterboxes (the screen
    material CLIPs outside the image and shows the page colour from ``set_fill``). Never mirrors: sx, sy > 0.
    """
    ia, sa = img_w / max(img_h, 1e-6), scr_w / max(scr_h, 1e-6)
    if fit == "contain":
        if ia > sa:
            sy = ia / sa
            return 0.0, (1 - sy) / 2, 1.0, sy
        sx = sa / ia
        return (1 - sx) / 2, 0.0, sx, 1.0
    if ia > sa:  # image wider: crop sides
        sx = sa / ia
        return (1 - sx) / 2, 0.0, sx, 1.0
    sy = ia / sa  # image taller: crop bottom (top-aligned) or centre
    y0 = 1.0 - sy if align == "top" else (1.0 - sy) / 2
    return 0.0, y0, 1.0, sy


def linearize(id_data: Any) -> None:
    """Set every keyframe of an ID's action to LINEAR interpolation (per-frame keys -> exact values)."""
    ad = getattr(id_data, "animation_data", None)
    act = ad.action if ad else None
    if act is None:
        return
    for fc in _fcurves(act, ad):
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"


def _fcurves(act: Any, ad: Any = None) -> list:
    """F-curves of an action on Blender 4.2 (act.fcurves) and 5.x (layered actions: layers/strips/channelbags)."""
    fcs = getattr(act, "fcurves", None)
    if fcs is not None and len(fcs):
        return list(fcs)
    out = []
    for layer in getattr(act, "layers", []):
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                out.extend(bag.fcurves)
    return out


def ui_luma(rgb_lin: tuple) -> float:
    """Approximate relative luminance of a linear colour."""
    r, g, b = rgb_lin[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


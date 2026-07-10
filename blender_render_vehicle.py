import json
import math
import os
import re
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


TEXTURE_EXTENSIONS = (".png", ".dds", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff")
NON_COLOR_HINTS = ("bump", "normal", "nrm", "nrml", "spec", "rough", "gloss")
LIVERY_HINTS = ("livery", "sign", "skin", "decal", "police", "ems", "lsmd", "sheriff")
GENERIC_AUTO_LIVERY_PREFIXES = ("police_new", "vehicle_", "generic_", "vehshare")
WHEEL_COLOR_HINTS = ("wheel", "rim", "alloy")
WHEEL_COLOR_EXCLUDE_HINTS = (
    "normal",
    "nrm",
    "nrml",
    "spec",
    "rough",
    "gloss",
    "dirt",
    "mud",
    "tyrewall",
    "tirewall",
    "sidewall",
    "tire",
    "tyre",
    "pzero",
)
COLOR_TEXTURE_EXCLUDE_HINTS = (
    "normal",
    "nrm",
    "nrml",
    "bump",
    "spec",
    "rough",
    "gloss",
    "dirt",
    "mud",
    "glass",
    "window",
    "wheel",
    "tire",
    "tyre",
    "plate",
    "light",
    "emiss",
    "interior",
    "fabric",
    "leather",
)
PAINT_COLOR = (0.045, 0.045, 0.04, 1.0)
CHROME_FALLBACK_COLOR = (0.26, 0.27, 0.26, 1.0)
MODEL_TONE = "black"
ASSET_KIND = "vehicle"
MODEL_TONE_PALETTE = {
    "gray": ((0.12, 0.13, 0.12, 1.0), (0.26, 0.27, 0.26, 1.0)),
    "white": ((0.62, 0.64, 0.61, 1.0), (0.26, 0.27, 0.26, 1.0)),
    "black": ((0.045, 0.045, 0.04, 1.0), (0.26, 0.27, 0.26, 1.0)),
}
VEHICLE_BODY_PAINT_LAYERS = {1, 2, 3}
GREEN_SCREEN_COLOR = (0.0, 1.0, 0.0)
PNG_ALPHA_HALF_STEP = 0.5 / 255.0
MIN_PROJECTED_ORTHO_SCALE = 0.0001


def apply_model_tone(job):
    global PAINT_COLOR, CHROME_FALLBACK_COLOR, MODEL_TONE, ASSET_KIND
    tone = str(job.get("model_tone", "black")).lower()
    paint, chrome = MODEL_TONE_PALETTE.get(tone, MODEL_TONE_PALETTE["black"])
    MODEL_TONE = tone
    ASSET_KIND = str(job.get("asset_kind", "vehicle")).lower()
    if ASSET_KIND != "vehicle" and tone == "gray":
        paint = (0.18, 0.18, 0.17, 1.0)
        chrome = (0.16, 0.16, 0.15, 1.0)
    PAINT_COLOR = paint
    CHROME_FALLBACK_COLOR = chrome
    print(f"Model tone: {tone} paint={PAINT_COLOR[:3]}")


def parse_args(argv):
    args = {}
    for arg in argv:
        if "=" in arg and not arg.startswith("-"):
            key, value = arg.split("=", 1)
            args[key] = value
    return args


def operator_available(name):
    try:
        getattr(bpy.ops.sollumz, name).get_rna_type()
        return True
    except Exception:
        return False


def resolve_sollumz(addon_path):
    path = Path(addon_path).resolve()
    if (path / "__init__.py").exists():
        return path.parent, path.name
    package = path / "Sollumz"
    if (package / "__init__.py").exists():
        return path, "Sollumz"
    raise FileNotFoundError(f"Invalid Sollumz path: {path}")


def ensure_sollumz(job):
    if operator_available("import_assets"):
        return

    user_config = job.get("blender_user_config") or os.environ.get("BLENDER_USER_CONFIG")
    if user_config:
        os.environ["BLENDER_USER_CONFIG"] = str(Path(user_config).resolve())
        Path(os.environ["BLENDER_USER_CONFIG"]).mkdir(parents=True, exist_ok=True)

    user_scripts = job.get("blender_user_scripts") or os.environ.get("BLENDER_USER_SCRIPTS")
    if user_scripts:
        os.environ["BLENDER_USER_SCRIPTS"] = str(Path(user_scripts).resolve())
        Path(os.environ["BLENDER_USER_SCRIPTS"]).mkdir(parents=True, exist_ok=True)

    addon_path = job.get("sollumz_path") or os.environ.get("SOLLUMZ_ADDON_PATH")
    module_names = []
    if addon_path:
        addon_parent, module_name = resolve_sollumz(addon_path)
        if str(addon_parent) not in sys.path:
            sys.path.insert(0, str(addon_parent))
        module_names.append(module_name)
    module_names.append("Sollumz")

    import addon_utils

    errors = []
    for module_name in dict.fromkeys(module_names):
        try:
            addon_utils.enable(module_name, default_set=False, persistent=False)
            if operator_available("import_assets"):
                return
            errors.append(f"{module_name}: enabled but operator not registered")
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")
    raise RuntimeError("Could not enable Sollumz. " + " | ".join(errors))


def call_sollumz_operator(name, **kwargs):
    operator = getattr(bpy.ops.sollumz, name)
    props = operator.get_rna_type().properties.keys()
    filtered = {k: v for k, v in kwargs.items() if k in props}
    skipped = sorted(set(kwargs) - set(filtered))
    if skipped:
        print(f"Skip unsupported args for {name}: {skipped}")
    return operator(**filtered)


def import_assets(source_dir, names):
    names = [name for name in names if name and (source_dir / name).exists()]
    if not names:
        return None
    print(f"Import: {names}")
    return call_sollumz_operator(
        "import_assets",
        directory=str(source_dir),
        files=[{"name": name} for name in names],
        use_custom_settings=True,
        import_as_asset=False,
        split_by_group=True,
        dwd_import_external_skeleton="NO",
        frag_import_vehicle_windows=False,
        ymap_skip_missing_entities=True,
        ymap_exclude_entities=False,
        ymap_box_occluders=False,
        ymap_model_occluders=False,
        ymap_car_generators=False,
        ymap_instance_entities=True,
        ytyp_mlo_instance_entities=True,
        textures_mode="PACK",
        textures_extract_custom_directory="",
    )


def normalized_texture_name(value):
    if not value:
        return ""
    name = str(value).strip().replace("\\", "/").split("/")[-1]
    for ext in TEXTURE_EXTENSIONS:
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    name = re.sub(r"\s+\[[^\]]+\]$", "", name)
    name = re.sub(r"\.\d{3}$", "", name)
    return name.lower()


def build_texture_index(texture_dir):
    root = Path(texture_dir or "")
    if not root.is_dir():
        return {}

    priority = {".png": 0, ".dds": 1, ".tga": 2, ".jpg": 3, ".jpeg": 3, ".bmp": 4, ".tif": 5, ".tiff": 5}
    index = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXTURE_EXTENSIONS:
            continue
        key = normalized_texture_name(path.name)
        if not key:
            continue
        old = index.get(key)
        if old is None or priority.get(path.suffix.lower(), 99) < priority.get(old.suffix.lower(), 99):
            index[key] = path
    print(f"Texture files: {len(index)} from {root}")
    return index


def node_texture_candidates(node, material):
    candidates = []
    for attr in ("sollumz_texture_name",):
        value = getattr(node, attr, "")
        if value:
            candidates.append(value)

    image = getattr(node, "image", None)
    if image:
        candidates.append(image.name)
        if image.filepath:
            candidates.append(image.filepath)

    if material:
        candidates.append(material.name)
    return [normalized_texture_name(value) for value in candidates if normalized_texture_name(value)]


def is_non_color_node(node, path):
    combined = f"{node.name} {getattr(node, 'label', '')} {path.stem}".lower()
    return is_non_color_texture_name(path.stem) or any(hint in combined for hint in NON_COLOR_HINTS)


def set_image_color_space(image, is_data):
    try:
        image.colorspace_settings.is_data = bool(is_data)
    except Exception:
        try:
            image.colorspace_settings.name = "Non-Color" if is_data else "sRGB"
        except Exception:
            pass


def make_solid_image(name, color, is_data=False):
    image_name = f"vehicle_renderer_{name}"
    image = bpy.data.images.get(image_name)
    if image is None:
        image = bpy.data.images.new(image_name, width=4, height=4, alpha=True)
        image.pixels.foreach_set(list(color) * 16)
        image.pack()
        image.update()
    set_image_color_space(image, is_data)
    return image


def make_principled_material(name, color, roughness=0.35, metallic=0.0):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = color
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        set_input(bsdf, "Base Color", color)
        set_input(bsdf, "Roughness", roughness)
        set_input(bsdf, "Metallic", metallic)
        set_input(bsdf, "Alpha", color[3])
        set_input(bsdf, "Specular IOR Level", 0.65)
        set_input(bsdf, "Coat Weight", 0.45)
        set_input(bsdf, "Coat Roughness", 0.12)
    return mat


def fallback_color_for_name(name):
    lower = name.lower()
    if any(hint in lower for hint in ("normal", "nrm", "nrml", "bump")):
        return "normal", (0.5, 0.5, 1.0, 1.0), True
    if any(hint in lower for hint in ("spec", "rough", "gloss")):
        return "spec", (0.55, 0.55, 0.55, 1.0), True
    if any(hint in lower for hint in ("wheel", "rim", "brake", "disc")):
        return "wheel", (0.018, 0.018, 0.017, 1.0), False
    if "glass" in lower or "window" in lower:
        return "glass", (0.03, 0.07, 0.08, 0.65), False
    if any(hint in lower for hint in ("black", "tyre", "tire", "rubber", "burnt")):
        return "black", (0.015, 0.015, 0.014, 1.0), False
    return "paint", PAINT_COLOR, False


def is_magenta_color(color):
    try:
        r, g, b = color[:3]
    except Exception:
        return False
    return r > 0.65 and b > 0.65 and g < 0.28


def neutralize_magenta_materials():
    changed = 0
    for material_obj in bpy.data.materials:
        if not material_obj.use_nodes or not material_obj.node_tree:
            continue
        for node in material_obj.node_tree.nodes:
            if node.bl_idname != "ShaderNodeBsdfPrincipled":
                continue
            base = node.inputs.get("Base Color")
            if base and not base.is_linked and is_magenta_color(base.default_value):
                base.default_value = PAINT_COLOR
                material_obj.diffuse_color = PAINT_COLOR
                changed += 1
    return changed


def set_input(node, name, value):
    socket = node.inputs.get(name)
    if socket and not socket.is_linked:
        socket.default_value = value


def force_input(node, name, value):
    socket = node.inputs.get(name)
    if not socket:
        return False
    for link in list(socket.links):
        node.id_data.links.remove(link)
    socket.default_value = value
    return True


def set_first_input(node, names, value):
    for name in names:
        socket = node.inputs.get(name)
        if socket and not socket.is_linked:
            socket.default_value = value
            return True
    return False


def image_is_generated_fallback(image):
    return bool(image and image.name.startswith("vehicle_renderer_"))


def material_has_real_texture(material_obj):
    if not material_obj or not material_obj.use_nodes or not material_obj.node_tree:
        return False
    for node in material_obj.node_tree.nodes:
        if node.bl_idname != "ShaderNodeTexImage":
            continue
        image = getattr(node, "image", None)
        if image and not image_is_generated_fallback(image):
            return True
    return False


def material_has_fallback_texture(material_obj):
    if not material_obj or not material_obj.use_nodes or not material_obj.node_tree:
        return False
    for node in material_obj.node_tree.nodes:
        if node.bl_idname != "ShaderNodeTexImage":
            continue
        if image_is_generated_fallback(getattr(node, "image", None)):
            return True
    return False


def material_has_renderer_color_texture(material_obj):
    if not material_obj or not material_obj.use_nodes or not material_obj.node_tree:
        return False
    for node in material_obj.node_tree.nodes:
        if node.bl_idname == "ShaderNodeBsdfPrincipled" and base_color_has_upstream_texture(node):
            return True
    for node in material_obj.node_tree.nodes:
        if node.bl_idname != "ShaderNodeTexImage":
            continue
        if node.name == "vehicle_renderer_livery_texture":
            image = getattr(node, "image", None)
            return bool(image and not image_is_generated_fallback(image))
    return False


def material_uses_generic_tiny_texture(material_obj, names):
    if not material_obj or not material_obj.use_nodes or not material_obj.node_tree:
        return False
    normalized_names = {normalized_texture_name(name) for name in names}
    for node in material_obj.node_tree.nodes:
        if node.bl_idname != "ShaderNodeTexImage":
            continue
        image = getattr(node, "image", None)
        if not image:
            continue
        image_name = normalized_texture_name(image.name)
        if image_name not in normalized_names:
            continue
        try:
            width, height = image.size
            if max(width, height) <= 8:
                return True
        except Exception:
            return True
    return False


def is_livery_texture(path):
    name = path.stem.lower()
    return any(hint in name for hint in LIVERY_HINTS) and not any(
        hint in name for hint in COLOR_TEXTURE_EXCLUDE_HINTS
    )


def load_texture_manifest(job):
    manifest_path = job.get("texture_manifest_path")
    if not manifest_path and job.get("texture_dir"):
        manifest_path = str(Path(job["texture_dir"]) / "_texture_manifest.json")
    if not manifest_path:
        return {"local": set(), "shared": set()}

    path = Path(manifest_path)
    if not path.is_file():
        return {"local": set(), "shared": set()}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Texture manifest ignored: {exc}")
        return {"local": set(), "shared": set()}

    return {
        "local": {normalized_texture_name(name) for name in data.get("local", [])},
        "shared": {normalized_texture_name(name) for name in data.get("shared", [])},
    }


def write_texture_bind_report(
    job,
    texture_index,
    texture_manifest,
    matched,
    missing,
    livery_links,
    generic_links,
    part_links,
    window_tunes,
    surface_tunes,
):
    report_path = job.get("texture_bind_report_path")
    if not report_path and job.get("texture_dir"):
        report_path = str(Path(job["texture_dir"]) / "_texture_bind_report.json")
    if not report_path:
        return

    path = Path(report_path)
    report = {
        "model": job.get("model", ""),
        "asset_kind": job.get("asset_kind", "vehicle"),
        "texture_dir": job.get("texture_dir", ""),
        "texture_files": len(texture_index),
        "matched": int(matched),
        "missing": sorted(str(name) for name in missing),
        "livery_links": int(livery_links),
        "generic_links": int(generic_links),
        "part_links": int(part_links),
        "window_tunes": int(window_tunes),
        "surface_tunes": int(surface_tunes),
        "manifest": {
            key: sorted(str(name) for name in value)
            for key, value in texture_manifest.items()
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Texture bind report: {path}")
    except Exception as exc:
        print(f"Texture bind report failed: {exc}")




def model_texture_fragments(model):
    compact = re.sub(r"[^a-z0-9]+", "", str(model or "").lower())
    fragments = set()
    if len(compact) >= 4:
        fragments.add(compact)
    for run in re.findall(r"[a-z]{4,}", compact):
        fragments.add(run)
        for size in (4, 5, 6):
            if len(run) > size:
                fragments.add(run[:size])
    return fragments


def texture_name_matches_model(name, model):
    fragments = model_texture_fragments(model)
    return any(fragment in name for fragment in fragments)


def is_generic_auto_livery_name(name):
    return name.startswith(GENERIC_AUTO_LIVERY_PREFIXES)


def livery_candidate_score(path, model, local_texture_names):
    key = normalized_texture_name(path.name)
    name = path.stem.lower()
    if local_texture_names and key not in local_texture_names:
        return None
    if not is_livery_texture(path):
        return None

    matches_model = texture_name_matches_model(name, model)
    if is_generic_auto_livery_name(name) and not matches_model:
        return None
    if not matches_model:
        if not any(hint in name for hint in ("livery", "skin")):
            return None
        try:
            if path.stat().st_size < 32_000:
                return None
        except OSError:
            return None

    try:
        value = path.stat().st_size
    except OSError:
        value = 0
    if matches_model:
        value += 30_000_000
    if "sign" in name or "livery" in name:
        value += 10_000_000
    if name.endswith("_1") or "sign_1" in name:
        value += 5_000_000
    if "skin" in name or "decal" in name:
        value += 3_000_000
    return value


def find_livery_texture(texture_index, model, local_texture_names):
    candidates = {}
    for path in texture_index.values():
        if livery_candidate_score(path, model, local_texture_names) is not None:
            candidates[str(path.resolve()).lower()] = path
    if not candidates:
        return None

    def score(path):
        return livery_candidate_score(path, model, local_texture_names) or 0

    return max(candidates.values(), key=score)


def linked_node_has_real_image(node, visited=None):
    if node is None:
        return False
    if visited is None:
        visited = set()
    marker = id(node)
    if marker in visited:
        return False
    visited.add(marker)

    if node.bl_idname == "ShaderNodeTexImage":
        image = getattr(node, "image", None)
        return bool(image and not image_is_generated_fallback(image))

    for input_socket in getattr(node, "inputs", []):
        for link in getattr(input_socket, "links", []):
            if linked_node_has_real_image(link.from_node, visited):
                return True
    return False


def base_color_has_upstream_texture(node):
    socket = node.inputs.get("Base Color")
    if not socket or not socket.is_linked:
        return False
    for link in socket.links:
        if linked_node_has_real_image(link.from_node):
            return True
    return False


def base_color_has_texture(node):
    socket = node.inputs.get("Base Color")
    if not socket or not socket.is_linked:
        return False
    for link in socket.links:
        source = link.from_node
        if source and source.bl_idname == "ShaderNodeTexImage":
            image = getattr(source, "image", None)
            return bool(image and not image_is_generated_fallback(image))
    return False


def base_color_uses_palette_texture(node):
    socket = node.inputs.get("Base Color")
    if not socket or not socket.is_linked:
        return False
    found = False
    for link in socket.links:
        source = link.from_node
        if not source or source.bl_idname != "ShaderNodeTexImage":
            return False
        image = getattr(source, "image", None)
        if not image:
            continue
        found = True
        key = normalized_texture_name(image.name)
        if not any(hint in key for hint in ("dpal", "palette", "tint")):
            return False
    return found


def is_light_neutral_color(color):
    try:
        r, g, b = color[:3]
    except Exception:
        return False
    return min(r, g, b) > 0.82 and (max(r, g, b) - min(r, g, b)) < 0.12


def tone_untextured_paint(material_obj, bsdf):
    base = bsdf.inputs.get("Base Color")
    if not base or base.is_linked or not is_light_neutral_color(base.default_value):
        return False
    base.default_value = PAINT_COLOR
    material_obj.diffuse_color = PAINT_COLOR
    return True


def link_image_to_base_color(material_obj, bsdf, image, label):
    base = bsdf.inputs.get("Base Color")
    if not base:
        return False
    for link in list(base.links):
        material_obj.node_tree.links.remove(link)
    tex_node = material_obj.node_tree.nodes.new("ShaderNodeTexImage")
    tex_node.name = "vehicle_renderer_livery_texture"
    tex_node.label = label
    tex_node.image = image
    material_obj.node_tree.links.new(tex_node.outputs["Color"], base)
    return True


def protected_vehicle_model_tone_material(name):
    raw = str(name or "").lower()
    key = normalized_texture_name(name)
    if not key:
        return True

    semantic = material_semantic(name)
    if semantic in {"glass", "light", "rubber", "brake", "leather", "fabric"}:
        return True
    if semantic in {"chrome", "metal", "carbon", "plastic"}:
        return True

    protected = (
        "glass",
        "window",
        "windscreen",
        "windshield",
        "headlamp",
        "headlight",
        "rearlight",
        "taillight",
        "lamp",
        "emiss",
        "emission",
        "livery",
        "decal",
        "badge",
        "logo",
        "sign",
        "stripe",
        "sticker",
        "letter",
        "text",
        "interior",
        "seat",
        "sitz",
        "floor",
        "carpet",
        "screen",
        "display",
        "dial",
        "gauge",
        "tacho",
        "dash",
        "radio",
        "pedal",
        "cup",
        "matratze",
        "fabric",
        "cloth",
        "leather",
        "leder",
        "tire",
        "tyre",
        "rubber",
        "sidewall",
        "pzero",
        "tyrewall",
        "tirewall",
        "wheel",
        "alloy",
        "brake",
        "disc",
        "rotor",
        "caliper",
        "calliper",
        "plate",
        "license",
        "numberplate",
    )
    protected_tags = ("[wheel]", "[rim]", "[tire]", "[tyre]", "[brake]")
    rim_like = key == "rim" or key.startswith("rim_") or key.endswith("_rim") or "_rim_" in key
    return rim_like or any(hint in key for hint in protected) or any(tag in raw for tag in protected_tags)


def vehicle_model_tone_factor(name):
    raw = str(name or "").lower()
    key = normalized_texture_name(name)
    if ASSET_KIND != "vehicle" or MODEL_TONE not in MODEL_TONE_PALETTE:
        return 0.0
    if not key or "pearlescent" in raw or protected_vehicle_model_tone_material(name):
        return 0.0
    if "[primary]" in raw or "[secondary]" in raw:
        return 1.0
    if key.isdigit() or key == "matte":
        return 1.0
    if is_paint_like_material(name):
        return 1.0
    return 0.0


def vehicle_paint_tone_color():
    return MODEL_TONE_PALETTE.get(MODEL_TONE, MODEL_TONE_PALETTE["gray"])[0]


def vehicle_material_paint_layer(material_obj):
    if not material_obj or not material_obj.node_tree:
        return None
    diffuse = material_obj.node_tree.nodes.get("matDiffuseColor")
    if diffuse is None:
        return None
    try:
        if abs(float(diffuse.get("X")) - 2.0) < 0.0001:
            return int(round(float(diffuse.get("Y"))))
    except (TypeError, ValueError):
        pass
    return None


def vehicle_material_uses_paint_tone(material_obj):
    if ASSET_KIND != "vehicle" or not material_obj or not material_obj.node_tree:
        return False
    diffuse = material_obj.node_tree.nodes.get("matDiffuseColor")
    if diffuse is None:
        return False
    paint_layer = vehicle_material_paint_layer(material_obj)
    if paint_layer is not None:
        return paint_layer in VEHICLE_BODY_PAINT_LAYERS
    return vehicle_model_tone_factor(material_obj.name) > 0.0


def apply_vehicle_paint_tones():
    if ASSET_KIND != "vehicle" or MODEL_TONE not in MODEL_TONE_PALETTE:
        return 0
    color = vehicle_paint_tone_color()
    changed = []
    for material_obj in bpy.data.materials:
        if not vehicle_material_uses_paint_tone(material_obj):
            continue
        nodes = material_obj.node_tree.nodes
        diffuse = nodes.get("matDiffuseColor")
        paint_layer = vehicle_material_paint_layer(material_obj)
        updated = False
        if paint_layer in VEHICLE_BODY_PAINT_LAYERS:
            layer_node = nodes.get(f"PreviewBodyColor{paint_layer}")
            if layer_node is not None and len(layer_node.inputs) >= 3:
                for index, component in enumerate(color[:3]):
                    layer_node.inputs[index].default_value = component
                updated = True
        else:
            try:
                diffuse.set_vec3(color[:3])
                updated = True
            except Exception:
                pass
        if updated:
            changed.append(material_obj.name)
    if changed:
        print(f"Model paint tone adjusted: {len(changed)}")
        print("Model paint tone materials: " + ", ".join(changed[:36]))
    return len(changed)


def bake_sollumz_shader_parameters():
    baked_links = 0
    baked_materials = set()
    for material_obj in bpy.data.materials:
        if not material_obj.node_tree:
            continue
        links = material_obj.node_tree.links
        for node in material_obj.node_tree.nodes:
            if node.bl_idname != "SOLLUMZ_NT_SHADER_Parameter":
                continue
            for output in node.outputs:
                try:
                    value = float(node.get(output.name))
                except (KeyError, TypeError, ValueError):
                    continue
                for link in list(output.links):
                    target = link.to_socket
                    try:
                        target.default_value = value
                    except Exception:
                        continue
                    links.remove(link)
                    baked_links += 1
                    baked_materials.add(material_obj.name)
    if baked_links:
        print(f"Sollumz shader parameters baked: {baked_links} links in {len(baked_materials)} materials")
        print("Sollumz parameter materials: " + ", ".join(sorted(baked_materials)[:36]))
    return baked_links


def strip_texture_suffix(name):
    key = normalized_texture_name(name)
    suffixes = (
        "_materialopacity",
        "_material",
        "_diffuse",
        "_diff",
        "_color",
        "_col",
        "_opacity",
        "_d",
    )
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if key.endswith(suffix) and len(key) > len(suffix) + 1:
                key = key[: -len(suffix)]
                changed = True
                break
    return key


def is_non_color_texture_name(name):
    key = normalized_texture_name(name)
    if any(hint in key for hint in NON_COLOR_HINTS):
        return True
    return key.endswith(("_s", "_n", "_nm", "_nrm"))


def material_texture_match_score(material_name, path, local_texture_names):
    mat_key = normalized_texture_name(material_name)
    tex_key = normalized_texture_name(path.name)
    if not mat_key or not tex_key or is_non_color_texture_name(tex_key):
        return None

    exact = mat_key == tex_key
    generic_material_names = {
        "material",
        "default",
        "black",
        "white",
        "paint",
        "primary",
        "secondary",
        "vehicle",
        "body",
    }
    if mat_key in {"black", "white", "blank", "default", "material"}:
        return None
    if mat_key in generic_material_names and not exact:
        return None

    mat_base = strip_texture_suffix(mat_key)
    tex_base = strip_texture_suffix(tex_key)
    base_match = bool(mat_base and tex_base and mat_base == tex_base)

    if not exact and not base_match:
        if tex_key.startswith(mat_key + "_") or mat_key.startswith(tex_key + "_"):
            base_match = True
        elif len(mat_key) >= 4 and len(tex_key) >= 4 and (mat_key in tex_key or tex_key in mat_key):
            base_match = True

    if not exact and not base_match:
        return None

    # Do not use generic shared liveries as a part-material fallback unless the
    # material itself asks for that exact texture name.
    if is_livery_texture(path) and not exact and not any(hint in mat_key for hint in LIVERY_HINTS):
        return None
    if any(hint in tex_key for hint in COLOR_TEXTURE_EXCLUDE_HINTS) and not exact:
        return None

    try:
        value = path.stat().st_size
    except OSError:
        value = 0
    if tex_key in local_texture_names:
        value += 20_000_000
    if exact:
        value += 15_000_000
    if base_match:
        value += 8_000_000
    if tex_key.endswith("_d") or "_diff" in tex_key or "_color" in tex_key:
        value += 4_000_000
    if "materialopacity" in tex_key or "material" in tex_key:
        value += 2_000_000
    return value


def find_material_color_texture(material_name, texture_index, local_texture_names):
    candidates = []
    for path in texture_index.values():
        score = material_texture_match_score(material_name, path, local_texture_names)
        if score is not None:
            candidates.append((score, path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]

def texture_pixel_size(path):
    try:
        image = bpy.data.images.load(str(path), check_existing=True)
        width, height = image.size
        return int(width) * int(height)
    except Exception:
        return 0


def generic_asset_texture_score(path, local_texture_names):
    key = normalized_texture_name(path.name)
    if local_texture_names and key not in local_texture_names:
        return None
    if is_non_color_texture_name(key):
        return None
    if any(hint in key for hint in ("normal", "spec", "rough", "gloss", "ao", "height", "metallic", "bump", "mask")):
        return None
    if any(hint in key for hint in ("decal", "plate", "font", "dirt", "mud", "burnt", "dpal", "tint", "palette")):
        return None
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size < 1024:
        return None
    score = size
    if any(hint in key for hint in ("basecolor", "diffuse", "albedo", "color")) or key.endswith(("_d", "_diff")):
        score += 10_000_000
    if key in {"map", "diffuse", "albedo", "basecolor", "base_color"}:
        score += 14_000_000
        if any(f"{key}{suffix}" in local_texture_names for suffix in ("_n", "_nm", "_nrm", "_normal")):
            score += 3_000_000
        if any(f"{key}{suffix}" in local_texture_names for suffix in ("_s", "_spec", "_specular")):
            score += 3_000_000
    if key.startswith(("w_", "weapon_")):
        score += 5_000_000
    if key.endswith("_d") or key.endswith("_diff"):
        score += 3_000_000
    if texture_pixel_size(path) < 64:
        return None
    return score


def find_generic_asset_texture(texture_index, local_texture_names):
    candidates = []
    for path in texture_index.values():
        score = generic_asset_texture_score(path, local_texture_names)
        if score is not None:
            candidates.append((score, path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def bind_generic_asset_texture(texture_index, texture_manifest, job):
    if job.get("asset_kind", "vehicle") == "vehicle":
        return 0
    local_texture_names = texture_manifest.get("local", set())
    if not local_texture_names:
        print(f"Texture bind local missing: {job.get('model', '')} has no local YTD textures")
        return 0
    texture_path = find_generic_asset_texture(texture_index, local_texture_names)
    if texture_path is None:
        return 0
    image = bpy.data.images.load(str(texture_path), check_existing=True)
    set_image_color_space(image, False)
    linked = 0
    names = []
    for material_obj in bpy.data.materials:
        if not material_obj.use_nodes or not material_obj.node_tree:
            continue
        if material_semantic(material_obj.name) in {"glass", "light"}:
            continue
        for node in material_obj.node_tree.nodes:
            if node.bl_idname != "ShaderNodeBsdfPrincipled":
                continue
            if base_color_has_upstream_texture(node) and not base_color_uses_palette_texture(node):
                continue
            if link_image_to_base_color(material_obj, node, image, texture_path.stem):
                linked += 1
                names.append(material_obj.name)
    if linked:
        print(f"Generic asset texture linked: {texture_path.stem} -> {linked}")
        print("Generic asset materials: " + ", ".join(names[:24]))
    return linked


def wheel_object_material_names():
    names = set()
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.name.lower().startswith("wheel_"):
            continue
        for slot in obj.material_slots:
            if slot.material:
                names.add(slot.material.name)
                names.add(normalized_texture_name(slot.material.name))
    return names


def bind_untextured_materials(texture_index, texture_manifest):
    local_texture_names = texture_manifest.get("local", set())
    wheel_materials = wheel_object_material_names()
    linked = 0
    names = []
    for material_obj in bpy.data.materials:
        if not material_obj.use_nodes or not material_obj.node_tree:
            continue
        if material_obj.name in wheel_materials or normalized_texture_name(material_obj.name) in wheel_materials:
            continue
        texture_path = find_material_color_texture(material_obj.name, texture_index, local_texture_names)
        if texture_path is None:
            continue
        image = None
        for node in material_obj.node_tree.nodes:
            if node.bl_idname != "ShaderNodeBsdfPrincipled":
                continue
            if base_color_has_upstream_texture(node):
                continue
            if image is None:
                image = bpy.data.images.load(str(texture_path), check_existing=True)
                set_image_color_space(image, False)
            if link_image_to_base_color(material_obj, node, image, texture_path.stem):
                linked += 1
                names.append(f"{material_obj.name}->{texture_path.stem}")
    if linked:
        print(f"Part texture linked: {linked}")
        print("Part texture materials: " + ", ".join(names[:36]))
    return linked


def bind_auto_livery_materials(texture_index, job, texture_manifest):
    livery_path = find_livery_texture(
        texture_index,
        job.get("model", ""),
        texture_manifest.get("local", set()),
    )
    if not livery_path:
        return 0
    livery_image = bpy.data.images.load(str(livery_path), check_existing=True)
    set_image_color_space(livery_image, False)

    linked = 0
    names = []
    for material_obj in bpy.data.materials:
        if not material_obj.use_nodes or not material_obj.node_tree:
            continue
        if vehicle_model_tone_factor(material_obj.name) <= 0.0 and not is_paint_like_material(material_obj.name):
            continue
        for node in material_obj.node_tree.nodes:
            if node.bl_idname != "ShaderNodeBsdfPrincipled":
                continue
            if base_color_has_texture(node):
                continue
            if link_image_to_base_color(material_obj, node, livery_image, livery_path.stem):
                linked += 1
                names.append(material_obj.name)
    if linked:
        print(f"Auto livery texture: {livery_path.stem}")
        print("Auto livery materials: " + ", ".join(names[:20]))
    return linked


def dump_wheel_materials():
    rows = []
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.name.lower().startswith("wheel_"):
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if not mat:
                continue
            images = []
            if mat.use_nodes and mat.node_tree:
                for node in mat.node_tree.nodes:
                    if node.bl_idname == "ShaderNodeTexImage":
                        image = getattr(node, "image", None)
                        images.append(image.name if image else node.name)
            rows.append(f"{obj.name}:{mat.name}[{','.join(images) or '-'}]")
    if rows:
        print("Wheel materials: " + " | ".join(rows[:32]))


def is_wheel_color_texture(path):
    name = path.stem.lower()
    return any(hint in name for hint in WHEEL_COLOR_HINTS) and not any(
        hint in name for hint in WHEEL_COLOR_EXCLUDE_HINTS
    )


def wheel_texture_score(path, local_texture_names):
    key = normalized_texture_name(path.name)
    name = path.stem.lower()
    if not is_wheel_color_texture(path):
        return None

    local = key in local_texture_names if local_texture_names else True
    if local_texture_names and not local and not name.startswith("vehicle_generic_alloy"):
        return None

    try:
        value = path.stat().st_size
    except OSError:
        value = 0
    if local:
        value += 20_000_000
    if re.search(r"(^|[_-])d($|[_-])", name) or name.endswith("_d"):
        value += 8_000_000
    if "rim" in name or "alloy" in name:
        value += 4_000_000
    if "material" in name:
        value += 1_000_000
    return value


def find_wheel_color_texture(texture_index, local_texture_names):
    candidates = []
    for path in texture_index.values():
        score = wheel_texture_score(path, local_texture_names)
        if score is not None:
            candidates.append((score, path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def is_tire_like_material_name(name):
    return any(
        hint in name
        for hint in ("tire", "tyre", "rubber", "sidewall", "tyrewall", "tirewall", "pzero", "pz_")
    )


def is_brake_like_material_name(name):
    return any(hint in name for hint in ("brake", "disc", "rotor", "caliper", "calliper"))


def is_light_like_material_name(name):
    key = normalized_texture_name(name)
    tokens = [token for token in re.split(r"[^a-z0-9]+", key.replace("_", " ")) if token]
    joined = "_".join(tokens)
    if any(hint in key for hint in ("emiss", "emission", "emit", "headlamp", "headlight", "rearlight", "taillight", "lightbar", "light_bar", "siren", "beacon", "strobe", "neon")):
        return True
    if any(token in {"indicator", "signal", "turn"} for token in tokens):
        return True
    if "brake_l" in key:
        return True
    if any(token in {"tail", "led"} for token in tokens):
        return True
    if any(token in {"light", "lights", "lamp", "lamps"} for token in tokens):
        return not any(color in tokens for color in ("gray", "grey", "black", "white"))
    return False


def material_semantic(name):
    key = normalized_texture_name(name)
    if "glass" in key or "window" in key or "windscreen" in key:
        return "glass"
    if is_light_like_material_name(key):
        return "light"
    if is_tire_like_material_name(key):
        return "rubber"
    if is_brake_like_material_name(key):
        return "brake"
    if any(hint in key for hint in ("alloy", "rim", "wheel")):
        return "metal"
    if any(
        hint in key
        for hint in (
            "primary",
            "secondary",
            "paint",
            "vehpaint",
            "vehicle_generic_smallspecmap",
            "body",
            "bodyshell",
            "coloured",
            "color",
        )
    ):
        return "paint"
    if "chrome" in key:
        return "chrome"
    if any(hint in key for hint in ("metal", "steel", "aluminium", "aluminum", "bolt", "screw", "pipe", "exhaust")):
        return "metal"
    if "carbon" in key:
        return "carbon"
    if any(hint in key for hint in ("plastic", "black", "trim", "grille", "grill", "splitter", "diffuser")):
        return "plastic"
    if any(hint in key for hint in ("leather", "seat", "interior")):
        return "leather"
    if any(hint in key for hint in ("fabric", "cloth", "carpet", "rug")):
        return "fabric"
    return ""


def semantic_color(name, semantic):
    key = normalized_texture_name(name)
    if semantic == "rubber":
        return (0.012, 0.012, 0.011, 1.0)
    if semantic == "brake":
        return (0.20, 0.19, 0.17, 1.0)
    if semantic == "chrome":
        return (0.82, 0.82, 0.78, 1.0)
    if semantic == "metal":
        return (0.28, 0.28, 0.27, 1.0)
    if semantic == "carbon":
        return (0.025, 0.026, 0.025, 1.0)
    if semantic == "plastic":
        return (0.025, 0.025, 0.024, 1.0)
    if semantic == "leather":
        return (0.045, 0.043, 0.04, 1.0)
    if semantic == "fabric":
        return (0.07, 0.066, 0.06, 1.0)
    if semantic == "light":
        if any(hint in key for hint in ("tail", "brake", "rear", "red")):
            return (1.0, 0.05, 0.02, 1.0)
        if any(hint in key for hint in ("indicator", "signal", "turn", "amber", "orange")):
            return (1.0, 0.42, 0.03, 1.0)
        return (0.92, 0.96, 1.0, 1.0)
    return None


def is_catalog_paint_slot(name):
    key = normalized_texture_name(name)
    lower = name.lower()
    return (
        "primary" in lower
        or "secondary" in lower
        or "vehicle_generic_smallspecmap" in key
        or key in {"paint", "body", "bodyshell", "vehicle_body", "vehpaint"}
    )


def light_effect_color(name):
    key = normalized_texture_name(name)
    if any(hint in key for hint in ("blue", "siren", "police", "lightbar", "light_bar")):
        return (0.12, 0.34, 1.0, 1.0)
    if any(hint in key for hint in ("tail", "brake", "rear", "red")):
        return (1.0, 0.03, 0.015, 1.0)
    if any(hint in key for hint in ("indicator", "signal", "turn", "amber", "orange", "yellow")):
        return (1.0, 0.45, 0.04, 1.0)
    if any(hint in key for hint in ("green", "neon")):
        return (0.08, 1.0, 0.18, 1.0)
    return (0.9, 0.96, 1.0, 1.0)


def is_police_light_name(name):
    key = normalized_texture_name(name)
    return any(hint in key for hint in ("siren", "police", "lightbar", "light_bar", "beacon", "strobe"))


def is_self_emissive_name(name):
    key = normalized_texture_name(name)
    return (
        any(hint in key for hint in ("emiss", "emission", "emit", "neon"))
        or key.endswith("_e")
    )


def should_emit_material(name):
    key = normalized_texture_name(name)
    if is_police_light_name(key) or is_self_emissive_name(key):
        return True
    return any(
        hint in key
        for hint in ("headlamp", "headlight", "tail", "brake_l", "indicator", "signal", "turn", "rearlight")
    )


def link_base_color_to_emission(material_obj, node):
    base = node.inputs.get("Base Color")
    target = node.inputs.get("Emission Color") or node.inputs.get("Emission")
    if not base or not target or not base.is_linked or target.is_linked:
        return False
    for link in base.links:
        if linked_node_has_real_image(link.from_node):
            material_obj.node_tree.links.new(link.from_socket, target)
            return True
    return False


def set_emission_inputs(material_obj, node, color, strength):
    if not link_base_color_to_emission(material_obj, node):
        set_first_input(node, ("Emission Color", "Emission"), color)
    set_input(node, "Emission Strength", strength)


def current_material_color(material_obj, node):
    socket = node.inputs.get("Base Color") if node else None
    if socket is not None:
        try:
            value = tuple(socket.default_value)
            if len(value) >= 4:
                return value[:4]
        except Exception:
            pass
    try:
        value = tuple(material_obj.diffuse_color)
        if len(value) >= 4:
            return value[:4]
    except Exception:
        pass
    return (1.0, 1.0, 1.0, 1.0)


def apply_untextured_model_tone(material_obj, node):
    if ASSET_KIND != "vehicle" or MODEL_TONE not in MODEL_TONE_PALETTE:
        return False
    if vehicle_model_tone_factor(material_obj.name) <= 0.0:
        return False
    if vehicle_material_uses_paint_tone(material_obj):
        return True
    if base_color_has_upstream_texture(node):
        return False
    color = vehicle_paint_tone_color()
    force_input(node, "Base Color", color)
    material_obj.diffuse_color = color
    return True


def tune_semantic_materials(enable_emission=True):
    changed = 0
    for material_obj in bpy.data.materials:
        semantic = material_semantic(material_obj.name)
        if not semantic or semantic == "glass":
            continue
        material_obj.use_nodes = True
        color = semantic_color(material_obj.name, semantic)
        for node in material_obj.node_tree.nodes:
            if node.bl_idname != "ShaderNodeBsdfPrincipled":
                continue
            model_toned = apply_untextured_model_tone(material_obj, node)
            if not model_toned and semantic != "light" and color and not base_color_has_upstream_texture(node):
                force_input(node, "Base Color", color)
                material_obj.diffuse_color = color
            if semantic == "rubber":
                set_input(node, "Roughness", 0.78)
                set_input(node, "Metallic", 0.0)
                set_first_input(node, ("Specular IOR Level", "Specular"), 0.32)
            elif semantic == "brake":
                set_input(node, "Roughness", 0.48)
                set_input(node, "Metallic", 0.35)
                set_first_input(node, ("Specular IOR Level", "Specular"), 0.55)
            elif semantic == "chrome":
                if not model_toned and material_uses_generic_tiny_texture(material_obj, ("chrome", "vehicle_generic_smallspecmap")):
                    chrome_fallback = CHROME_FALLBACK_COLOR
                    force_input(node, "Base Color", chrome_fallback)
                    material_obj.diffuse_color = chrome_fallback
                    force_input(node, "Roughness", 0.50)
                    force_input(node, "Metallic", 0.04)
                    force_input(node, "Specular IOR Level", 0.34)
                    force_input(node, "Specular", 0.34)
                    force_input(node, "Coat Weight", 0.06)
                    force_input(node, "Coat Roughness", 0.26)
                else:
                    set_input(node, "Roughness", 0.08)
                    set_input(node, "Metallic", 0.85)
                    set_first_input(node, ("Specular IOR Level", "Specular"), 0.82)
                    set_input(node, "Coat Weight", 0.35)
            elif semantic == "paint":
                if not model_toned and is_catalog_paint_slot(material_obj.name) and not material_has_renderer_color_texture(material_obj):
                    force_input(node, "Base Color", PAINT_COLOR)
                    material_obj.diffuse_color = PAINT_COLOR
                    force_input(node, "Roughness", 0.42)
                    force_input(node, "Specular IOR Level", 0.42)
                    force_input(node, "Specular", 0.42)
                    force_input(node, "Coat Weight", 0.22)
                    force_input(node, "Coat Roughness", 0.20)
                else:
                    set_input(node, "Roughness", 0.28)
                    set_first_input(node, ("Specular IOR Level", "Specular"), 0.64)
                    set_input(node, "Coat Weight", 0.42)
                    set_input(node, "Coat Roughness", 0.14)
                set_input(node, "Metallic", 0.0)
            elif semantic == "metal":
                set_input(node, "Roughness", 0.28)
                set_input(node, "Metallic", 0.72)
                set_first_input(node, ("Specular IOR Level", "Specular"), 0.72)
                set_input(node, "Coat Weight", 0.25)
            elif semantic == "carbon":
                set_input(node, "Roughness", 0.24)
                set_input(node, "Metallic", 0.0)
                set_first_input(node, ("Specular IOR Level", "Specular"), 0.75)
                set_input(node, "Coat Weight", 0.65)
                set_input(node, "Coat Roughness", 0.08)
            elif semantic in ("plastic", "leather", "fabric"):
                set_input(node, "Roughness", 0.52 if semantic == "plastic" else 0.72)
                set_input(node, "Metallic", 0.0)
                set_first_input(node, ("Specular IOR Level", "Specular"), 0.42)
            elif semantic == "light":
                light_color = current_material_color(material_obj, node)
                if enable_emission and should_emit_material(material_obj.name):
                    strength = 2.4 if is_police_light_name(material_obj.name) else 1.15
                    set_emission_inputs(material_obj, node, light_color, strength)
                set_input(node, "Roughness", 0.12)
                set_input(node, "Metallic", 0.0)
                set_first_input(node, ("Specular IOR Level", "Specular"), 0.72)
            changed += 1
    return changed


def should_link_wheel_texture(mat_name, wheel_texture_name):
    key = normalized_texture_name(mat_name)
    wheel_key = normalized_texture_name(wheel_texture_name)
    if key in {"black", "blank", "rubber"}:
        return False
    if is_tire_like_material_name(key) or is_brake_like_material_name(key):
        return False
    if key == wheel_key:
        return True
    if any(hint in key for hint in ("wheel", "rim", "alloy")):
        return True
    return False


def tune_window_materials():
    changed = 0
    for material_obj in bpy.data.materials:
        name = material_obj.name.lower()
        if not any(hint in name for hint in ("glass", "glasswindows", "windscreen", "window")):
            continue
        material_obj.use_nodes = True
        material_obj.diffuse_color = (0.16, 0.20, 0.22, 0.18)
        try:
            material_obj.blend_method = "BLEND"
            material_obj.use_screen_refraction = True
            material_obj.show_transparent_back = True
            material_obj.alpha_threshold = 0.01
        except Exception:
            pass
        try:
            material_obj.surface_render_method = "BLENDED"
        except Exception:
            pass
        for node in material_obj.node_tree.nodes:
            if node.bl_idname != "ShaderNodeBsdfPrincipled":
                continue
            if not base_color_has_upstream_texture(node) or material_has_fallback_texture(material_obj):
                set_input(node, "Base Color", (0.16, 0.20, 0.22, 0.18))
            force_input(node, "Alpha", 0.18)
            set_input(node, "Roughness", 0.035)
            set_input(node, "Metallic", 0.0)
            set_first_input(node, ("Specular IOR Level", "Specular"), 0.86)
            set_input(node, "Coat Weight", 0.55)
            set_input(node, "Coat Roughness", 0.07)
            set_input(node, "Transmission Weight", 0.24)
            changed += 1
    return changed


def is_paint_like_material(name):
    lower = name.lower()
    excluded = (
        "glass",
        "window",
        "windscreen",
        "tyre",
        "tire",
        "rubber",
        "wheel",
        "brake",
        "disc",
        "rotor",
        "interior",
        "seat",
        "fabric",
        "cloth",
        "leather",
        "dirt",
        "mud",
        "light",
        "emiss",
        "plate",
    )
    if any(hint in lower for hint in excluded):
        return False
    included = (
        "paint",
        "body",
        "veh",
        "vehicle",
        "car",
        "coloured",
        "color",
        "primary",
        "secondary",
        "metal",
        "chrome",
        "carbon",
        "bumper",
        "door",
        "hood",
        "bonnet",
        "roof",
        "fender",
        "spoiler",
    )
    return any(hint in lower for hint in included)


def tune_paint_materials(texture_index, job, texture_manifest):
    changed = 0
    toned = 0
    livery_path = find_livery_texture(
        texture_index,
        job.get("model", ""),
        texture_manifest.get("local", set()),
    )
    livery_image = None
    if livery_path:
        livery_image = bpy.data.images.load(str(livery_path), check_existing=True)
        set_image_color_space(livery_image, False)
        print(f"Auto livery texture: {livery_path.stem}")
    for material_obj in bpy.data.materials:
        if not material_obj.use_nodes or not material_obj.node_tree:
            continue
        if not is_paint_like_material(material_obj.name):
            continue
        for node in material_obj.node_tree.nodes:
            if node.bl_idname != "ShaderNodeBsdfPrincipled":
                continue
            if livery_image and not base_color_has_texture(node):
                link_image_to_base_color(material_obj, node, livery_image, livery_path.stem)
            elif tone_untextured_paint(material_obj, node):
                toned += 1
            set_input(node, "Roughness", 0.18)
            set_first_input(node, ("Specular IOR Level", "Specular"), 0.82)
            set_input(node, "Coat Weight", 0.82)
            set_input(node, "Coat Roughness", 0.055)
            set_input(node, "Metallic", 0.0)
            changed += 1
    if toned:
        print(f"Paint tone adjusted: {toned}")
    return changed


def tune_wheel_materials(texture_index, texture_manifest):
    changed = 0
    linked = 0
    linked_names = []
    wheel_path = find_wheel_color_texture(texture_index, texture_manifest.get("local", set()))
    wheel_image = None
    if wheel_path:
        wheel_image = bpy.data.images.load(str(wheel_path), check_existing=True)
        set_image_color_space(wheel_image, False)
        print(f"Auto wheel texture: {wheel_path.stem}")
    for obj in bpy.data.objects:
        lower_obj = obj.name.lower()
        if obj.type != "MESH" or not lower_obj.startswith("wheel_"):
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if not mat:
                continue
            mat_name = mat.name.lower()
            mat.use_nodes = True
            for node in mat.node_tree.nodes:
                if node.bl_idname != "ShaderNodeBsdfPrincipled":
                    continue
                if is_tire_like_material_name(mat_name):
                    set_input(node, "Roughness", 0.62)
                    set_input(node, "Metallic", 0.0)
                elif is_brake_like_material_name(mat_name):
                    set_input(node, "Roughness", 0.46)
                    set_input(node, "Metallic", 0.28)
                else:
                    if (
                        wheel_image
                        and should_link_wheel_texture(mat_name, wheel_path.stem)
                        and not base_color_has_texture(node)
                    ):
                        if link_image_to_base_color(mat, node, wheel_image, wheel_path.stem):
                            linked += 1
                            linked_names.append(mat.name)
                    set_input(node, "Roughness", 0.28)
                    set_input(node, "Metallic", 0.45)
                    set_first_input(node, ("Specular IOR Level", "Specular"), 0.7)
                    set_input(node, "Coat Weight", 0.35)
                    set_input(node, "Coat Roughness", 0.12)
                changed += 1
    if linked:
        print(f"Wheel texture linked: {linked}")
        print("Wheel texture materials: " + ", ".join(sorted(set(linked_names))[:20]))
    return changed


def duplicate_mesh_at_target(source, target, name, mirror_local_x=False):
    bpy.context.view_layer.update()
    clone = source.copy()
    clone.data = source.data.copy()
    if mirror_local_x:
        clone.data.transform(Matrix.Scale(-1.0, 4, Vector((1.0, 0.0, 0.0))))
        clone.data.flip_normals()
        clone.data.update()
    clone.animation_data_clear()
    for constraint in list(clone.constraints):
        clone.constraints.remove(constraint)
    clone.name = name
    clone.data.name = f"{name}.mesh"
    clone.hide_viewport = False
    clone.hide_render = False
    bpy.context.collection.objects.link(clone)
    clone.matrix_world = target.matrix_world.copy()
    return clone


def mirror_missing_wheels():
    created = 0
    objects = bpy.data.objects
    pairs = []
    for obj in list(objects):
        lower = obj.name.lower()
        if obj.type != "MESH" or not lower.startswith("wheel_l") or ".child" not in lower:
            continue
        target_name = "wheel_r" + obj.name[7:]
        target_col = target_name.replace(".child", ".col")
        pairs.append((obj.name, target_name, target_col))

    for obj in list(objects):
        lower = obj.name.lower()
        if obj.type != "MESH" or not lower.startswith("wheel_r") or ".child" not in lower:
            continue
        target_name = "wheel_l" + obj.name[7:]
        target_col = target_name.replace(".child", ".col")
        pairs.append((obj.name, target_name, target_col))

    for source_name, target_name, target_col_name in pairs:
        if objects.get(target_name):
            continue
        source = objects.get(source_name)
        target = objects.get(target_col_name)
        if not source or not target:
            continue
        mirror_local_x = source_name[:7].lower() != target_name[:7].lower()
        clone = duplicate_mesh_at_target(source, target, target_name, mirror_local_x)
        suffix = " mirrored-x" if mirror_local_x else ""
        print(f"Wheel mirror: {source_name} -> {clone.name}{suffix}")
        created += 1
    return created


def bind_extracted_textures(job):
    texture_index = build_texture_index(job.get("texture_dir"))
    texture_manifest = load_texture_manifest(job)
    if not texture_index:
        print("Texture bind: no extracted textures")
        write_texture_bind_report(job, texture_index, texture_manifest, 0, set(), 0, 0, 0, 0, 0)
        return 0, 0

    matched = 0
    missing = set()
    for material_obj in bpy.data.materials:
        if not material_obj.use_nodes or not material_obj.node_tree:
            continue
        for node in material_obj.node_tree.nodes:
            if node.bl_idname != "ShaderNodeTexImage":
                continue

            candidates = node_texture_candidates(node, material_obj)
            texture_path = next((texture_index[name] for name in candidates if name in texture_index), None)
            if texture_path is None:
                if candidates:
                    missing.add(candidates[0])
                continue

            image = bpy.data.images.load(str(texture_path), check_existing=True)
            set_image_color_space(image, is_non_color_node(node, texture_path))
            node.image = image
            try:
                node.sollumz_texture_name = texture_path.stem
            except Exception:
                pass
            matched += 1

    if missing:
        preview = ", ".join(sorted(missing)[:24])
        suffix = "..." if len(missing) > 24 else ""
        print(f"Texture bind missing {len(missing)}: {preview}{suffix}")
    livery_links = bind_auto_livery_materials(texture_index, job, texture_manifest)
    generic_links = bind_generic_asset_texture(texture_index, texture_manifest, job)
    part_links = bind_untextured_materials(texture_index, texture_manifest)
    window_tunes = tune_window_materials()
    paint_tones = apply_vehicle_paint_tones()
    surface_tunes = tune_semantic_materials(bool(job.get("special_lights", True)))
    dump_wheel_materials()
    print(
        f"Texture bind matched: {matched}, missing: {len(missing)}, "
        f"livery_links: {livery_links}, generic_links: {generic_links}, part_links: {part_links}, "
        f"window_tunes: {window_tunes}, surface_tunes: {surface_tunes}, "
        f"paint_tones: {paint_tones}. "
        "Material parameters preserved."
    )
    write_texture_bind_report(
        job,
        texture_index,
        texture_manifest,
        matched,
        missing,
        livery_links,
        generic_links,
        part_links,
        window_tunes,
        surface_tunes,
    )
    return matched, len(missing)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def mesh_objects():
    objs = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        name = obj.name.lower()
        if name.startswith("bound ") or "collision" in name or ".bound" in name or name.endswith(".col") or ".col." in name:
            obj.hide_render = True
            obj.hide_viewport = True
            continue
        if obj.visible_get():
            objs.append(obj)
    return objs


def world_bounds(objects):
    min_v = Vector((float("inf"), float("inf"), float("inf")))
    max_v = Vector((float("-inf"), float("-inf"), float("-inf")))
    for obj in objects:
        for corner in obj.bound_box:
            v = obj.matrix_world @ Vector(corner)
            min_v.x = min(min_v.x, v.x)
            min_v.y = min(min_v.y, v.y)
            min_v.z = min(min_v.z, v.z)
            max_v.x = max(max_v.x, v.x)
            max_v.y = max(max_v.y, v.y)
            max_v.z = max(max_v.z, v.z)
    return min_v, max_v


def material(name, color, roughness=0.55):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        try:
            bsdf.inputs["Base Color"].default_value = color
            bsdf.inputs["Roughness"].default_value = roughness
            set_first_input(bsdf, ("Specular IOR Level", "Specular"), 0.45)
        except Exception:
            pass
    return mat


def set_camera_visible(obj, visible):
    for attr in ("visible_camera",):
        if hasattr(obj, attr):
            try:
                setattr(obj, attr, visible)
            except Exception:
                pass
    cycles_visibility = getattr(obj, "cycles_visibility", None)
    if cycles_visibility and hasattr(cycles_visibility, "camera"):
        try:
            cycles_visibility.camera = visible
        except Exception:
            pass


def set_shadow_catcher(obj):
    for attr in ("is_shadow_catcher",):
        if hasattr(obj, attr):
            try:
                setattr(obj, attr, True)
                return True
            except Exception:
                pass
    cycles = getattr(obj, "cycles", None)
    if cycles and hasattr(cycles, "is_shadow_catcher"):
        try:
            cycles.is_shadow_catcher = True
            return True
        except Exception:
            pass
    return False


def add_studio_wall(center, view_dir, max_dim, camera_visible=True):
    flat_dir = Vector((view_dir.x, view_dir.y, 0.0))
    if flat_dir.length < 0.001:
        return
    flat_dir.normalize()
    tangent = Vector((-flat_dir.y, flat_dir.x, 0.0))
    up = Vector((0.0, 0.0, 1.0))
    width = max_dim * 5.2
    height = max_dim * 2.8
    wall_center = Vector((center.x, center.y, center.z)) + flat_dir * max_dim * 1.7 + up * max_dim * 0.72
    verts = [
        wall_center - tangent * width * 0.5 - up * height * 0.5,
        wall_center + tangent * width * 0.5 - up * height * 0.5,
        wall_center + tangent * width * 0.5 + up * height * 0.5,
        wall_center - tangent * width * 0.5 + up * height * 0.5,
    ]
    mesh = bpy.data.meshes.new("catalog_backdrop_wall_mesh")
    mesh.from_pydata([tuple(v) for v in verts], [], [(0, 1, 2, 3)])
    mesh.update()
    wall = bpy.data.objects.new("catalog_backdrop_wall", mesh)
    bpy.context.collection.objects.link(wall)
    wall.data.materials.append(material("catalog_backdrop_wall", (0.31, 0.31, 0.31, 1.0), 0.82))
    if not camera_visible:
        set_camera_visible(wall, False)
    return wall


def add_studio_floor(min_z, max_dim, cutout_mode):
    floor_mat = material("catalog_floor", (0.88, 0.88, 0.86, 1.0), 0.46)
    floor_size = max_dim * 4.4
    bpy.ops.mesh.primitive_plane_add(size=floor_size, location=(0, 0, min_z))
    floor = bpy.context.object
    floor.name = "catalog_floor"
    floor.data.materials.append(floor_mat)
    if cutout_mode:
        if not set_shadow_catcher(floor):
            set_camera_visible(floor, False)
    return floor


def set_world_background(color, strength=1.0):
    scene = bpy.context.scene
    if scene.world is None:
        scene.world = bpy.data.worlds.new("vehicle_renderer_world")
    scene.world.color = color[:3]
    scene.world.use_nodes = True
    nodes = scene.world.node_tree.nodes
    background = nodes.get("Background")
    if background:
        color_socket = background.inputs.get("Color")
        strength_socket = background.inputs.get("Strength")
        if color_socket:
            color_socket.default_value = color
        if strength_socket:
            strength_socket.default_value = strength


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def projected_bounds(objects, camera):
    inv_camera = camera.matrix_world.inverted()
    min_x = float("inf")
    max_x = float("-inf")
    min_y = float("inf")
    max_y = float("-inf")
    for obj in objects:
        for corner in obj.bound_box:
            v = inv_camera @ (obj.matrix_world @ Vector(corner))
            min_x = min(min_x, v.x)
            max_x = max(max_x, v.x)
            min_y = min(min_y, v.y)
            max_y = max(max_y, v.y)
    return min_x, max_x, min_y, max_y


def center_camera_on_projection(objects, camera):
    min_x, max_x, min_y, max_y = projected_bounds(objects, camera)
    center_x = (min_x + max_x) * 0.5
    center_y = (min_y + max_y) * 0.5
    camera.location += camera.matrix_world.to_quaternion() @ Vector((center_x, center_y, 0.0))
    bpy.context.view_layer.update()


def projected_ortho_scale(objects, camera, aspect, margin=1.28, minimum=MIN_PROJECTED_ORTHO_SCALE):
    min_x, max_x, min_y, max_y = projected_bounds(objects, camera)
    width = max_x - min_x
    height = max_y - min_y
    return max(height, width / max(aspect, 0.01), minimum) * margin


def setup_scene(job, objects):
    cutout_mode = bool(job.get("green_screen", False))
    min_v, max_v = world_bounds(objects)
    center = (min_v + max_v) * 0.5
    dims = max_v - min_v
    max_dim = max(dims.x, dims.y, dims.z, 1.0)

    # Move the model center close to origin for stable camera math.
    offset = Vector((0, 0, 0)) - center
    for obj in objects:
        obj.location += offset
    bpy.context.view_layer.update()
    min_v, max_v = world_bounds(objects)
    center = (min_v + max_v) * 0.5
    dims = max_v - min_v
    max_dim = max(dims.x, dims.y, dims.z, 1.0)

    floor_clearance = max(float(job.get("floor_clearance", 0.12)), 0.0)
    if not cutout_mode:
        add_studio_floor(min_v.z - floor_clearance, max_dim, cutout_mode)

    yaw = math.radians(float(job.get("yaw", -42.0)))
    elevation = math.radians(float(job.get("elevation", 26.0)))
    distance = max_dim * 2.8
    cam_loc = Vector(
        (
            math.sin(yaw) * math.cos(elevation) * distance,
            -math.cos(yaw) * math.cos(elevation) * distance,
            math.sin(elevation) * distance + dims.z * 0.38,
        )
    )
    target = Vector((0, 0, center.z + dims.z * 0.03))
    view_dir = (target - cam_loc).normalized()
    add_studio_wall(target, view_dir, max_dim, camera_visible=not cutout_mode)

    bpy.ops.object.camera_add(location=cam_loc)
    camera = bpy.context.object
    look_at(camera, target)
    bpy.context.view_layer.update()
    center_camera_on_projection(objects, camera)
    bpy.context.scene.camera = camera
    if bool(job.get("orthographic", True)):
        camera.data.type = "ORTHO"
        aspect = float(job.get("width", 1600)) / max(float(job.get("height", 1000)), 1.0)
        camera.data.ortho_scale = projected_ortho_scale(objects, camera, aspect, margin=1.85)
    else:
        camera.data.type = "PERSP"
        camera.data.lens = 70

    light_scale = max(float(job.get("light_scale", 0.72)), 0.0)
    light_specs = [
        ("key", (-max_dim * 1.7, -max_dim * 2.1, max_dim * 2.6), 1800, max_dim * 2.9),
        ("fill", (max_dim * 2.2, -max_dim * 1.0, max_dim * 1.5), 820, max_dim * 4.8),
        ("rim", (0, max_dim * 1.9, max_dim * 2.1), 820, max_dim * 2.2),
        ("front", (0, -max_dim * 2.9, max_dim * 1.2), 650, max_dim * 4.8),
        ("top", (-max_dim * 0.35, -max_dim * 0.35, max_dim * 3.2), 900, max_dim * 3.6),
    ]
    for name, loc, power, size in light_specs:
        bpy.ops.object.light_add(type="AREA", location=loc)
        light = bpy.context.object
        light.name = f"catalog_{name}_light"
        light.data.energy = power * light_scale
        light.data.size = size
        look_at(light, target)

    set_world_background((1.0, 1.0, 1.0, 1.0), max(float(job.get("world_strength", 0.45)), 0.0))


def setup_render(job):
    scene = bpy.context.scene
    scene.render.resolution_x = int(job.get("width", 1600))
    scene.render.resolution_y = int(job.get("height", 1000))
    scene.render.resolution_percentage = 100
    cutout_mode = bool(job.get("green_screen", False))
    scene.render.film_transparent = cutout_mode
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(Path(job["output_path"]))

    if cutout_mode or job.get("engine", "eevee") == "cycles":
        scene.render.engine = "CYCLES"
        scene.cycles.samples = int(job.get("samples", 64))
        scene.cycles.use_denoising = True
        for attr, value in (
            ("transparent_max_bounces", 8),
            ("transparent_min_bounces", 2),
            ("diffuse_bounces", 3),
            ("glossy_bounces", 4),
        ):
            if hasattr(scene.cycles, attr):
                try:
                    setattr(scene.cycles, attr, value)
                except Exception:
                    pass
    else:
        for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
            try:
                scene.render.engine = engine
                break
            except Exception:
                continue
        if hasattr(scene, "eevee"):
            for attr, value in (
                ("use_gtao", True),
                ("gtao_distance", 4),
                ("gtao_factor", 1.4),
                ("use_raytracing", True),
                ("use_ssr", True),
                ("use_ssr_refraction", True),
            ):
                if hasattr(scene.eevee, attr):
                    try:
                        setattr(scene.eevee, attr, value)
                    except Exception:
                        pass
            for attr in ("taa_render_samples", "taa_samples"):
                if hasattr(scene.eevee, attr):
                    setattr(scene.eevee, attr, int(job.get("samples", 64)))

    try:
        for transform in ("AgX", "Filmic", "Standard"):
            try:
                scene.view_settings.view_transform = transform
                break
            except Exception:
                pass
        for look in ("Medium High Contrast", "Medium Contrast", "None"):
            try:
                scene.view_settings.look = look
                break
            except Exception:
                pass
        scene.view_settings.exposure = float(job.get("exposure", -0.2))
        scene.view_settings.gamma = 1
    except Exception:
        pass


def green_key_alpha(r, g, b, threshold):
    if g < 0.25:
        return 1.0
    dominance = g - max(r, b)
    soft = max(threshold * 0.5, 0.02)
    if dominance >= threshold:
        return 0.0
    if dominance <= threshold - soft:
        return 1.0
    return 1.0 - ((dominance - (threshold - soft)) / soft)


def minimum_output_dimensions(width, height, min_width=0, min_height=0):
    width = max(int(width), 1)
    height = max(int(height), 1)
    min_width = max(int(min_width), 0)
    min_height = max(int(min_height), 0)
    scale = max(
        1.0,
        min_width / width if min_width else 1.0,
        min_height / height if min_height else 1.0,
    )
    return math.ceil(width * scale), math.ceil(height * scale)


def process_green_image(input_path, output_path, threshold=70, padding=0, min_width=0, min_height=0):
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    image = bpy.data.images.load(str(input_path), check_existing=False)
    width, height = image.size
    threshold_f = max(0.0, min(float(threshold), 255.0)) / 255.0
    padding = max(int(padding), 0)
    pixels = list(image.pixels[:])

    min_x = width
    min_y = height
    max_x = -1
    max_y = -1
    keyed = [0.0] * len(pixels)

    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 4
            r, g, b, src_a = pixels[idx : idx + 4]
            alpha = min(src_a, green_key_alpha(r, g, b, threshold_f))
            if alpha > 0.01:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
                max_rb = max(r, b)
                if g > max_rb:
                    g = min(g, max_rb)
            else:
                r = g = b = 0.0
            keyed[idx : idx + 4] = [r, g, b, alpha]

    if max_x < min_x or max_y < min_y:
        cutout = bpy.data.images.new("vehicle_renderer_empty_cutout", width=1, height=1, alpha=True)
        cutout.pixels.foreach_set([0.0, 0.0, 0.0, 0.0])
    else:
        min_x = max(min_x - padding, 0)
        min_y = max(min_y - padding, 0)
        max_x = min(max_x + padding, width - 1)
        max_y = min(max_y + padding, height - 1)
        out_w = max_x - min_x + 1
        out_h = max_y - min_y + 1
        out_pixels = [0.0] * (out_w * out_h * 4)
        for y in range(out_h):
            src_y = min_y + y
            for x in range(out_w):
                src_x = min_x + x
                src_idx = (src_y * width + src_x) * 4
                dst_idx = (y * out_w + x) * 4
                out_pixels[dst_idx : dst_idx + 4] = keyed[src_idx : src_idx + 4]
        cutout = bpy.data.images.new("vehicle_renderer_cutout", width=out_w, height=out_h, alpha=True)
        cutout.pixels.foreach_set(out_pixels)

    target_width, target_height = minimum_output_dimensions(*cutout.size, min_width, min_height)
    if (target_width, target_height) != tuple(cutout.size):
        cutout.scale(target_width, target_height)
    cutout.filepath_raw = str(output_path)
    cutout.file_format = "PNG"
    cutout.save()
    bpy.data.images.remove(image)
    bpy.data.images.remove(cutout)
    print(f"Green key: {input_path} -> {output_path} ({target_width}x{target_height})")


def save_image(path, width, height, pixels, name, min_width=0, min_height=0):
    image = bpy.data.images.new(name, width=width, height=height, alpha=True)
    image.pixels.foreach_set(pixels)
    target_width, target_height = minimum_output_dimensions(width, height, min_width, min_height)
    if (target_width, target_height) != (width, height):
        image.scale(target_width, target_height)
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    return target_width, target_height


def percentile(values, ratio):
    if not values:
        return 0.0
    values = sorted(values)
    index = max(0, min(len(values) - 1, int((len(values) - 1) * ratio)))
    return values[index]


def estimate_background_alpha(pixels, width, height):
    patch = max(8, min(width, height) // 24)
    samples = []
    corners = (
        (0, 0, patch, patch),
        (max(width - patch, 0), 0, width, patch),
        (0, max(height - patch, 0), patch, height),
        (max(width - patch, 0), max(height - patch, 0), width, height),
    )
    for x0, y0, x1, y1 in corners:
        for y in range(y0, y1, 2):
            for x in range(x0, x1, 2):
                samples.append(pixels[(y * width + x) * 4 + 3])
    return percentile(samples, 0.75)


def normalize_alpha(alpha, background_alpha):
    if background_alpha <= 0.015:
        return 0.0 if alpha <= 0.035 else alpha
    if alpha <= background_alpha + 0.012:
        return 0.0
    normalized = max(0.0, min(1.0, (alpha - background_alpha) / max(1.0 - background_alpha, 0.001)))
    return 0.0 if normalized <= 0.035 else normalized


def save_green_preview_and_cutout(
    alpha_path,
    green_path,
    cutout_path,
    padding=0,
    crop=True,
    min_width=0,
    min_height=0,
):
    alpha_path = Path(alpha_path).resolve()
    green_path = Path(green_path).resolve()
    cutout_path = Path(cutout_path).resolve()
    green_path.parent.mkdir(parents=True, exist_ok=True)
    cutout_path.parent.mkdir(parents=True, exist_ok=True)

    image = bpy.data.images.load(str(alpha_path), check_existing=False)
    width, height = image.size
    pixels = list(image.pixels[:])
    background_alpha = estimate_background_alpha(pixels, width, height)
    padding = max(int(padding), 0)

    green_pixels = [0.0] * len(pixels)
    normalized_pixels = [0.0] * len(pixels)
    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 4
            r, g, b, a = pixels[idx : idx + 4]
            a = normalize_alpha(a, background_alpha)
            if a <= 0.01:
                r = g = b = 0.0
            normalized_pixels[idx : idx + 4] = [r, g, b, a]
            green_pixels[idx : idx + 4] = [
                r * a + GREEN_SCREEN_COLOR[0] * (1.0 - a),
                g * a + GREEN_SCREEN_COLOR[1] * (1.0 - a),
                b * a + GREEN_SCREEN_COLOR[2] * (1.0 - a),
                1.0,
            ]

    save_image(green_path, width, height, green_pixels, "vehicle_renderer_green_preview")
    bpy.data.images.remove(image)
    save_image(alpha_path, width, height, normalized_pixels, "vehicle_renderer_full_frame_alpha")

    if not crop:
        if cutout_path != alpha_path:
            save_image(
                cutout_path,
                width,
                height,
                normalized_pixels,
                "vehicle_renderer_full_frame_alpha_cutout",
            )
        print(f"Full-frame alpha cutout: {alpha_path} -> {cutout_path} ({width}x{height})")
        return
    encoded_image = bpy.data.images.load(str(alpha_path), check_existing=False)
    encoded_width, encoded_height = encoded_image.size
    if (encoded_width, encoded_height) != (width, height):
        bpy.data.images.remove(encoded_image)
        raise RuntimeError(
            f"Normalized alpha dimensions changed: {width}x{height} -> {encoded_width}x{encoded_height}"
        )
    normalized_pixels = list(encoded_image.pixels[:])
    bpy.data.images.remove(encoded_image)

    min_x = width
    min_y = height
    max_x = -1
    max_y = -1
    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 4
            if normalized_pixels[idx + 3] >= PNG_ALPHA_HALF_STEP:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

    if max_x < min_x or max_y < min_y:
        save_image(cutout_path, 1, 1, [0.0, 0.0, 0.0, 0.0], "vehicle_renderer_empty_alpha_cutout", min_width, min_height)
        return

    min_x = max(min_x - padding, 0)
    min_y = max(min_y - padding, 0)
    max_x = min(max_x + padding, width - 1)
    max_y = min(max_y + padding, height - 1)
    out_w = max_x - min_x + 1
    out_h = max_y - min_y + 1
    out_pixels = [0.0] * (out_w * out_h * 4)
    for y in range(out_h):
        src_y = min_y + y
        for x in range(out_w):
            src_x = min_x + x
            src_idx = (src_y * width + src_x) * 4
            dst_idx = (y * out_w + x) * 4
            r, g, b, a = normalized_pixels[src_idx : src_idx + 4]
            if a <= 0.01:
                r = g = b = 0.0
            out_pixels[dst_idx : dst_idx + 4] = [r, g, b, a]

    final_width, final_height = save_image(cutout_path, out_w, out_h, out_pixels, "vehicle_renderer_alpha_cutout", min_width, min_height)
    print(f"Green preview: {alpha_path} -> {green_path}")
    print(f"Alpha cutout: {alpha_path} -> {cutout_path} ({out_w}x{out_h} -> {final_width}x{final_height}, background_alpha={background_alpha:.4f})")


def process_green_tree(input_path, output_path, threshold=70, padding=0, min_width=0, min_height=0):
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    if input_path.is_file():
        if output_path.suffix.lower() != ".png":
            output_path.mkdir(parents=True, exist_ok=True)
            output_path = output_path / input_path.name
        process_green_image(input_path, output_path, threshold, padding, min_width, min_height)
        return

    output_path.mkdir(parents=True, exist_ok=True)
    for path in sorted(input_path.rglob("*.png")):
        rel = path.relative_to(input_path)
        process_green_image(path, output_path / rel, threshold, padding, min_width, min_height)


def main():
    args = parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:])
    if args.get("key_input"):
        process_green_tree(
            args["key_input"],
            args["key_output"],
            int(args.get("key_threshold", 70)),
            int(args.get("key_padding", 12)),
            int(args.get("cutout_width", 0)),
            int(args.get("cutout_height", 0)),
        )
        return

    job_path = Path(args["job"]).resolve()
    job = json.loads(job_path.read_text(encoding="utf-8"))
    apply_model_tone(job)
    source_dir = Path(job["source_dir"]).resolve()
    output_path = Path(job["output_path"]).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ensure_sollumz(job)
    clear_scene()

    asset_name = job.get("asset_name") or job.get("yft_name")
    import_result = import_assets(source_dir, [asset_name])
    print(f"Import result: {import_result}")

    bind_extracted_textures(job)
    bake_sollumz_shader_parameters()
    wheels_created = mirror_missing_wheels() if job.get("asset_kind", "vehicle") == "vehicle" else 0
    print(f"Wheel mirror created: {wheels_created}")

    objects = mesh_objects()
    if not objects:
        raise RuntimeError(f"No mesh objects imported for {job['model']}")

    setup_scene(job, objects)
    setup_render(job)

    if job.get("save_blend"):
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(job["blend_path"])))

    print(f"Render: {output_path}")
    bpy.ops.render.render(write_still=True)
    if not output_path.exists():
        raise RuntimeError(f"Render output missing: {output_path}")
    if job.get("cutout_path"):
        save_green_preview_and_cutout(
            output_path,
            job.get("green_screen_path") or output_path,
            job["cutout_path"],
            padding=int(job.get("key_padding", 12)),
            min_width=int(job.get("cutout_width", 0)),
            min_height=int(job.get("cutout_height", 0)),
        )


if __name__ == "__main__":
    main()

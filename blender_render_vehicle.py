import json
import math
import os
import re
import sys
from pathlib import Path

import bpy
from mathutils import Vector


TEXTURE_EXTENSIONS = (".png", ".dds", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff")
NON_COLOR_HINTS = ("bump", "normal", "nrm", "nrml", "spec", "rough", "gloss", "_s", "_n")
PAINT_COLOR = (0.82, 0.84, 0.84, 1.0)


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
    return any(hint in combined for hint in NON_COLOR_HINTS)


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


def tune_window_materials():
    changed = 0
    for material_obj in bpy.data.materials:
        name = material_obj.name.lower()
        if not any(hint in name for hint in ("glasswindows", "windscreen", "window")):
            continue
        material_obj.use_nodes = True
        material_obj.diffuse_color = (0.015, 0.028, 0.03, 0.48)
        try:
            material_obj.blend_method = "BLEND"
            material_obj.use_screen_refraction = True
            material_obj.show_transparent_back = True
        except Exception:
            pass
        try:
            material_obj.surface_render_method = "BLENDED"
        except Exception:
            pass
        for node in material_obj.node_tree.nodes:
            if node.bl_idname != "ShaderNodeBsdfPrincipled":
                continue
            set_input(node, "Base Color", (0.015, 0.028, 0.03, 0.48))
            set_input(node, "Alpha", 0.48)
            set_input(node, "Roughness", 0.18)
            set_input(node, "Metallic", 0.0)
            set_input(node, "Coat Weight", 0.45)
            set_input(node, "Coat Roughness", 0.12)
            changed += 1
    return changed


def tune_wheel_materials():
    changed = 0
    wheel_dark = make_principled_material(
        "vehicle_renderer_wheel_dark_metal",
        (0.018, 0.018, 0.017, 1.0),
        roughness=0.28,
        metallic=0.55,
    )
    brake_dark = make_principled_material(
        "vehicle_renderer_brake_dark",
        (0.055, 0.052, 0.048, 1.0),
        roughness=0.5,
        metallic=0.25,
    )
    for obj in bpy.data.objects:
        lower_obj = obj.name.lower()
        if obj.type != "MESH" or not lower_obj.startswith("wheel_"):
            continue
        for slot in obj.material_slots:
            mat = slot.material
            mat_name = mat.name.lower() if mat else ""
            if "tire" in mat_name or "tyre" in mat_name or "black" in mat_name:
                continue
            if "brake" in mat_name or "disc" in mat_name:
                slot.material = brake_dark
            else:
                slot.material = wheel_dark
            changed += 1
    return changed


def duplicate_mesh_at_target(source, target, name):
    bpy.context.view_layer.update()
    clone = source.copy()
    clone.data = source.data.copy()
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
        clone = duplicate_mesh_at_target(source, target, target_name)
        print(f"Wheel mirror: {source_name} -> {clone.name}")
        created += 1
    return created


def bind_extracted_textures(job):
    texture_index = build_texture_index(job.get("texture_dir"))
    if not texture_index:
        print("Texture bind: no extracted textures")
        return 0, 0

    matched = 0
    fallbacks = 0
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
                fallback_key = candidates[0] if candidates else normalized_texture_name(node.name)
                fallback_name, fallback_color, fallback_data = fallback_color_for_name(fallback_key or node.name)
                node.image = make_solid_image(fallback_name, fallback_color, fallback_data)
                fallbacks += 1
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
    neutralized = neutralize_magenta_materials()
    windows = tune_window_materials()
    wheels = tune_wheel_materials()
    print(f"Texture bind matched: {matched}, fallback: {fallbacks}, neutralized: {neutralized}, windows: {windows}, wheels: {wheels}")
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
        if name.startswith("bound ") or "collision" in name or ".bound" in name:
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
        except Exception:
            pass
    return mat


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


def projected_ortho_scale(objects, camera, aspect, margin=1.28):
    min_x, max_x, min_y, max_y = projected_bounds(objects, camera)
    width = max_x - min_x
    height = max_y - min_y
    return max(height, width / max(aspect, 0.01), 1.0) * margin


def setup_scene(job, objects):
    min_v, max_v = world_bounds(objects)
    center = (min_v + max_v) * 0.5
    dims = max_v - min_v
    max_dim = max(dims.x, dims.y, dims.z, 1.0)

    # Move the vehicle center close to origin for stable camera math.
    offset = Vector((0, 0, 0)) - center
    for obj in objects:
        obj.location += offset
    min_v, max_v = world_bounds(objects)
    center = (min_v + max_v) * 0.5
    dims = max_v - min_v
    max_dim = max(dims.x, dims.y, dims.z, 1.0)

    floor_mat = material("catalog_floor", (0.96, 0.96, 0.95, 1.0), 0.62)
    floor_size = max_dim * 4.0
    bpy.ops.mesh.primitive_plane_add(size=floor_size, location=(0, 0, min_v.z - 0.02))
    floor = bpy.context.object
    floor.name = "catalog_floor"
    floor.data.materials.append(floor_mat)

    yaw = math.radians(float(job.get("yaw", -42.0)))
    elevation = math.radians(float(job.get("elevation", 24.0)))
    distance = max_dim * 2.8
    cam_loc = Vector(
        (
            math.sin(yaw) * math.cos(elevation) * distance,
            -math.cos(yaw) * math.cos(elevation) * distance,
            math.sin(elevation) * distance + dims.z * 0.35,
        )
    )
    target = Vector((0, 0, center.z + dims.z * 0.03))

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

    light_specs = [
        ("key", (-max_dim * 1.5, -max_dim * 2.0, max_dim * 2.4), 1350, max_dim * 3.2),
        ("fill", (max_dim * 2.0, -max_dim * 1.0, max_dim * 1.4), 620, max_dim * 4.5),
        ("rim", (0, max_dim * 1.8, max_dim * 2.0), 520, max_dim * 2.4),
        ("front", (0, -max_dim * 2.8, max_dim * 1.2), 320, max_dim * 5.0),
    ]
    for name, loc, power, size in light_specs:
        bpy.ops.object.light_add(type="AREA", location=loc)
        light = bpy.context.object
        light.name = f"catalog_{name}_light"
        light.data.energy = power
        light.data.size = size

    bpy.context.scene.world.color = (1.0, 1.0, 1.0)


def setup_render(job):
    scene = bpy.context.scene
    scene.render.resolution_x = int(job.get("width", 1600))
    scene.render.resolution_y = int(job.get("height", 1000))
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(Path(job["output_path"]))

    if job.get("engine", "eevee") == "cycles":
        scene.render.engine = "CYCLES"
        scene.cycles.samples = int(job.get("samples", 64))
        scene.cycles.use_denoising = True
    else:
        for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
            try:
                scene.render.engine = engine
                break
            except Exception:
                continue
        if hasattr(scene, "eevee"):
            for attr in ("taa_render_samples", "taa_samples"):
                if hasattr(scene.eevee, attr):
                    setattr(scene.eevee, attr, int(job.get("samples", 64)))

    try:
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.view_settings.exposure = 0.35
        scene.view_settings.gamma = 1
    except Exception:
        pass


def main():
    args = parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:])
    job_path = Path(args["job"]).resolve()
    job = json.loads(job_path.read_text(encoding="utf-8"))
    source_dir = Path(job["source_dir"]).resolve()
    output_path = Path(job["output_path"]).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ensure_sollumz(job)
    clear_scene()

    import_result = import_assets(source_dir, [job["yft_name"]])
    print(f"Import result: {import_result}")

    bind_extracted_textures(job)
    wheels_created = mirror_missing_wheels()
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


if __name__ == "__main__":
    main()

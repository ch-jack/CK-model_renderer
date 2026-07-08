import json
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector


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

    floor_mat = material("catalog_floor", (0.82, 0.82, 0.80, 1.0), 0.7)
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
        ("key", (-max_dim * 1.5, -max_dim * 2.0, max_dim * 2.2), 650, max_dim * 3.0),
        ("fill", (max_dim * 2.0, -max_dim * 1.0, max_dim * 1.2), 220, max_dim * 4.0),
        ("rim", (0, max_dim * 1.8, max_dim * 1.8), 240, max_dim * 2.0),
    ]
    for name, loc, power, size in light_specs:
        bpy.ops.object.light_add(type="AREA", location=loc)
        light = bpy.context.object
        light.name = f"catalog_{name}_light"
        light.data.energy = power
        light.data.size = size

    bpy.context.scene.world.color = (0.36, 0.36, 0.34)


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
        scene.view_settings.view_transform = "Filmic"
        scene.view_settings.look = "Medium High Contrast"
        scene.view_settings.exposure = 0
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

    ytds = list(job.get("ytd_names") or [])
    if ytds:
        import_assets(source_dir, ytds)
    import_result = import_assets(source_dir, [job["yft_name"]])
    print(f"Import result: {import_result}")

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

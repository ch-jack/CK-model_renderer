import importlib.util
import struct
import sys
import tempfile
import types
import unittest
import zlib
from enum import Enum, auto
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def load_renderer_module():
    fake_bpy = types.ModuleType("bpy")
    fake_mathutils = types.ModuleType("mathutils")
    fake_mathutils.Matrix = type("Matrix", (), {})
    fake_mathutils.Vector = type("Vector", (), {})
    spec = importlib.util.spec_from_file_location(
        "blender_render_vehicle_test",
        REPOSITORY_ROOT / "blender_render_vehicle.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"bpy": fake_bpy, "mathutils": fake_mathutils}):
        spec.loader.exec_module(module)
    return module


RENDERER = load_renderer_module()


class DependencyState(Enum):
    UNINSTALLED = auto()
    INSTALLED = auto()


class Dependency:
    def __init__(self, name, supported=True):
        self.name = name
        self.supported = supported


class FakeDependencies:
    def __init__(self, root, install_succeeds=True):
        self.root = Path(root)
        self.szio = Dependency("szio")
        self.pymateria = Dependency("pymateria")
        self.unsupported = Dependency("unsupported", supported=False)
        self.DEPENDENCIES = (self.szio, self.pymateria, self.unsupported)
        self.DEPENDENCIES_OPTIONAL = (self.pymateria, self.unsupported)
        self.states = {
            "szio": DependencyState.UNINSTALLED,
            "pymateria": DependencyState.UNINSTALLED,
            "unsupported": DependencyState.UNINSTALLED,
        }
        self.install_succeeds = install_succeeds
        self.install_calls = 0
        self.mount_calls = 0
        self.unmount_calls = 0

    def dependencies_available_state(self):
        return dict(self.states)

    def requirements_path(self):
        return self.root / "requirements.txt"

    def mount_dependencies(self):
        self.mount_calls += 1

    def unmount_dependencies(self):
        self.unmount_calls += 1

    def install_dependencies(self, online_access_override, optional_dependencies_to_install):
        self.install_calls += 1
        if not online_access_override:
            raise AssertionError("online access override is required")
        if optional_dependencies_to_install != {"pymateria"}:
            raise AssertionError(optional_dependencies_to_install)
        if self.install_succeeds:
            self.states["szio"] = DependencyState.INSTALLED
            self.states["pymateria"] = DependencyState.INSTALLED
        return self.install_succeeds


class SollumzDependencyTests(unittest.TestCase):
    def test_installs_missing_dependencies_once_and_removes_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dependencies = FakeDependencies(temp_dir)
            module_name = "fake_sollumz_dependencies_success"
            fake_module = types.ModuleType(module_name)
            fake_module.dependencies = dependencies
            with patch.dict(sys.modules, {module_name: fake_module}):
                RENDERER.ensure_sollumz_dependencies(module_name)
                RENDERER.ensure_sollumz_dependencies(module_name)

            self.assertEqual(1, dependencies.install_calls)
            self.assertFalse((Path(temp_dir) / ".ck-dependency-install.lock").exists())
            self.assertEqual([], RENDERER.missing_sollumz_dependencies(dependencies))

    def test_failed_install_releases_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dependencies = FakeDependencies(temp_dir, install_succeeds=False)
            module_name = "fake_sollumz_dependencies_failure"
            fake_module = types.ModuleType(module_name)
            fake_module.dependencies = dependencies
            with patch.dict(sys.modules, {module_name: fake_module}):
                with self.assertRaisesRegex(RuntimeError, "failure status"):
                    RENDERER.ensure_sollumz_dependencies(module_name)

            self.assertEqual(1, dependencies.install_calls)
            self.assertFalse((Path(temp_dir) / ".ck-dependency-install.lock").exists())

    def test_unsupported_optional_dependency_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dependencies = FakeDependencies(temp_dir)
            dependencies.states["szio"] = DependencyState.INSTALLED
            dependencies.states["pymateria"] = DependencyState.INSTALLED
            self.assertEqual([], RENDERER.missing_sollumz_dependencies(dependencies))


class FakeSocket:
    def __init__(self, node, name):
        self.node = node
        self.name = name
        self.links = []

    @property
    def is_linked(self):
        return bool(self.links)


class FakeNode:
    def __init__(self, name, image_name=None):
        self.name = name
        self.image = types.SimpleNamespace(name=image_name) if image_name else None
        self.outputs = {"Color": FakeSocket(self, "Color")}


class FakeLink:
    def __init__(self, source, target):
        self.from_node = source.node
        self.from_socket = source
        self.to_socket = target


class FakeLinks:
    def remove(self, link):
        link.to_socket.links.remove(link)

    def new(self, source, target):
        link = FakeLink(source, target)
        target.links.append(link)
        return link


class WeaponDiffusePreviewTests(unittest.TestCase):
    def make_graph(self, source_name, source_image_name, diffuse_image_name="w_ar_meigui.png"):
        source_node = FakeNode(source_name, source_image_name)
        diffuse_node = FakeNode("DiffuseSampler", diffuse_image_name)
        base = FakeSocket(None, "Base Color")
        links = FakeLinks()
        links.new(source_node.outputs["Color"], base)
        material = types.SimpleNamespace(
            node_tree=types.SimpleNamespace(links=links)
        )
        bsdf = types.SimpleNamespace(inputs={"Base Color": base})
        return material, bsdf, base, source_node, diffuse_node

    def test_restores_color_diffuse_when_diffpal_sampler_uses_color_image(self):
        material, bsdf, base, _, diffuse_node = self.make_graph(
            "TextureSamplerDiffPal", "w_ar_meigui.png"
        )

        restored = RENDERER.restore_weapon_diffuse_preview(material, bsdf, diffuse_node)

        self.assertEqual("w_ar_meigui", restored)
        self.assertIs(diffuse_node, base.links[0].from_node)
        self.assertIs(diffuse_node.outputs["Color"], base.links[0].from_socket)

    def test_keeps_real_palette_texture_connected(self):
        material, bsdf, base, source_node, diffuse_node = self.make_graph(
            "TextureSamplerDiffPal", "w_ar_meigui_dpal.png"
        )

        restored = RENDERER.restore_weapon_diffuse_preview(material, bsdf, diffuse_node)

        self.assertIsNone(restored)
        self.assertIs(source_node, base.links[0].from_node)

    def test_ignores_regular_diffuse_connection(self):
        material, bsdf, base, source_node, diffuse_node = self.make_graph(
            "DiffuseSampler", "w_ar_meigui.png"
        )

        restored = RENDERER.restore_weapon_diffuse_preview(material, bsdf, diffuse_node)

        self.assertIsNone(restored)
        self.assertIs(source_node, base.links[0].from_node)


class FakeColorSpace:
    def __init__(self):
        self.is_data = False
        self.name = "sRGB"


class FakeImage:
    def __init__(self, path):
        self.filepath = str(path)
        self.name = Path(path).name
        self.colorspace_settings = FakeColorSpace()


class FakeImages:
    def __init__(self):
        self.items = []

    def load(self, path, check_existing=True):
        if check_existing:
            for image in self.items:
                if image.filepath == str(path):
                    return image
        image = FakeImage(path)
        self.items.append(image)
        return image


class TextureRoleIsolationTests(unittest.TestCase):
    def test_reused_diffuse_and_data_texture_get_separate_images(self):
        images = FakeImages()
        fake_data = types.SimpleNamespace(images=images)
        cache = {}
        texture_path = Path("silver.png")

        with patch.object(RENDERER.bpy, "data", fake_data, create=True):
            color = RENDERER.load_texture_image_for_role(texture_path, False, cache)
            data = RENDERER.load_texture_image_for_role(texture_path, True, cache)
            same_color = RENDERER.load_texture_image_for_role(texture_path, False, cache)

        self.assertIsNot(color, data)
        self.assertIs(color, same_color)
        self.assertFalse(color.colorspace_settings.is_data)
        self.assertTrue(data.colorspace_settings.is_data)
        self.assertEqual(2, len(images.items))


class WeaponLightingTests(unittest.TestCase):
    def test_png_metrics_reads_rgba_without_blender_pixel_access(self):
        def chunk(chunk_type, data):
            payload = chunk_type + data
            return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))

        ihdr = struct.pack(">IIBBBBB", 2, 1, 8, 6, 0, 0, 0)
        pixels = bytes((0, 0, 0, 255, 255, 255, 255, 255))
        png = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00" + pixels))
            + chunk(b"IEND", b"")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.png"
            path.write_bytes(png)
            metrics = RENDERER.rendered_png_metrics(path, max_samples=10)

        self.assertEqual(2, metrics["samples"])
        self.assertAlmostEqual(0.5, metrics["mean"], places=3)
        self.assertAlmostEqual(0.5, metrics["bright"], places=3)

    def test_normal_weapon_render_keeps_original_lighting(self):
        factor = RENDERER.weapon_light_correction_factor(
            {"mean": 0.71, "bright": 0.28, "saturation": 0.2}
        )
        self.assertEqual(1.0, factor)

    def test_washed_out_weapon_render_receives_strong_correction(self):
        factor = RENDERER.weapon_light_correction_factor(
            {"mean": 0.88, "bright": 0.80, "saturation": 0.03}
        )
        self.assertGreaterEqual(factor, 0.08)
        self.assertLessEqual(factor, 0.10)

    def test_borderline_bright_weapon_uses_gentler_correction(self):
        factor = RENDERER.weapon_light_correction_factor(
            {"mean": 0.77, "bright": 0.45, "saturation": 0.08}
        )
        self.assertGreater(factor, 0.11)
        self.assertLessEqual(factor, 0.12)


if __name__ == "__main__":
    unittest.main()

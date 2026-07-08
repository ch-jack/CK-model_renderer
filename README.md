# Vehicle Renderer

基于 Blender + Sollumz + CodeWalker YTD 工具的 FiveM/GTA V 车辆批量渲染工具。

作者：JACK  
联系方式：QQ 2518926462

## 功能

- 指定一个车辆资源文件夹，递归扫描 `.yft` 车辆模型。
- 自动优先使用普通 `.yft`，没有普通文件时使用 `_hi.yft`。
- 自动读取同目录 `.ytd`，提取贴图并绑定到 Blender 材质。
- 自动处理 Blender 缺图品红材质，给玻璃、轮毂、黑色件做兜底材质。
- 自动补全部分车辆只导入单侧车轮的问题。
- 支持 `--workers` 多个 Blender 后台进程并发渲染。
- 支持指定车型、输出目录、分辨率、角度、Blender 路径、Sollumz 路径。

## 快速使用

在 FiveM 工程根目录运行：

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" ".\[Tool]\TestVeh" --workers 2 --force
```

输出目录：

```text
<输入目录>\_vehicle_renders
```

## 依赖

- Windows
- Python 3.7+
- Blender 5.1 或兼容版本
- Sollumz 2.8.x
- `[Tool]\autorpf\newdll\YtdTools.exe`
- `[Tool]\autorpf\newdll\texconv.exe`

如果 Blender 不在默认位置：

```powershell
python ".\render_all_vehicles.py" "D:\cars" --blender "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
```

如果 Sollumz 没装进 Blender：

```powershell
python ".\render_all_vehicles.py" "D:\cars" --sollumz "D:\tools\Sollumz"
```

## 常用命令

指定输出目录：

```powershell
python ".\render_all_vehicles.py" "D:\cars" --out "D:\vehicle_images" --workers 4
```

只渲染指定车型：

```powershell
python ".\render_all_vehicles.py" "D:\cars" --model police --model sultan --workers 2
```

强制覆盖旧图片：

```powershell
python ".\render_all_vehicles.py" "D:\cars" --force
```

跳过已有图片：

```powershell
python ".\render_all_vehicles.py" "D:\cars" --skip-existing
```

不提取贴图，只渲染模型：

```powershell
python ".\render_all_vehicles.py" "D:\cars" --skip-textures
```

## 输出结构

```text
_vehicle_renders/
  car_a.png
  car_b.png
  _textures/
    car_a/
      *.png
  _jobs/
    car_a.json
  _logs/
    car_a.log
    car_a.textures.log
```

## 已验证

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" ".\[Tool]\TestVeh" --workers 2 --force
```

测试输出：

```text
[ok] fordc72
[ok] 10ttrsscpd
Done. OK=2 FAIL=0
```

## 说明

工具会从车辆资源自己的 `.ytd` 提取贴图。若车辆依赖 GTA 原版共享贴图但资源包里没有带上，渲染脚本会使用内置兜底材质避免品红缺图。共享贴图不会被打包进本仓库。

## 参考项目

- [dexyfex/CodeWalker](https://github.com/dexyfex/CodeWalker)
- [Sollumz/Sollumz](https://github.com/Sollumz/Sollumz)

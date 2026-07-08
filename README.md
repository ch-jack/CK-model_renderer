# Vehicle Renderer

基于 Blender + Sollumz 的 FiveM/GTA V 车辆批量渲染工具。

给一个车辆资源文件夹，工具会递归扫描 `.yft` 车型文件，并用多个 Blender 后台进程并发输出 PNG 车辆预览图。

作者：JACK  
联系方式：QQ 2518926462

## 功能

- 直接指定一个文件夹，自动扫描全部车辆 `.yft`
- 支持 `--workers` 多进程并发渲染
- 支持只渲染指定车型：`--model`
- 自动识别 `*_hi.yft` 和普通 `.yft`
- 支持指定 Blender 路径、Sollumz 插件路径
- 支持输出日志、任务 JSON、跳过已存在图片
- 可选用已有 `RpfTools.exe` 解包 `.rpf`

## 环境要求

- Windows
- Python 3.7+
- Blender 5.1 或兼容版本
- Sollumz 2.8.x，并已安装 `szio` / `pymateria` 依赖

当前测试环境：

- Blender 5.1.2
- Sollumz 2.8.3
- Python 3.7.0 外层调度

## 快速开始

在本仓库目录运行：

```powershell
python .\render_all_vehicles.py "D:\path\to\vehicle_pack" --workers 3
```

在 FiveM 服务器工程的 `[Tool]` 目录下运行：

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" ".\[Tool]\TestVeh" --workers 2 --force
```

默认输出目录：

```text
<输入目录>\_vehicle_renders
```

## 常用命令

指定输出目录：

```powershell
python .\render_all_vehicles.py "D:\cars" --out "D:\renders" --workers 4
```

只渲染指定车型：

```powershell
python .\render_all_vehicles.py "D:\cars" --model police --model sultan --workers 2
```

指定 Blender 和 Sollumz：

```powershell
python .\render_all_vehicles.py "D:\cars" --blender "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --sollumz "D:\tools\Sollumz"
```

强制覆盖已有图片：

```powershell
python .\render_all_vehicles.py "D:\cars" --force
```

跳过已有图片：

```powershell
python .\render_all_vehicles.py "D:\cars" --skip-existing
```

## 输出结构

```text
_vehicle_renders/
  10ttrsscpd.png
  fordc72.png
  _jobs/
    10ttrsscpd.json
  _logs/
    10ttrsscpd.log
```

## 重要限制

当前稳定链路能可靠导入 `.yft` 模型并批量出 PNG。

外部 `.ytd` 贴图字典在当前 Sollumz 路径下不会自动挂到材质上，部分车辆会显示为 Blender 的洋红色缺贴图材质。模型、角度、取景和 PNG 输出是正常的。完整贴图效果需要后续接 CodeWalker/YTD 贴图映射链路。

更多用法见 [docs/USAGE.zh-CN.md](docs/USAGE.zh-CN.md)。

## 参考项目

- [dexyfex/CodeWalker](https://github.com/dexyfex/CodeWalker)
- [Sollumz/Sollumz](https://github.com/Sollumz/Sollumz)

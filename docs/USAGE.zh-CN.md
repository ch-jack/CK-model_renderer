# 使用文档

作者：JACK  
联系方式：QQ 2518926462

## 1. 工具目标

`vehicle_renderer` 用于从 FiveM/GTA V 车辆资源目录批量生成车辆预览图。它不是游戏内截图工具，而是通过 Blender 后台导入 `.yft` 模型并渲染 PNG。

适合这些目录结构：

```text
vehicle_pack/
  car_a/
    stream/
      car_a.yft
      car_a_hi.yft
      car_a.ytd
  car_b/
    stream/
      car_b.yft
      car_b_hi.yft
      car_b.ytd
```

也支持直接把多个 `stream` 文件夹放在一个大目录下，工具会递归扫描。

## 2. 安装准备

必须安装：

- Python 3.7 或更高版本
- Blender
- Sollumz 插件

建议使用 Blender 5.1 和 Sollumz 2.8.x。

如果 Blender 不在默认位置，可以用 `--blender` 指定：

```powershell
python .\render_all_vehicles.py "D:\cars" --blender "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
```

如果 Sollumz 没有装进 Blender 用户插件目录，可以用 `--sollumz` 指定插件源码目录：

```powershell
python .\render_all_vehicles.py "D:\cars" --sollumz "D:\tools\Sollumz"
```

## 3. 基础使用

进入工具目录后执行：

```powershell
python .\render_all_vehicles.py "D:\cars"
```

工具会：

1. 递归扫描 `D:\cars` 下的 `.yft`
2. 优先使用普通 `.yft`，没有普通文件时使用 `_hi.yft`
3. 为每台车生成一个 Blender 任务
4. 输出 PNG 到 `D:\cars\_vehicle_renders`

## 4. 多线程/并发

使用 `--workers`：

```powershell
python .\render_all_vehicles.py "D:\cars" --workers 4
```

实现方式是多进程启动 Blender 后台任务，不是在单个 Blender 里开线程。这样更稳定，但更吃 CPU/GPU/内存。

建议：

- 普通电脑：`--workers 2`
- 性能较好的机器：`--workers 3` 或 `--workers 4`
- 显存/内存不够时降低 workers

## 5. 常用参数

### 指定输出目录

```powershell
python .\render_all_vehicles.py "D:\cars" --out "D:\vehicle_images"
```

### 指定车型

```powershell
python .\render_all_vehicles.py "D:\cars" --model police
```

多个车型：

```powershell
python .\render_all_vehicles.py "D:\cars" --model police --model sultan
```

### 强制重渲染

```powershell
python .\render_all_vehicles.py "D:\cars" --force
```

### 跳过已有图片

```powershell
python .\render_all_vehicles.py "D:\cars" --skip-existing
```

### 分辨率

```powershell
python .\render_all_vehicles.py "D:\cars" --width 1600 --height 1000
```

### 角度

默认角度是前侧视角：

```powershell
python .\render_all_vehicles.py "D:\cars" --yaw 135 --elevation 24
```

### 渲染引擎

默认 `eevee`，速度快：

```powershell
python .\render_all_vehicles.py "D:\cars" --engine eevee
```

更慢但光照更稳定：

```powershell
python .\render_all_vehicles.py "D:\cars" --engine cycles --samples 64
```

## 6. RPF 输入

如果输入目录里是 `.rpf`，可尝试：

```powershell
python .\render_all_vehicles.py "D:\cars_rpf" --unpack-rpf --workers 2
```

默认会查找：

```text
[Tool]\autorpf\newdll\RpfTools.exe
```

也可以手动指定：

```powershell
python .\render_all_vehicles.py "D:\cars_rpf" --unpack-rpf --rpf-tool "D:\tools\RpfTools.exe"
```

## 7. 输出说明

输出目录示例：

```text
_vehicle_renders/
  fordc72.png
  10ttrsscpd.png
  _jobs/
    fordc72.json
    10ttrsscpd.json
  _logs/
    fordc72.log
    10ttrsscpd.log
```

说明：

- PNG 是最终图片
- `_jobs` 是每台车的任务参数
- `_logs` 是 Blender 输出日志，失败时优先看这里

## 8. 常见问题

### 图片是洋红色

这表示模型导入成功，但外部 `.ytd` 贴图没有挂上。当前稳定链路主要保证批量出模型图，完整贴图需要后续接 CodeWalker/YTD 贴图映射。

### 某台车失败

看对应日志：

```text
_vehicle_renders\_logs\车型名.log
```

常见原因：

- 模型文件损坏
- Sollumz 不支持该资源的某些数据
- Blender/Sollumz 依赖没装完整
- 显存/内存不足

### 并发越高越慢

Blender 是重进程，`--workers` 过高会抢 GPU/CPU/内存。降低到 2 或 3 通常更稳。

## 9. 已验证命令

在 FiveM 工程中：

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" ".\[Tool]\TestVeh" --workers 2 --force
```

测试输出：

```text
[ok] fordc72
[ok] 10ttrsscpd
Done. OK=2 FAIL=0
```

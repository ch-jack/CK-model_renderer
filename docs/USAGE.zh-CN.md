# 使用文档

作者：JACK  
联系方式：QQ 2518926462

## 1. 目标

`vehicle_renderer` 用于把 FiveM/GTA V 车辆资源目录批量渲染成 PNG 预览图。它通过 Blender 后台导入 `.yft`，用 CodeWalker 相关工具从 `.ytd` 提取贴图，再把贴图绑定到材质。

支持常见目录结构：

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

## 2. 基础命令

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" ".\[Tool]\TestVeh" --workers 2 --force
```

工具会：

1. 递归扫描输入目录下的 `.yft`。
2. 自动匹配同目录 `.ytd`。
3. 临时复制 `.ytd` 并提取贴图，不修改原始车辆文件。
4. 调用 Blender 后台导入模型、绑定贴图、补缺轮、渲染 PNG。
5. 输出到 `<输入目录>\_vehicle_renders`。

## 3. 多线程

`--workers` 表示并行启动多少个 Blender 后台进程：

```powershell
python ".\render_all_vehicles.py" "D:\cars" --workers 4
```

建议：

- 普通机器：`--workers 2`
- CPU/内存较强：`--workers 3` 或 `--workers 4`
- 显存或内存不够时降低 workers

## 4. 常用参数

指定输出目录：

```powershell
python ".\render_all_vehicles.py" "D:\cars" --out "D:\vehicle_images"
```

只渲染指定车型：

```powershell
python ".\render_all_vehicles.py" "D:\cars" --model police --model sultan
```

强制重渲染：

```powershell
python ".\render_all_vehicles.py" "D:\cars" --force
```

跳过已有 PNG：

```powershell
python ".\render_all_vehicles.py" "D:\cars" --skip-existing
```

指定分辨率：

```powershell
python ".\render_all_vehicles.py" "D:\cars" --width 1600 --height 1000
```

指定角度：

```powershell
python ".\render_all_vehicles.py" "D:\cars" --yaw 135 --elevation 24
```

关闭贴图提取：

```powershell
python ".\render_all_vehicles.py" "D:\cars" --skip-textures
```

## 5. 贴图处理

默认会使用：

```text
[Tool]\autorpf\newdll\YtdTools.exe
[Tool]\autorpf\newdll\texconv.exe
```

流程：

1. 自动读取工具目录内置的 `vehshare*.ytd` 共享贴图。
2. 把共享 `.ytd` 和车辆 `.ytd` 复制到临时目录。
3. 用 YtdTools 提取 DDS。
4. 用 texconv 转 PNG。
5. Blender 里按 Sollumz 材质节点的纹理名绑定图片。

不会直接改原始 `.ytd`。

## 6. 输出说明

```text
_vehicle_renders/
  fordc72.png
  10ttrsscpd.png
  _textures/
    fordc72/
    10ttrsscpd/
  _jobs/
    fordc72.json
    10ttrsscpd.json
  _logs/
    fordc72.log
    fordc72.textures.log
```

- PNG：最终图片。
- `_textures`：从 `.ytd` 提取出的临时贴图缓存。
- `_jobs`：每台车传给 Blender 的参数。
- `_logs`：Blender 和贴图提取日志。

## 7. 常见问题

### 图片是品红色

说明贴图没绑定。现在工具会自动提取车辆 `.ytd` 和内置 `vehshare*.ytd` 并绑定；如果还是缺图，通常是车辆还依赖其它共享贴图，需要把对应 `.ytd` 放到工具目录或 `shared_ytd` 目录。

### 车轮少一边

部分 `.yft` 只导入左侧车轮 mesh，右侧只有碰撞体。脚本会根据右侧碰撞体位置自动镜像补全右侧车轮。

### 渲染失败

先看：

```text
_vehicle_renders\_logs\车型名.log
_vehicle_renders\_logs\车型名.textures.log
```

常见原因：

- 车辆文件损坏
- Sollumz 不支持该资源的某些数据
- Blender/Sollumz 依赖不完整
- workers 太高导致内存不足

## 8. 验证命令

```powershell
python ".\[Tool]\vehicle_renderer\render_all_vehicles.py" ".\[Tool]\TestVeh" --workers 2 --force
```

期望输出：

```text
[ok] fordc72
[ok] 10ttrsscpd
Done. OK=2 FAIL=0
```

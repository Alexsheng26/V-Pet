# sprites/

把素材按状态名建目录丢进来就会自动生效，代码一行都不用改。
这个目录空着的时候，程序会退回到 `render.py` 里用 QPainter 现画的占位角色。

```
sprites/
  idle/   00.png  01.png  02.png ...
  walk/   00.png  01.png ...
  drag/
  fall/
  sleep/
  happy/
  cling/
  dizzy/
  curious/
```

约定：

- 目录名 = `vpet/state.py` 里 `State` 枚举的值：`idle` / `walk` / `drag` / `fall` / `sleep` / `happy` / `cling` / `dizzy` / `curious`
- **文件名排序就是帧序**，所以用 `00 01 02` 这样补零的两位数，别用 `1 2 10`
- 带 alpha 通道的 PNG。透明区域是真透明 —— 不用抠色，也别留白底
- 所有帧同尺寸，正方形，建议 108×108 或它的整数倍
- 只画**朝右**的方向，朝左的由程序自动镜像
- 播放帧率见 `render.py` 的 `SPRITE_FPS`（默认 8）
- 缺哪个状态就自动退回 `idle`，可以一个状态一个状态地补，不用一次画齐

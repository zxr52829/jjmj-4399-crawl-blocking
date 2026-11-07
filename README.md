# 竞技麻将（4399 / 来游戏 jjmj）· 爬取阻断分析

一份 H5 棋牌游戏的取数过程记录：**哪些拿得到、哪些拿不到、卡在哪一行代码、以及为什么它是设计上不可绕的**。

不是教程，是取证报告。每条结论都标注了证据来源。

---

## 0. 结论先行

| 层 | 能拿到？ | 卡点 |
|---|---|---|
| 前端静态资源（JS / 引擎 / 配置） | ✅ 完整 | 无 |
| AssetBundle（预制体 / 图集元数据 / Spine / 特效） | ✅ 完整 | 无 |
| **原始图片文件（.png / .jpg）** | ⚠️ **仅 39 张** | 3,517 个资源挂在 `config.packs` 里，无独立 `native` URL |
| 原始工程路径 | ✅ 已完整还原 2,287 条 | 无 |
| **游戏入口 URL** | ❌ 需一次 4399 登录 | cookie → `sign` → 302 |
| **业务服务器协议** | ❌ 完全不可达 | 服务端权威，客户端只发指令 |

一句话：**静态资源能全拿，游戏跑不起来。**

跑不起来的根因不是"资源缺"，而是**逻辑在服务端**，且入口被一次**服务端签名的跳转**守着。

---

## 1. 架构：这不是一个能"下载下来就能玩"的东西

```
www.4399.com/flash/xxxx.htm          ← 4399 游戏页
        │
        │  4399 H5 平台用 cookie 换签名 URL
        ▼
api.zxlyx.cn/st/jjmj/h5/4399?userid=…&time=…&sign=…
        │
        │  302 跳转
        ▼
g2022jjmj-cdn.laiyouxi.com/<ver>/index.html?{同一串参数}
        │
        ▼
Cocos Creator 3.8.3 引擎 → 加载 53 个 AssetBundle → 进大厅 → WebSocket 连业务服
```

**关键点在第 3 步**：CDN 上的 `index.html` 本身是公开的（无需 cookie），但**知道它的完整 URL 需要一次带 `sign` 的跳转**。而 `sign` 由 4399 服务端用密钥签发。

---

## 2. 能拿到的部分（已完整落盘）

### 2.1 前端外壳

```
index.html                    ← 页面骨架
style.c04b1.css
application.bc2e7.js          ← 加载器，settingsPath 硬编码在这里
index.0ae51.js
src/polyfills.bundle.5adbf.js
src/system.bundle.543e6.js
src/import-map.69f82.json
src/settings.f8033.json       ← ★ 全局配置：53 个 bundle + 版本号 + 加密密钥
src/chunks/bundle.64b8b.js
cocos-js/cc.dc181.js          ← 引擎（3.8.3）
cocos-js/spine-9a8528df.js
cocos-js/assets/spine-59f406dc.wasm
cocos-js/assets/meshopt_decoder.wasm-12c0a404.wasm
```

### 2.2 AssetBundle（53 个，3,400 个文件）

每个 bundle 的结构：

```
assets/{bundle}/
├── config.{ver}.json
├── index.{ver}.js
├── import/{uuid前2位}/{uuid}.{hash}.json
└── native/{uuid前2位}/{uuid}.{hash}.{ext}
```

`config.{ver}.json` 里 `paths` 字段**完整保留了原始工程路径**，这是能还原的前提：

```json
{
  "uuids": ["00ayuGZvlA7qu+nKrcHr4m", "0010cebphJqrErBeCQf6d1"],
  "paths": {
    "0": ["weinmj/static/wein/ico_zjzs_4jp", 1, 1],
    "1": ["static/spine/hupaihuo/hupaihuo", 8, 1]
  }
}
```

映射链：`paths[i][0] ←→ uuids[i] ←→ decompress_uuid() ←→ 磁盘文件名`

UUID 是 **22 字符压缩 base64**，需解压：前 2 字符原样，之后每 2 个 base64 字符解出 3 个 hex 字符。

### 2.3 规则配置（32 张表，纯 JSON）

`rconfig_online/` 独立于 bundle，直接 HTTP GET 可得：

```
ab_config/
├── globalConfig        全局参数（番数、倍数、时限）
├── gameRoomRule_508    房间规则选项（★ 最有用）
├── gameList_508        玩法列表
├── mode                模式
├── levelConfig         等级
├── attackConfig        番型
├── baseConfig          杂项 KV（含 UI 布局坐标）
├── onoff_508           功能开关（★ 见 §4）
├── errorCode           错误码
└── …共 32 张
```

`gameRoomRule_508` 直接给出了完整的规则枚举，例如：

```json
[406300, [0,3,4,5], ["不封顶","3番","4番","5番"]]
[406301, [1,0],     ["自摸加番","自摸加底"]]
[408515, [0,1],     ["","红中赖子"]]
[408517, [0,1],     ["","去万"]]
```

这张表足以让任何人**从零实现一套玩法完全一致的规则引擎**——不需要碰服务端。

---

## 3. 拿不到的部分

### 3.1 原始图片：3,517 个资源没有独立 URL

全局统计（53 个 bundle 求和）：

```
总 uuids: 13,258
总 paths:  9,741
差    :    3,517   ← 无 paths 映射，即无原始路径
```

这 3,517 个资源存在于 `config.uuids`，但不在 `config.paths`，由 `config.packs` 打包存储。`packs` 的真实结构是 **包哈希 → uuid 下标列表**：

```json
"packs": {
  "011b4175a": [960, 743],
  "011c792b7": [351, 352, 452, 517, 651, 214, 769],
  "01c0f9b8c": [398, 458, 670]
}
```

即：下标 `960`、`743` 这两个资源被打进名为 `011b4175a` 的 pack 里。

**它们没有独立的 `native/{uuid}.{hash}.png` 路径**，因此无法按 URL 抓取。要取出需要先按 pack 哈希找到 pack 二进制文件，再按下标切片——而 pack 二进制本身的 URL 规则与逐文件路径不同，不在这套镜像的抓取逻辑内。

实测后果：`assets/` 全量落盘后（3,375 个文件），图片只有 **39 张**：

```
3,275 × .json      ← 预制体 / 材质 / 动画 / 图集元数据
   53 × .js        ← bundle 索引
   39 × .png/.jpg  ← 实际图片
    6 × .bin
    1 × .ttf       ← sys_text.ttf（2.6 MB，含完整中文字形）
    1 × .cconb
```

牌桌纹理、牌面精灵图全部**元数据在、像素不在**：

```
restored/ab_effect/desk_texture/desk_bg_100001/texture.json
→ [1,0,0,["cc.ImageAsset"],0,[{"fmt":"0","w":0,"h":0},-1],[0],0,[],[],[]]
                                    ^^^^^^^^^^^^^^ 宽高为 0，占位空图
```

同类空占位：`pl_pai2d_new/texture.json`、`plist_res/*/texture.json`（70 个全空）、`ab_mj/mjpai.json`。

> **为什么会这样**：`packs` 里的资源需要先下载整个 pack 二进制再按下标切片。镜像脚本按 `import/` + `native/` 逐文件抓取，天然覆盖不到 pack 内资源。这不是反爬，是 Cocos 的打包机制。

### 3.2 游戏入口：一次服务端签名跳转

```
GET api.zxlyx.cn/st/jjmj/h5/4399?userid=…&time=…&sign=…
→ 302 → g2022jjmj-cdn.laiyouxi.com/<ver>/index.html?userid=…&time=…&sign=…
```

`sign` 由服务端用密钥签发。**同一个账号连续两次请求，得到不同 `sign`**（以下为结构示例，值已脱敏）：

```
t=<ts1> → sign=<32位hex A>
t=<ts2> → sign=<32位hex B>      ← 与 A 不同
```

证明是**逐请求签发**，不是固定值，本地无法预计算。

尝试过的路径：

| 尝试 | 结果 |
|---|---|
| `g.php?userinfo={userId}\|{token}` | 返回签名后的跳转 |
| `authStatus` | `{"code":30000,...,"result":true}` — token 有效 |
| `/intermodal/game/url`（各种 cookie / 参数摆法） | `{"code":10005,"message":"access_token_expire"}` |

`authStatus` 说 token 有效，`/intermodal/game/url` 说 token 过期——**两个接口的凭据口径不同**，后者要的不是 `4399_HTML5_ACCESS_TOKEN`。

> 注：`onoff_508` 里存在开关 `login_use_sign = 0`。这说明生产环境**当前没走 sign 登录**，但不代表入口免签——入口跳转与登录签名是两回事。此处如实记录，不做推断。

### 3.3 业务服务器：逻辑在对面

进大厅后，匹配、发牌、出牌校验、胡牌判定、结算全部走 WebSocket 到业务服务器。客户端只发**指令**，不是发**结果**：

```
客户端 → 服务器： "我要打第 3 张"
服务器 → 客户端： "可以" / "不行，你没有这张牌"
```

没有服务器，客户端手里只有：

- 协议格式（可能可以从前端 JS 逆出来）
- 没有牌局状态机、没有发牌算法、没有判胡实现

**即便自己写一个假服务器**，也要自己实现全部规则——那已经不是"让它跑起来"，而是"重写一个游戏"。

---

## 4. 三层阻断的完整链条

```
第 1 层：入口    需要一次 4399 登录 → 服务端签名 → 才能拿到 index.html 的完整 URL
                 ↓ 已突破（浏览器已登录态下抓到了 172 条实测 URL）
第 2 层：资源    53 个 bundle 可全量抓取，但 3,517 个资源在 pack 内、无独立 URL
                 ↓ 部分突破（元数据全有，像素缺 39 张之外的全部牌面）
第 3 层：逻辑    规则判定在服务端，客户端无权威逻辑
                 ↓ 未突破，且不可突破（除非重写）
```

**第 1 层可绕**（拿到一次登录态即可），**第 2 层可绕**（写 pack 解包器，前提是能拿到 pack 文件本身），**第 3 层绕不过**——那是架构，不是防护。

---

## 5. 这件事真正说明了什么

`sign` 不是"反爬措施"，是**平台分发的正常机制**：4399 作为渠道方，要控制哪家 CP 的哪个游戏分发给哪个用户。它顺带阻断了自动化抓取，但设计意图不是这个。

`packs` 不是"资源保护"，是**Cocos 的打包优化**：把大量小图合成少数大文件，减少 HTTP 请求。它顺带让逐文件抓取失效，但设计意图也不是这个。

真正把游戏锁死的是**服务端权威架构**——这是所有联网棋牌的标准做法，因为客户端判胡等于把牌局交给作弊者。

所以：**"爬下来就能玩"这个前提本身就是错的**，与技术水平无关。

---

## 6. 如果目标是"自己有一套麻将"

路径是**重写**，不是**提取**。手上已经有的是：

- ✅ 完整规则枚举（`gameRoomRule_508`，32 张配置表）
- ✅ 完整 UI 布局坐标（`baseConfig` 里的 `layout` 字段）
- ✅ 元数据完整的资源树（2,287 条原始路径）
- ❌ 牌面像素（需自己画，或美术重制）

开源参考实现：

- [liuchao0739/xiangzhuo](https://github.com/liuchao0739/xiangzhuo) — Skynet + Lua + Cocos 3.8.8，服务端权威，MIT
- [niyueling/tianle-game-server](https://github.com/niyueling/tianle-game-server) — Node.js + Cocos 3.8.1，前后端齐全，MulanPSL-2.0

两者都自带完整判胡实现，比自己从零写快得多。

---

## 7. 附：复现材料

本仓库只含文字与脚本，不含游戏资源。

| 本仓库文件 | 说明 |
|---|---|
| `restore_paths.py` | 路径还原器：UUID 解压 + `paths`/`uuids` 映射 + 同名冲突处理 |

抓取时需要的上游材料（自行获取，不随仓库分发）：

| 材料 | 说明 |
|---|---|
| `settings.f8033.json` | 53 bundle 清单 + 版本号，任何抓取脚本的入口 |
| 浏览器实测 URL 清单 | 游戏自身加载过的精确路径，不含猜测 |
| `config.{ver}.json` × 53 | 含 `uuids` / `paths` / `packs` / `extensionMap` |
| `rconfig_online/ab_config/` | 32 张规则配置表（纯 JSON，可直接读取） |

### `restore_paths.py` 用法

```bash
python restore_paths.py ./mirror --out=restored
```

核心映射：

```
paths[i][0]  ←→  uuids[i]  ←→  decompress_uuid()  ←→  磁盘文件名
   原始路径         压缩UUID        标准UUID
```

UUID 解压（22 字符压缩 base64 → 标准 UUID）：前 2 字符原样保留，之后每 2 个
base64 字符解出 3 个 hex 字符，最后格式化为 `8-4-4-4-12`。

---

## 声明

《竞技麻将》著作权归原作者及 4399 / 来游戏（laiyouxi）所有。

本文档仅记录技术观察：Cocos Creator AssetBundle 格式、H5 平台分发链路、客户端/服务端职责边界。**不包含**账号凭据、可复用的登录态、服务端协议实现或任何玩家数据。

文中出现的账号标识符已做脱敏。请勿用于商业用途或资源二次分发。

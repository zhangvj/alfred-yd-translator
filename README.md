# YD Translator — 自定义有道翻译 Alfred 工作流

基于 [wensonsmith/YoudaoTranslator](https://github.com/wensonsmith/YoudaoTranslator) 的思路自定义实现，**重点修复参考项目对全大写、中划线、下划线单词翻译不准的问题**。

本插件内置**智能文本规范化（normalizer）**，正确处理：

| 输入 | 规范化结果 | 实测翻译 |
|---|---|---|
| `NASA` / `API` / `HTML5` | `NASA` / `API` / `HTML5`（全大写缩写保留） | 美国国家航空航天局 / API |
| `USER_NAME` | `USER NAME` | 用户名 |
| `getUserName` | `get user name` | 获取用户名 |
| `well-known` / `USER-FRIENDLY` | `well known` / `USER FRIENDLY` | 众所周知 |
| `HTTPRequest` | `http request` | HTTP请求 |
| `iPhone` / `iOS` / `macOS` | `iphone` / `ios` / `macos` | 品牌词保护 |
| `你好世界` / `こんにちは` | 原样 | 自动识别中英日韩 |

> 实测发现全大写缩写**必须保留原样**：小写化会把 `API` 误译为「蜜蜂」（拉丁词 api），
> 而 `NASA` 大写可得到「美国国家航空航天局（NASA）」的完整翻译。

## 技术栈

- **Python3 标准库**（urllib / hashlib / json / re），零第三方依赖、无需构建
- 有道智云**官方 API**（v3 签名: `sign = md5(appKey + input(q) + salt + curtime + secret)`）
- Alfred 5 工作流

## 目录结构

```
├── Makefile                  # make test / build / install / clean
├── workflow/                 # ← Alfred 工作流包
│   ├── info.plist            # 工作流定义（Script Filter / Hotkey / 流程图 / 配置界面）
│   ├── yd.py                 # Script Filter 入口
│   ├── yd_speak.py           # 本地发音动作节点（Cmd+Enter）
│   └── lib/
│       ├── normalizer.py     # ★ 智能文本规范化（核心）
│       ├── detect.py         # 语言检测（汉字/假名/谚文）
│       ├── youdao.py         # 有道 API 客户端（v3 签名）
│       ├── pinyin.py         # ★ 拼音组词中间态检测（防误触发）
│       ├── guard.py          # ★ 防刷量守卫（缓存/限速/链式合并/指数冷却）
│       ├── output.py         # Alfred Script Filter JSON 构建器
│       ├── tts.py            # 发音 URL
│       └── config.py         # 环境变量配置
└── tests/                    # 单元测试（unittest）
```

## 快速开始

前置条件：macOS 自带 Python3（需安装 Xcode Command Line Tools: `xcode-select --install`）。

### 1. 申请有道 API Key

1. 注册[有道智云](https://ai.youdao.com)
2. 创建「自然语言翻译」服务
3. 创建应用并绑定服务，获得**应用 ID (appKey)** 与**应用密钥 (secret)**

### 2. 安装工作流

推荐优先从本仓库 GitHub Releases 下载对应版本的 `yd-translator.alfredworkflow` 安装包并直接导入 Alfred。

如需本地修改后再安装，可使用自定义打包方式：

```bash
make build     # 打包为 yd-translator.alfredworkflow（含 plist 校验）
make install   # 导入 Alfred
```

> 若已安装参考项目 YoudaoTranslator，请先删除旧工作流，避免关键字 `yd` 冲突。

### 3. 配置

**推荐方式（更新插件后 key/secret 自动保留）：**

```text
yd setkey <应用ID>
yd setsecret <应用密钥>
yd config        # 查看当前配置状态
yd reset         # 清除已保存的 key/secret
```

key/secret 会写入 Alfred 的 **Workflow Data 目录**
（`~/Library/Application Support/Alfred/Workflow Data/com.zvj.yd-translator/config.json`，
权限 600），**更新/替换工作流时自动保留**，无需重新输入。

> 也可在 Alfred → Workflows → YD Translator → 右上角 [X] 面板填写环境变量
> （`yd_key`/`yd_secret` 等）。环境变量优先级高于数据文件；但环境变量方式
> 在更新工作流时可能被新版本覆盖，因此**推荐用 `yd setkey` 方式**。

| 变量 | 说明 | 默认 |
|---|---|---|
| `yd_key` | 有道应用 ID (appKey) | - |
| `yd_secret` | 有道应用密钥 (secret) | - |
| `yd_to` | 非中文目标语言 | `zh-CHS` |
| `yd_cn_to` | 中文目标语言 | `en` |
| `yd_voice` | 在线发音音色 | `en`（美音） |
| `yd_sign` | 签名方式 | `auto` |

> **签名说明**：有道早期创建的应用只支持旧版 v1 签名
> （`md5(appKey+q+salt+secret)`），新应用用 v3。默认 `auto` 先试 v3、
> 遇「签名检验失败」自动回退 v1，新旧应用都能用；若你的应用固定失败重试，
> 可手动改为 `v1`（参考项目 V2 即用 v1，实测本机 key 需 v1）。

## 如何更新插件（不丢失 key/secret）

因为 key/secret 保存在 **Workflow Data 目录**（独立于工作流包），更新流程很简单：

1. 用 `yd setkey` / `yd setsecret` 设置过凭据（或确认 `yd config` 显示来源为「数据文件」）；
2. 获取新版：重新 `make build && make install`，或直接打开新版 `.alfredworkflow`；
3. 出现「Replace existing workflow?」提示时选择 **Replace**（同一 bundleid，数据目录保留）；
4. 完成 —— `yd config` 确认 key/secret 仍在，无需重新输入。

> 若凭据之前是填在 [X] 面板环境变量里的，更新后丢失了，改用 `yd setkey` /
> `yd setsecret` 保存一次，之后更新就不会再丢。

## 使用

| 操作 | 效果 |
|---|---|
| `yd <内容>` | 翻译（自动识别中英日韩，智能拆分大小写/分隔符） |
| Enter | 复制译文到剪贴板（Alfred 窗口关闭） |
| Cmd + Enter | macOS 本地发音（say），**Alfred 窗口保持打开** |
| Alt + Enter | 有道在线发音（美音/英音可配置），**Alfred 窗口保持打开** |
| Shift + Enter | 在浏览器打开有道网页 |
| 选中文字 + 热键 | 直接翻译选中内容 |
| `yd setkey` / `yd setsecret` | 保存凭据到数据目录（更新保留） |
| `yd config` / `yd reset` | 查看配置 / 清除凭据 |

> **防抖（debounce）**：Script Filter 内置 600ms 输入防抖
> （Run Behaviour → Queue Delay = 0.6s，自定义），停止输入 600ms 后才请求翻译 API，
> 避免连续打字时高频调用触发有道免费额度限制（errorCode 411）。
> 修改方式：双击 Script Filter 对象 → Run Behaviour 按钮 → Queue Delay。

### 防刷量守卫：签名记忆 · 链式合并 · 组词延迟 · 缓存限速 · 指数冷却（v1.3.0）

打字时频繁触发翻译、撞上有道 411「访问频率受限」的根因（经数据目录运行痕迹实证）：

1. **签名双倍请求**：`yd_sign=auto` 且应用只支持 v1 签名时，每次查询都先发一个
   注定 202 失败的 v3 请求再重试 v1——请求量翻倍，且两请求背靠背瞬时 2~3 QPS；
2. **逐词上屏链**：中文逐词上屏（`你`→`你在`→`你在干什么`）每个词都是"真实文本"，
   每次停顿 ≥0.6s 就各打一次 API，一句话 3~7 次调用；
3. **组词中间态**：裸拼音（`nihao`）、单音节（`da`）、已上屏+组词混合（`你好shijie`）
   被当成最终查询；英文长句的每个 ≥0.6s 停顿（想词、改错字）也各打一次。

六层防护，默认即安全值，全部可用环境变量调整：

| 层 | 解决的问题 | 行为 |
|---|---|---|
| 600ms 队列防抖 | 每次停顿就触发一次 | 停顿 0.6s 才运行脚本 |
| 签名回退记忆 | auto 模式下 v3 被拒后每次查询都双倍请求 | 首次 202→v1 回退成功后自动把 `yd_sign=v1` 写入数据目录，此后**每查询单请求**直达 |
| 链式合并 | 逐词上屏/退格编辑每次都调用 | 新查询与上一查询呈**前缀扩展/截断**关系且间隔 ≤3.5s → 显示"⌨️ 正在等待输入完成···"，**零调用**；停止输入 1s 后自动出结果。一句话只花 1 次调用 |
| 组词延迟 | 裸拼音/单音节/混合态被当最终查询 | 可切分为拼音音节（`da`/`nihao`）、可补全为拼音（`nih`/`shij`）或汉字+拼音尾（`你好shijie`）→ 延迟 1s 重跑；确要翻译这类词只慢 1s，**末尾加 `.` 立即翻译**（如 `nihao.`） |
| 结果缓存 + 限速 | 重复查询、突发连续调用 | 同查询+同目标语言 10 分钟内零调用（上限 200 条）；两次真实调用至少间隔 1s，60s 窗口内最多 30 次 |
| 411 指数冷却 | 已被限频后继续打 API | 收到 411 进入 60s 冷却；连续 411 逐次翻倍（120→240→480→960s 封顶），翻译成功后复位。冷却期所有查询**零调用** |

> 已知取舍：查询拼音形英文词（`he`/`she`/`me`/`can` 等）会先延迟 1s 再出结果；
> 英文长句中间隔 >3.5s 的长停顿仍会各调用一次（"想好了"与"没想完"信息上不可区分，
> 但签名记忆后单请求 + 1s 间隔不会再撞限）。`yd_pinyin_guard=0` 可关闭组词判定。

环境变量（工作流 [X] 面板配置，均有安全默认值）：

| 变量 | 说明 | 默认 |
|---|---|---|
| `yd_pinyin_guard` | 拼音组词中间态检测 | `1`（开） |
| `yd_min_len` | 非 CJK 查询最短长度（0 关闭） | `2` |
| `yd_min_interval` | 两次真实 API 调用最小间隔（秒） | `1.0` |
| `yd_rate_window` | 限速滑动窗口长度（秒） | `60` |
| `yd_max_per_window` | 窗口内最大调用次数 | `30` |
| `yd_cache_ttl` | 翻译结果缓存有效期（秒） | `600` |
| `yd_cooldown` | 411 冷却基准秒数（指数退避） | `60` |
| `yd_defer_delay` | 疑似"输入中"延后翻译的秒数（rerun） | `1.0` |
| `yd_chain_window` | 逐词上屏链式合并判定窗口（秒） | `3.5` |

### 中英混排长文本：目标语言判定与回显兜底（v1.4.0）

**症状**：粘贴一段英文错误日志（例如 `CC Switch local proxy failed … Provider: 公司; model: …`）
后，Alfred 里显示的"译文"与原文一模一样，看起来像没翻译。

**原因**：该文本只有 2 个汉字（`公司`）、却有 170+ 个英文字母。v1.3.0 的判定是
「只要含汉字 → 目标语言取 `yd_cn_to`（默认 `en`）」，于是请求变成 `from=auto&to=en`，
有道识别源语言同样是英文 → `l=<b>en2en</b>` → **把原文原样返回**（等价于没翻译）。

**v1.4.0 的两层修复**：

| 层 | 行为 |
|---|---|
| 目标语言判定（`detect.target_lang`） | 长文本（≥40 字符）且汉字占比 <5%（汉字/（汉字+拉丁字母））→ 判定为「拉丁文本为主」，翻译成 `yd_to`（默认中文）；短混排仍按原规则（`you are 大牛` → 英文） |
| 回显兜底（`yd.py` + `youdao.is_passthrough`） | 若 API 仍返回同语种对（`en2en`）或译文与原文逐字相同 → 自动换 `yd_to`/`yd_cn_to` 里的另一个目标语言**重试一次**；仍旧回显则显示可操作提示「未能翻译该文本（源语言与目标语言相同）」，不再把原文当译文 |

其他配套改进：

- 回显结果也会进缓存，重复查询**零调用**且稳定显示同一条提示（不重复浪费额度）
- 响应既无译文也无释义（如纯符号）时显示「未获取到翻译结果」，不再输出空 items 列表
- 有道文档确认**单次查询上限 5000 字符**（超出返回 `103 翻译文本过长`，已有中文提示）

### 中文片段保护：为什么 `公司` 会变成 `五星`（v1.5.0）

**症状**：同一句里的中文词被"重新翻译"成了无关的词，例如
`Provider: 公司` → 「提供方：**五星**」。

**原因**：这不是语言判定错误——有道返回的 `l` 明确是 `en2zh-CHS`（源语言英文识别正确）。
实测三种对照：

| 实验 | 结果 |
|---|---|
| `from=auto` 翻译整段 | 「提供方：**五星**」 |
| `from=en` 强制源语言英文 | 完全相同，仍是「**五星**」 |
| 只送 `Provider: 公司; model: x` 短片段 | 变成 `Provider: Company; model: x`（`l=zh-CHS2en`） |

即：**模型对"英文长句里嵌中文"的处理是上下文相关的失真**，靠请求参数无法修正。
但目标语言本来就是中文，`公司` 这段**根本不需要翻译**。

**v1.5.0 的做法：掩码 → 翻译 → 还原**（实测有道会原样保留占位符）：

```
发送：… /responses. Provider: [[C0]]; model: …
返回：… 提供者:[[C0]];模型:…
还原：… 提供者:公司;模型:…
```

生效条件（三条同时满足，避免误伤）：

1. 目标语言是中文（`yd_to`/`yd_cn_to` 取到 `zh-CHS`/`zh-CHT`）；
2. 文本为「拉丁主导」（≥40 字符且汉字占比 <5%，v1.4.0 的同一判定）；
3. 文本中确有汉字串。

因此：短混排 `Provider: 公司; model: x`（目标 en）仍照常翻成 `Company`；
`yd_to=ja/fr` 等非中文目标不掩码；纯中文、纯英文、日文、韩文行为完全不变。
占位符万一被模型吞掉（实测未发生），会自动退回未掩码请求保证不丢字，且沿用缓存。

> 代价：**不增加请求次数**（1 次调用即可，对比"按中文片段分段翻译"需 2~3 次）。
> 连字符/斜杠被加空格（`deepseek - v4.1 flash - 1017`）属模型对代码标识符的
> 固有行为，本插件不做自动"修复"（自动改空格有改错真实空格的风险）。


### 配置翻译选中文字的热键

工作流内置 Hotkey 触发器（默认未绑定，避免冲突）：

1. 双击工作流画布中的 **Hotkey** 对象
2. 点击 Record Hotkey 设置组合键（推荐 `⌥⌥` 双击 Alt，或 `⌘⇧D`）
3. **Argument 选择「Selection in macOS」**，使热键把选中文字传给翻译
4. 若选中文本无效：系统设置 → 隐私与安全性 → 辅助功能 → 勾选 Alfred

## 开发与测试

```bash
make test                # 运行全部单元测试（normalizer 规格表 / 签名 / 解析 / 拼音组词 / 防刷守卫 / 冒烟）
python3 workflow/yd.py "API"        # 终端直接调试（未配置 key 时给出提示）
yd_key=xxx yd_secret=yyy python3 workflow/yd.py "HTTPRequest"   # 带 key 调试
```

## 版本管理（无 package.json 的版本方案）

本项目没有 `package.json`，采用 Python/git 惯用的**单一事实来源**方案：

| 位置 | 作用 |
|---|---|
| `workflow/lib/__init__.py` 的 `__version__` | **唯一版本号**，改版本只改这一处 |
| `workflow/info.plist` 的 `<version>` | Alfred 工作流列表显示的版本，`make build` 自动同步 |
| git tag `v1.5.0` | 发布标记（相当于 npm 的 dist-tag） |
| `yd version` 命令 | Alfred 内随时查看版本 |
| `CHANGELOG.md` | 各版本更新日志（发布 Release 时可直接用作说明） |

```bash
make version          # 查看当前版本
make build            # 自动把 __version__ 同步进 info.plist 并打包

# 发布一个新版本
# 1. 修改 workflow/lib/__init__.py 的 __version__（如 1.1.0）
# 2. make build && make test
# 3. git add -A && git commit -m "release: v1.1.0"
# 4. git tag v1.1.0 && git push origin master v1.1.0
```

## 设计说明

- **normalizer** 是核心差异化模块，规则逐条被 `tests/test_normalizer.py` 锁定，防止回归
- 全大写缩写保留原样（实测 `NASA` 得到完整翻译，`API` 小写会误译为「蜜蜂」）
- `from=auto` 交由有道自动识别源语言，比参考项目强制指定更鲁棒
- **目标语言判定不再"见汉字就翻成英文"**：长文本按「汉字占比 <5% 即拉丁主导」判定，
  短混排保持原规则；并对 `en2en` 这类同语种回显自动换目标语言重试（详见上文 v1.4.0 小节）
- **中文片段保护**（`lib/protect.py`）：目标为中文且文本拉丁主导时，先把已有汉字串
  掩码为 `[[C0]]` 再翻译，译后还原——避免模型把 `公司` 这类无需翻译的词"译"成
  `五星`；占位符丢失时自动降级为未掩码请求（详见上文 v1.5.0 小节）
- **工作流执行流程在 Alfred 画布上完整可见**（与参考项目一致，四个动作均为独立节点，
  带彩色注记标签）：`Hotkey → Script Filter`，然后
  Enter → **复制到剪贴板 → 隐藏 Alfred**、Cmd → **本地发音**、
  Alt → **在线发音**（Open URL，TTS 音频地址）、Shift → **打开网页**（Open URL，有道词典页）。
  Script Filter 通过 JSON `mods` 把不同 arg 分发给对应节点，节点各司其职，无集中分发器
- 发音优先使用 API 返回的 `speakUrl`（美音）/ `tSpeakUrl`（英音），准确且免去本地下载
- 英文查询发音原词、中文查询发音英文译文；密钥通过 `variablesdontexport` 标记，
  导出/分享工作流时不带出

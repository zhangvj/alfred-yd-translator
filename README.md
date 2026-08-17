# YD Translator — 自定义有道翻译 Alfred 工作流

基于 [wensonsmith/YoudaoTranslator](https://github.com/wensonsmith/YoudaoTranslator) 的思路自定义实现，**重点修复参考项目对全大写、中划线、下划线单词翻译不准的问题**。

参考项目的核心缺陷（源码 `translator.ts`）：

```ts
const word = query.replace(/([A-Z])/g, ' $1').toLowerCase();
```

它会在**每个大写字母前强行插入空格**，导致：`API` → `a p i`、`USER_NAME` → `u s e r _ n a m e`、`HTTPRequest` → `h t t p request`，翻译结果全是乱码。

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
│   ├── info.plist            # 工作流定义（Script Filter / Hotkey / 配置界面）
│   ├── yd.py                 # Script Filter 入口
│   ├── yd_action.py          # 动作分发器（复制 / 本地发音 / 在线发音）
│   └── lib/
│       ├── normalizer.py     # ★ 智能文本规范化（核心）
│       ├── detect.py         # 语言检测（汉字/假名/谚文）
│       ├── youdao.py         # 有道 API 客户端（v3 签名）
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
| Shift + Enter | 有道网页预览 |
| 选中文字 + 热键 | 直接翻译选中内容 |
| `yd setkey` / `yd setsecret` | 保存凭据到数据目录（更新保留） |
| `yd config` / `yd reset` | 查看配置 / 清除凭据 |

### 配置翻译选中文字的热键

工作流内置 Hotkey 触发器（默认未绑定，避免冲突）：

1. 双击工作流画布中的 **Hotkey** 对象
2. 点击 Record Hotkey 设置组合键（推荐 `⌥⌥` 双击 Alt，或 `⌘⇧D`）
3. **Argument 选择「Selection in macOS」**，使热键把选中文字传给翻译
4. 若选中文本无效：系统设置 → 隐私与安全性 → 辅助功能 → 勾选 Alfred

## 开发与测试

```bash
make test                # 运行全部单元测试（normalizer 规格表 / 签名 / 解析 / 冒烟）
python3 workflow/yd.py "API"        # 终端直接调试（未配置 key 时给出提示）
yd_key=xxx yd_secret=yyy python3 workflow/yd.py "HTTPRequest"   # 带 key 调试
```

## 版本管理（无 package.json 的版本方案）

本项目没有 `package.json`，采用 Python/git 惯用的**单一事实来源**方案：

| 位置 | 作用 |
|---|---|
| `workflow/lib/__init__.py` 的 `__version__` | **唯一版本号**，改版本只改这一处 |
| `workflow/info.plist` 的 `<version>` | Alfred 工作流列表显示的版本，`make build` 自动同步 |
| git tag `v1.0.0` | 发布标记（相当于 npm 的 dist-tag） |
| `yd version` 命令 | Alfred 内随时查看版本 |

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
- 动作分发采用 **arg 前缀协议**（`speak:local:` / `speak:tts:` / 普通文本），
  Script Filter 只有一条下游连接，Enter/Cmd/Alt 通过 JSON `mods` 携带不同前缀的 arg
- 发音优先使用 API 返回的 `speakUrl`（美音）/ `tSpeakUrl`（英音），准确且免去本地下载
- 英文查询发音原词、中文查询发音英文译文；密钥通过 `variablesdontexport` 标记，
  导出/分享工作流时不带出

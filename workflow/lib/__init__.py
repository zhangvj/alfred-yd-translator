"""yd-translator 有道翻译 Alfred 工作流。"""

# 版本单一事实来源（代替 package.json 的 version 字段）：
#   1. 修改版本号只需改这里；
#   2. `make build` 会自动把该版本同步到 workflow/info.plist
#      （Alfred 的工作流列表会显示此版本）；
#   3. 发布时用 git tag v<版本号> 标记（如 v1.0.0）；
#   4. 在 Alfred 中输入 `yd version` 可随时查看。
__version__ = "1.0.0"

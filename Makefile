# yd-translator — 有道翻译 Alfred 5 工作流
# 用法: make test / make build / make install / make clean
#
# 版本管理（无 package.json，单一事实来源）:
#   workflow/lib/__init__.py 的 __version__ 是唯一版本号；
#   `make build` 自动把该版本同步到 workflow/info.plist（Alfred 显示）。
#   发布时: git tag v$(VERSION) && git push origin v$(VERSION)

WORKFLOW_NAME := yd-translator
WORKFLOW_DIR  := workflow
BUNDLE        := $(WORKFLOW_NAME).alfredworkflow

# 从单一事实来源读取版本号
VERSION := $(shell python3 -c "from workflow.lib import __version__; print(__version__)")

.PHONY: test build install clean version

version:
	@echo "yd-translator v$(VERSION)"

test:
	python3 -m unittest discover -s tests -v

build:
	@plutil -lint $(WORKFLOW_DIR)/info.plist
	@echo "==> 同步版本 v$(VERSION) 到 info.plist"
	@/usr/libexec/PlistBuddy -c "Set :version $(VERSION)" $(WORKFLOW_DIR)/info.plist
	@echo "==> 打包 $(BUNDLE)"
	@cd $(WORKFLOW_DIR) && find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null; \
	zip -r ../$(BUNDLE) . -x '*.pyc' '*__pycache__*'
	@echo "==> 完成: $(BUNDLE) (v$(VERSION))"

install: build
	open $(BUNDLE)

clean:
	rm -f $(BUNDLE)
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

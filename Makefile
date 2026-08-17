# yd-translator — 有道翻译 Alfred 5 工作流
# 用法: make test / make build / make install / make clean

WORKFLOW_NAME := yd-translator
WORKFLOW_DIR  := workflow
BUNDLE        := $(WORKFLOW_NAME).alfredworkflow

.PHONY: test build install clean

test:
	python3 -m unittest discover -s tests -v

build:
	@plutil -lint $(WORKFLOW_DIR)/info.plist
	@echo "==> 打包 $(BUNDLE)"
	@cd $(WORKFLOW_DIR) && find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null; \
	zip -r ../$(BUNDLE) . -x '*.pyc' '*__pycache__*'
	@echo "==> 完成: $(BUNDLE)"

install: build
	open $(BUNDLE)

clean:
	rm -f $(BUNDLE)
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

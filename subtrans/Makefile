# SubTrans 2.0 Makefile

.PHONY: help install dev-install test lint format clean build release

# 默认目标
help:
	@echo "SubTrans 2.0 构建命令:"
	@echo "  install      - 安装项目"
	@echo "  dev-install  - 开发模式安装"
	@echo "  test         - 运行测试"
	@echo "  lint         - 代码检查"
	@echo "  format       - 代码格式化"
	@echo "  clean        - 清理构建文件"
	@echo "  build        - 构建包"
	@echo "  release      - 发布版本"

# 安装项目
install:
	pip install -e .

# 开发模式安装
dev-install:
	pip install -e ".[dev,test]"
	pip install -r requirements.txt

# 运行测试
test:
	python -m pytest tests/ -v --cov=core --cov=utils --cov-report=html

# 代码检查
lint:
	flake8 core/ utils/ main.py
	mypy core/ utils/ main.py

# 代码格式化
format:
	black core/ utils/ main.py tests/
	isort core/ utils/ main.py tests/

# 清理构建文件
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

# 构建包
build: clean
	python -m build
	twine check dist/*

# 发布版本
release: build
	./release.sh

# 安装构建依赖
install-build-deps:
	pip install --upgrade setuptools wheel build twine
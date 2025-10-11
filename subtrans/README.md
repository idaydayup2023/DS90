# SubTrans - 字幕翻译管理工具

SubTrans是DS90项目的字幕处理模块，提供智能字幕翻译、格式转换和同步功能。

## 🎯 功能特性

### 🌐 多语言翻译
- 支持多种翻译API (Google, DeepL, 百度等)
- 批量字幕文件翻译
- 保持原始时间轴和格式
- 智能语言检测

### 📝 格式转换
- 支持主流字幕格式: SRT, ASS, SSA, VTT, SUB
- 批量格式转换
- 编码自动检测和转换
- 样式保持和优化

### 🎯 字幕同步
- 自动时间轴校准
- 手动微调功能
- 多轨字幕合并
- 字幕质量检测

### 🤖 AI辅助
- 智能断句优化
- 术语一致性检查
- 翻译质量评估
- 自动校对功能

## 🚀 快速开始

### 环境要求
- Python 3.7+
- 支持的翻译API密钥 (可选)

### 安装
```bash
cd subtrans
pip install -r requirements.txt
```

### 基本使用
```bash
# 翻译单个字幕文件
python main.py translate --input movie.srt --output movie_cn.srt --target zh

# 批量翻译
python main.py batch --input-dir ./subs --output-dir ./subs_cn --target zh

# 格式转换
python main.py convert --input movie.ass --output movie.srt --format srt

# 字幕同步
python main.py sync --input movie.srt --reference audio.wav --output synced.srt
```

## 📁 项目结构

```
subtrans/
├── main.py                 # 主程序入口
├── config/                 # 配置文件
│   ├── config.yaml        # 主配置
│   └── translators.yaml   # 翻译器配置
├── src/                   # 源代码
│   ├── translators/       # 翻译器模块
│   ├── converters/        # 格式转换器
│   ├── sync/             # 同步工具
│   └── utils/            # 工具函数
├── tests/                # 测试文件
├── docs/                 # 文档
└── requirements.txt      # 依赖包
```

## ⚙️ 配置说明

### 翻译器配置
```yaml
# config/translators.yaml
translators:
  google:
    enabled: true
    api_key: "your_api_key"
    endpoint: "https://translation.googleapis.com/language/translate/v2"
  
  deepl:
    enabled: false
    api_key: "your_deepl_key"
    endpoint: "https://api-free.deepl.com/v2/translate"
  
  baidu:
    enabled: false
    app_id: "your_app_id"
    secret_key: "your_secret_key"
```

### 主配置
```yaml
# config/config.yaml
general:
  default_source_lang: "auto"
  default_target_lang: "zh"
  max_concurrent: 5
  
output:
  preserve_formatting: true
  add_source_track: false
  encoding: "utf-8"
  
sync:
  tolerance: 0.5  # 秒
  auto_adjust: true
```

## 🔧 开发状态

| 功能模块 | 状态 | 描述 |
|---------|------|------|
| 基础翻译 | 🚧 开发中 | Google翻译API集成 |
| 格式转换 | 📋 规划中 | SRT/ASS/VTT转换 |
| 字幕同步 | 📋 规划中 | 音频同步功能 |
| Web界面 | 📋 规划中 | 可视化操作界面 |

## 📖 详细文档

- [API文档](./docs/API.md)
- [配置指南](./docs/CONFIG.md)
- [开发指南](./docs/DEVELOPMENT.md)
- [故障排除](./docs/TROUBLESHOOTING.md)

## 🤝 贡献

欢迎提交Issue和Pull Request！

## 📄 许可证

MIT License - 详见根目录LICENSE文件

---

**注意**: 此模块目前处于开发阶段，功能尚未完整实现。
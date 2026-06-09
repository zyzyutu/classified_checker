# 涉密信息综合检查系统

## 项目简介
基于 Python + tkinter 开发的本地涉密信息综合检查工具，支持网页、数据库、文件、图片四大模块的涉密关键词自动检查，并生成 Markdown 报告。

## 功能特性

### 网页检查
- BFS 全站遍历，可配置爬取深度（0~10）
- 多线程并行爬取（可配置 1~16 线程）
- 增量检测：利用 ETag / Last-Modified / 内容 MD5 哈希跳过未变化的页面
- 缓存涉密标记，增量模式下涉密页面仍会在报告中展示

### 数据库检查
- GUI 界面输入数据库连接信息（地址/用户名/密码）
- 支持检查全部数据库或指定单个数据库
- 多库并行检查（ThreadPoolExecutor）
- REGEXP 粗筛 + Python 正则精确匹配
- 自动检测表主键作为记录标识
- 跳过数值字段，同行关键词去重合并

### 文件检查
- 支持 TXT、DOC、DOCX、XLS、XLSX、PPT、PPTX、PDF
- 支持 ZIP、RAR、7Z 压缩包递归解压检查（最大嵌套 3 层）
- Magic Number 文件头校验真实类型
- 加密文件识别（Office/ZIP/RAR/7Z/PDF 多层检测）
- 隐藏文件检测、损坏文件诊断
- COM 应用实例缓存，RLock 可重入锁保证线程安全
- 多线程并行检查

### 图片检查
- 本地 OCR（RapidOCR），支持 GPU 加速（DirectML/CUDA）
- 多线程并行 OCR
- 文字位置检测（上部/中部/下部）
- OCR 结果缓存，置信度过滤（阈值 0.7）

### 报告输出
- 自动生成 Markdown 格式报告
- 路径固定 40 列宽度截断，关键词截断显示
- 长文本截取关键词周围上下文

### 界面
- 深色主题 GUI，可配置各项参数
- 数据库连接信息界面输入，密码隐藏显示
- 支持立即停止、断点续查

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 运行
python main.py
```

## 依赖库
| 库 | 用途 |
|---|------|
| requests | HTTP 请求 |
| beautifulsoup4 | HTML 解析 |
| pymysql | MySQL 连接 |
| python-docx | DOCX 读取 |
| openpyxl | XLSX 读取 |
| python-pptx | PPTX 读取 |
| PyPDF2 / pdfplumber | PDF 读取 |
| xlrd | XLS 读取 |
| pywin32 | WPS/Word COM 接口 |
| rapidocr-onnxruntime | OCR 识别 |
| rarfile | RAR 解压 |
| py7zr | 7Z 解压 |

## 开发环境
- Python 3.11
- Windows 11

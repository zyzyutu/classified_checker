# 涉密信息综合检查系统

## 项目简介
基于 Python + tkinter 开发的本地涉密信息综合检查工具，支持网页、数据库、文件、图片四大模块的涉密关键词自动检查，并生成 Markdown 报告。

## 功能特性

### 网页检查
- BFS 全站遍历，可配置爬取深度（0~10）
- 多线程并行爬取（可配置 1~16 线程）
- 增量检测：利用 ETag / Last-Modified / 内容 MD5 哈希跳过未变化的页面

### 数据库检查
- 直连 MySQL 数据库，遍历所有表、字段、记录
- 逐表统计（记录数、涉密数、字段数）

### 文件检查
- 支持 TXT、DOC、DOCX、XLS、XLSX、PPT、PPTX、PDF
- 支持 ZIP、RAR、7Z 压缩包递归解压检查（最大嵌套 3 层）
- Magic Number 文件头校验真实类型
- 加密文件识别、隐藏文件检测
- 多线程并行检查

### 图片检查
- 本地 OCR（RapidOCR / pytesseract），不依赖远程 API
- 支持 PNG、JPG、BMP、TIFF、GIF

### 报告输出
- 自动生成 Markdown 格式报告
- 包含汇总统计、各模块详情、涉密精确定位

### 界面
- 深色主题 GUI，可配置各项参数
- 支持立即停止、断点续查
- 检查结果自动保存，支持历史查看

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

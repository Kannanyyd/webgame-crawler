# Webgame Crawler

Webgame Crawler 是一个面向 HTML5 网页游戏的资源发现与下载工具。输入一个能够正常打开并进入游戏界面的链接，工具会通过真实浏览器观察页面结构和网络请求，识别实际游戏运行上下文，并保存进入初始可玩界面所需的静态资源。

## 功能

- 自动分析页面、iframe 和 Canvas，定位真实游戏入口。
- 根据浏览器请求关系筛选游戏资源，减少广告、统计和平台页面资源干扰。
- 支持跨域 CDN、查询参数、Cookie、Referer 和常用鉴权请求头。
- 保存 Brotli、Gzip 等原始压缩内容，并校验响应状态和文件长度。
- 从脚本及资源清单中补充浏览器尚未立即加载的资源。
- 支持 Unity WebGL、Construct、Cocos Creator、LayaAir 和通用 HTML5 资源格式。
- 输出资源映射、汇总信息和失败记录，便于审计与后续处理。

## 环境要求

- Python 3.11 或更高版本
- Playwright Chromium

安装依赖：

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

## 使用方法

```powershell
python game_grabber.py "https://example.com/game"
```

也可以直接运行脚本，然后按提示输入 URL。

下载结果保存在以页面标题命名的目录中：

```text
<game-name>/
  ...下载的资源...
  _external/<host>/...
  _crawl/resource-map.json
  _crawl/summary.json
  _crawl/failures.json
```

其中：

- `resource-map.json` 记录原始 URL 与本地文件路径的映射。
- `summary.json` 记录游戏上下文、资源数量及传输体积。
- `failures.json` 记录下载失败的资源和原因。

程序会区分浏览器实际请求的核心资源和从清单推导出的可选资源。只有核心资源下载失败时，命令才会返回失败状态。

## 测试

自动化测试不依赖外部网站：

```powershell
py -3.12 -m unittest discover -s tests -v
```

测试覆盖游戏上下文选择、跨域资源、查询参数、浏览器会话、分段响应、压缩内容、失败重试和常见引擎资源格式。

## 使用限制

- 工具不会绕过登录、验证码、付费、DRM 或其他访问控制。
- 只有在交互后才动态加载、且未在任何清单中声明的资源，需要额外设计交互流程才能发现。
- 联机、排行榜、支付等服务端功能仍依赖原始后台。
- 下载资源不等同于自动生成可离线运行的完整游戏；离线运行通常还需要 URL 重写和平台接口适配。
- 请确保对目标内容拥有必要授权，并遵守适用的用户协议和法律法规。

# Webgame Crawler

输入一个能够正常打开并进入游戏界面的网页链接，脚本会通过真实浏览器观察 frame、canvas、请求发起关系和资源流量，识别实际游戏上下文，并保存初始可玩界面所需的静态资源。

## 核心原则

- 不按平台域名写死规则。
- 不把第一个 iframe 当成游戏。
- 不要求资源和游戏页面属于同一个根域。
- 完整保留查询参数、Cookie、Referer、Authorization 等请求上下文。
- 支持 HTTP 200、完整 206、Brotli/Gzip 原始压缩资源。
- 浏览器网络捕获为主，引擎清单解析用于补充未立即加载的资源。

首批覆盖 Unity WebGL、Construct、Cocos Creator、LayaAir 和通用 HTML5 游戏。

## 安装

建议使用 Python 3.11 或更高版本：

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

## 使用

```powershell
python game_grabber.py "https://example.com/game"
```

也可以直接运行脚本后交互式输入 URL。

输出目录使用页面标题命名：

```text
<game-name>/
  ...下载的资源...
  _external/<host>/...
  _crawl/resource-map.json
  _crawl/summary.json
  _crawl/failures.json
```

`summary.json` 会分别记录：

- 浏览器捕获请求数；
- 选中的游戏 frame、引擎和置信分；
- 纳入、排除、成功及失败资源数；
- 实际保存的压缩字节；
- 服务器声明的已知解压字节。

因此 Unity `.br` 游戏不会再把约 28MB 的压缩传输量和约 70MB 的解压资源量混为一谈。

## 测试

确定性测试不访问外网：

```powershell
py -3.12 -m unittest discover -s tests -v
```

测试覆盖广告 iframe 误判、跨域 CDN、签名查询参数、Cookie、206、压缩字节、Unity、Construct、Cocos、Laya 和通用 HTML5 资源格式。

## 限制

- 工具不会绕过登录、验证码、付费、DRM 或访问控制。
- 初始界面没有请求且清单没有声明的后续关卡资源无法凭空发现。
- 多人联机、排行榜、支付等服务端功能仍需要原始后台。
- 请遵守目标站点的用户协议、授权范围和相关法律。

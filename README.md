# Webgame Crawler

网页游戏资源抓取工具。输入游戏页面 URL,自动抓取所有游戏资源到本地,保持原目录结构,游戏可直接本地运行。

## 工作原理

```
1. 启动 headless 浏览器加载游戏页面
2. 拦截所有网络请求,收集返回 200 的资源 URL 和 referer
3. 自动点击 canvas 触发动态资源加载
4. 识别游戏引擎,按引擎特征补抓资源
5. 从 HTML <title> 或 URL 推断游戏名,创建同名目录
6. 用拦截到的 referer 批量下载所有资源
7. 保持原目录结构,游戏本地可直接运行
```

## 支持的游戏引擎

| 引擎 | 资源补抓策略 |
|------|------|
| Cocos Creator | 解析 `src/settings.js` + 各 bundle 的 `config.json` |
| Egret | 解析 `resource/default.res.json` |
| Unity WebGL | 解析 `index.html` 的 `createUnityInstance` config 对象 |
| Construct 3 | JS 字符串扫描兜底(`c3runtime.js` 特征识别) |
| Phaser / PixiJS / Three.js / Babylon.js | JS 字符串扫描兜底 |
| CreateJS / Laya / Hilo / PlayCanvas | JS 字符串扫描兜底 |
| 纯 HTML5 + Canvas | JS 字符串扫描兜底 |

**兜底策略**:对所有引擎,扫描拦截到的 JS 文件,正则提取 `.png/.mp3/.json/.wasm` 等资源路径。即使 JS 被混淆,字符串数组本身是明文,能提取出资源路径。

## 平台兼容性

| 平台 | 兼容性 | 说明 |
|------|------|------|
| 多数主流平台 | ✅ 完全兼容 | 资源抓取完整,本地可零失败运行 |
| Yandex Games | ✅ 完全兼容 | 支持 Unity WebGL brotli 压缩资源 |
| Poki | ✅ 完全兼容 | 自动点击 Play 按钮,跨子域资源白名单 |
| GameDistribution | ✅ 完全兼容 | Construct 3 引擎识别 + 资源完整抓取 |
| itch.io | ⚠️ 受限 | 平台对 headless 浏览器有反爬,游戏按钮不渲染,需真实浏览器环境 |
| Newgrounds | ⚠️ 受限 | 有 `_guard` 反爬验证 + headless 检测,部分游戏无法抓取 |

## 安装

```bash
git clone https://github.com/Kannanyyd/webgame-crawler.git
cd webgame-crawler
pip install -r requirements.txt
playwright install chromium   # 首次运行也可由工具自动安装
```

## 使用

```bash
# 命令行参数
python game_grabber.py <游戏页面 URL>

# 或交互式输入
python game_grabber.py
```

运行后会在当前目录下创建以游戏名命名的目录,所有资源都保存在里面。

## 本地运行抓下来的游戏

```bash
cd "<游戏名>"
python -m http.server 8080
# 浏览器打开工具输出的 URL(如 http://localhost:8080/<game>/index.html)
```

## 已知问题

- 部分平台子域有 Cloudflare 防护,直接访问 headless 浏览器会被拦截;从平台主站入口加载可绕过
- CDN 资源带 Referer 防盗链,工具会自动用拦截到的 referer 注入请求头
- 部分平台的 gameframe 是外壳,真实游戏在另一域名/子域的 iframe 里,工具会自动识别真实游戏 frame

## 目录结构

```
webgame-crawler/
├── game_grabber.py      # 主程序
├── requirements.txt
├── README.md
└── .gitignore
```

抓取后的资源结构示例:

```
<游戏名>/
└── <game-slug>/
    └── <version>/
        ├── index.html
        └── assets/
            ├── bundle-a/
            ├── bundle-b/
            └── ...
```

## 注意事项

本工具仅供学习与个人使用,抓取的资源请遵守目标平台的用户协议与版权规定。使用者需自行承担相关法律责任。

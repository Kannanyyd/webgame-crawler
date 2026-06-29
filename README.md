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
| Unity WebGL | UnityLoader 启动时浏览器拦截覆盖 |
| Phaser / PixiJS / Three.js / Babylon.js | JS 字符串扫描兜底 |
| CreateJS / Laya / Hilo / PlayCanvas | JS 字符串扫描兜底 |
| 纯 HTML5 + Canvas | JS 字符串扫描兜底 |

**兜底策略**:对所有引擎,扫描拦截到的 JS 文件,正则提取 `.png/.mp3/.json/.wasm` 等资源路径。即使 JS 被混淆,字符串数组本身是明文,能提取出资源路径。

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
python game_grabber.py https://www.crazygames.com/game/find-the-cow-lqn

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

## 已测试的游戏

| 游戏 | 平台 | 引擎 | 资源数 | 本地运行 |
|------|------|------|------|------|
| Find The Cow | CrazyGames | Cocos Creator | 126 | ✅ 130 请求全 200 |
| Arrow Escape: Puzzle | CrazyGames | HTML5 + Canvas | 6 | ✅ 15 请求全 200 |

## 已知问题

- CrazyGames 部分子域有 Cloudflare 防护,直接访问会被拦截;从主站入口 `https://www.crazygames.com/game/<slug>` 加载可绕过
- CDN 资源带 Referer 防盗链,工具会自动用拦截到的 referer 注入请求头
- CrazyGames 的 `games.crazygames.com` 是 gameframe 外壳,真实游戏在 `*.game-files.crazygames.com` 的 iframe 里,工具会自动识别真实游戏 frame

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
Find the cow/
└── find-the-cow-lqn/
    └── 22/
        ├── index.html
        └── assets/
            ├── cowGame/
            ├── lobby/
            ├── resources/
            ├── internal/
            └── main/
```

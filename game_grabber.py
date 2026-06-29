"""
网页游戏资源抓取工具
用法:
    python game_grabber.py <游戏页面 URL>
    python game_grabber.py                    # 交互式输入

示例:
    python game_grabber.py https://example.com/game/your-game-slug
    python game_grabber.py https://cdn.example.com/your-game/1/index.html

工作流程:
1. 启动 headless 浏览器加载游戏页面
2. 拦截所有网络请求,收集返回 200 的资源 URL
3. 自动点击 canvas 触发动态资源加载
4. 识别游戏引擎,按引擎特征补抓资源:
   - Cocos Creator:解析 src/settings.js + 各 bundle 的 config.json
   - Egret:解析 resource/default.res.json
   - 其他引擎:扫描 JS 字符串里的资源路径补漏
5. 从 HTML <title> 或 URL 推断游戏名,创建同名目录
6. 用浏览器拦截到的 referer 批量下载所有资源
7. 保持原目录结构,游戏本地可直接运行

支持的游戏引擎:
- Cocos Creator(bundle 系统 + config.json)
- Egret(default.res.json 资源组)
- Unity WebGL(Build/xxx.json 清单)
- Phaser / PixiJS / Three.js / Babylon.js(JS 硬编码,用浏览器拦截 + JS 字符串扫描)
- 纯 HTML5 + Canvas(同上)
"""
import os
import re
import sys
import json
import time
import shutil
import requests
from urllib.parse import urlparse, unquote, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Playwright 浏览器路径(项目本地,首次运行自动下载)
PW_BROWSERS_PATH = str(Path(__file__).parent / ".pw-browsers")
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = PW_BROWSERS_PATH


def ensure_browser():
    """确保 Playwright 浏览器已安装"""
    pw_dir = Path(PW_BROWSERS_PATH)
    if not pw_dir.exists() or not list(pw_dir.glob("chromium-*")):
        print("首次运行,正在安装 Playwright 浏览器(约 300 MB)...")
        import subprocess
        env = os.environ.copy()
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            env=env, check=True
        )


def root_domain(host):
    """提取根域(简化版,处理常见多段 TLD)。
    用于跨子域白名单过滤 —— 比如游戏 frame 在 games.poki.com,
    但真实资源在 xxx.gdn.poki.com,两者根域都是 poki.com,应一并保留。
    """
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    # 常见多段 TLD(国家二级 + 通用 TLD)
    multi_tld = ("co.uk", "co.jp", "com.cn", "com.au", "co.kr",
                 "com.br", "com.tw", "co.in", "com.sg")
    last_two = ".".join(parts[-2:])
    if last_two in multi_tld and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_website_ui_path(url):
    """判断是否为明显的网站 UI 打包路径(非游戏资源)。
    比如网站外壳的 React/Vue 打包 chunk、CDN 图片处理接口。
    """
    ui_patterns = (
        "/assets/client~",      # 网站应用代码 chunk
        "/cdn-cgi/image/",       # Cloudflare 图片处理
        "/_next/static/",        # Next.js 网站静态资源
        "/_next/data/",         # Next.js 数据路由
        "/static/assets/",       # 通用网站打包
        "/assets/client~app",   # 网站应用组件
        "/aboutpage/",           # 平台 about 页资源
        "/playlists/",           # 播放列表 UI
        "/icons/",               # 网站 UI 图标(评分星、播放叠加层等)
    )
    return any(p in url for p in ui_patterns)


def is_api_endpoint(url):
    """判断是否为 API/追踪/分析端点(非资源文件,下载必失败)。"""
    api_patterns = (
        "/graphql", "/api/", "/_guard/", "/collect",
        "/analytics", "/tracking", "/telemetry",
        "/sdk.js",                   # 平台 SDK 脚本(Yandex/Poki 等)
        "/realtime", "/leaderboard", "/payments",
    )
    # 网站分析域名
    api_domains = (
        "gd-website-api.", "msgrt.", "tag.atom.",
        "hlana.", "counter.", "pixel.",
    )
    return any(p in url.lower() for p in api_patterns) or \
           any(d in url.lower() for d in api_domains)


def slugify(name):
    """把游戏名转成安全的目录名"""
    # 去掉 emoji 和非基本字符
    name = name.encode("ascii", "ignore").decode("ascii")
    # 去掉 "play on <平台>" 这类网站后缀(通用,不硬编码平台名)
    name = re.sub(r'\s*play\s+on\s+\w+.*$', '', name, flags=re.IGNORECASE)
    # 去掉 "play free online games" 这类宣传语
    name = re.sub(r'\s*[-|]?\s*play\s+free\s+online\s+games.*$', '', name, flags=re.IGNORECASE)
    # 去掉 " | <平台>" 这类带分隔符的后缀
    for sep in ["|", "-", "–", "—", "::"]:
        if sep in name:
            name = name.split(sep)[0].strip()
    # 替换非法字符
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "game"


def get_game_name(page, url):
    """从页面 title 或 URL 推断游戏名"""
    # 1. 优先 HTML title
    try:
        title = page.title()
        if title and title.strip():
            return slugify(title)
    except Exception:
        pass

    # 2. 从 URL 路径推断
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split("/") if p]
    if path_parts:
        # 取最后一个有意义的段
        for part in reversed(path_parts):
            if part not in ("game", "games", "play", "index.html"):
                return slugify(part.replace(".html", ""))

    return "game"


def detect_engine(page, game_frame):
    """
    识别游戏引擎类型。
    通过全局对象、script 引用、DOM 特征判断。
    返回引擎名字符串(小写): cocos / egret / unity / phaser / pixi /
    three / babylon / createjs / laya / hilo / playcanvas / html5 / unknown
    """
    # 全局对象特征(优先级最高)
    checks = [
        ("cc",            "cocos"),      # Cocos Creator
        ("CocosEngine",   "cocos"),
        ("egret",         "egret"),      # Egret
        ("UnityLoader",   "unity"),      # Unity WebGL
        ("Phaser",        "phaser"),
        ("PIXI",          "pixi"),       # PixiJS
        ("THREE",         "three"),      # Three.js
        ("BABYLON",       "babylon"),    # Babylon.js
        ("createjs",      "createjs"),
        ("Laya",          "laya"),
        ("Hilo",          "hilo"),
        ("PC_Application","playcanvas"), # PlayCanvas
    ]
    try:
        target = game_frame if game_frame else page
        for var, name in checks:
            try:
                found = target.evaluate(f"!!window.{var}")
                if found:
                    return name
            except Exception:
                continue
    except Exception:
        pass

    # DOM / script 引用特征
    try:
        target = game_frame if game_frame else page
        # Cocos Creator: 通常有 cc-settings 或 application.js
        if target.query_selector("script[src*='application.js']") or \
           target.query_selector("script[src*='cocos2d']"):
            return "cocos"
        # Egret: 通常有 egret.min.js
        if target.query_selector("script[src*='egret']"):
            return "egret"
        # Unity: 通常有 UnityLoader.js
        if target.query_selector("script[src*='UnityLoader']") or \
           target.query_selector("canvas[id*='unity']"):
            return "unity"
        # Construct 3: c3runtime.js / c3main.js
        if target.query_selector("script[src*='c3runtime']") or \
           target.query_selector("script[src*='c3main']") or \
           target.query_selector("script[src*='preview.js']"):
            return "construct"
    except Exception:
        pass

    # 默认:有 canvas 但没有上面任何特征 → 纯 HTML5
    try:
        target = game_frame if game_frame else page
        if target.query_selector("canvas"):
            return "html5"
    except Exception:
        pass

    return "unknown"


def scan_js_strings(js_urls, base_url, referer, captured):
    """
    通用兜底:扫描所有 JS 文件内容,正则提取资源路径。
    适用于纯 HTML5/Phaser/PixiJS/Three.js 等无清单引擎。
    即使 JS 被混淆,字符串数组本身是明文,能提取 .png/.mp3/.json 等路径。
    返回新发现的 URL -> referer 字典。
    """
    new_urls = {}
    # 资源后缀白名单(只抓游戏资源,不抓 .js/.css)
    ext_re = re.compile(
        r'["\']([^"\']+\.(?:png|jpg|jpeg|webp|gif|svg|mp3|wav|ogg|m4a|'
        r'json|wasm|data|glb|gltf|atlas|xml|fnt|ttf|woff2?|plist|bin))["\']'
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Referer": referer,
    }
    for js_url in js_urls:
        try:
            r = requests.get(js_url, headers=headers, timeout=30)
            if r.status_code != 200:
                continue
            content = r.text
            for m in ext_re.finditer(content):
                path = m.group(1)
                # 跳过明显非资源的(如 https://example.com 之类)
                if path.startswith("data:") or path.startswith("blob:"):
                    continue
                if path.startswith("http://") or path.startswith("https://"):
                    if path not in captured and path not in new_urls:
                        new_urls[path] = referer
                else:
                    # 相对路径 → 拼成绝对 URL
                    full = urljoin(base_url + "/", path.lstrip("./"))
                    # 只保留同域资源
                    if urlparse(full).netloc == urlparse(base_url).netloc:
                        if full not in captured and full not in new_urls:
                            new_urls[full] = referer
        except Exception:
            continue
    return new_urls


def parse_cocos_manifest(game_frame_url, referer, captured):
    """
    Cocos Creator 专属:解析 src/settings.js 拿到所有 bundle 名和版本,
    然后访问每个 bundle 的 config.json 拿到资源列表。
    返回新发现的 URL -> referer 字典。
    """
    new_urls = {}
    base = game_frame_url.rsplit("/", 1)[0]  # 去掉 index.html
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Referer": referer,
    }

    # 1. 拉 settings.js
    settings_url = f"{base}/src/settings.js"
    try:
        r = requests.get(settings_url, headers=headers, timeout=30)
        if r.status_code != 200:
            return new_urls
        text = r.text
        # settings.js 里 bundleVers 形如: bundleVers:{internal:"abc",main:"def",...}
        m = re.search(r'bundleVers\s*[:=]\s*\{([^}]+)\}', text)
        if not m:
            return new_urls
        # 提取 bundle 名 -> 版本
        bundles = {}
        for pair in re.finditer(r'["\']?([\w\-]+)["\']?\s*:\s*["\']([\w\-]+)["\']', m.group(1)):
            bundles[pair.group(1)] = pair.group(2)
        new_urls[settings_url] = referer
        # settings.js 本身也要下载
        # 2. 每个 bundle 的 config.json
        for name, ver in bundles.items():
            # 路径:<base>/<bundle>/config.<ver>.json 或 <base>/assets/<bundle>/config.json
            candidates = [
                f"{base}/{name}/config.{ver}.json",
                f"{base}/assets/{name}/config.{ver}.json",
                f"{base}/{name}/config.json",
                f"{base}/assets/{name}/config.json",
            ]
            for cfg_url in candidates:
                if cfg_url in captured or cfg_url in new_urls:
                    continue
                try:
                    r2 = requests.get(cfg_url, headers=headers, timeout=20)
                    if r2.status_code != 200:
                        continue
                    new_urls[cfg_url] = referer
                    # 解析 config.json,提取 paths 里的资源
                    try:
                        cfg = r2.json()
                        # Cocos config.json 结构:{ paths: {uuid: ["xxx.png", 0]}, types: [...] }
                        paths = cfg.get("paths", {})
                        types = cfg.get("types", [])
                        base_url_for_paths = cfg_url.rsplit("/", 1)[0]
                        for uuid, entry in paths.items():
                            if isinstance(entry, list) and entry:
                                fname = entry[0]
                                # 资源 URL 形式: <bundle>/native/<ver>/<uuid>.<ext>
                                # 或 <bundle>/import/<ver>/<uuid>.json
                                t = entry[1] if len(entry) > 1 else 0
                                ext = types[t] if t < len(types) else ""
                                # 列两种可能路径,稍后下载时按需重试
                                for sub in ("native", "import"):
                                    if ext and ext != "json":
                                        u = f"{base_url_for_paths}/{sub}/{ver}/{uuid}.{ext}"
                                    else:
                                        u = f"{base_url_for_paths}/{sub}/{ver}/{uuid}.json"
                                    if u not in captured and u not in new_urls:
                                        new_urls[u] = referer
                    except Exception:
                        pass
                    break  # 找到一个有效的 config.json 就跳出
                except Exception:
                    continue
    except Exception:
        pass
    return new_urls


def parse_unity_index(game_frame_url, referer, captured):
    """
    Unity WebGL 专属:解析 index.html 里的 createUnityInstance config 对象,
    拿到 dataUrl/frameworkUrl/codeUrl 等资源路径。
    Unity 加载 wasm 时用流式 fetch,URL 可能被浏览器拦截器截断,
    所以必须直接解析 index.html 的 config 对象。
    返回新发现的 URL -> referer 字典。
    """
    new_urls = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Referer": referer,
    }
    try:
        r = requests.get(game_frame_url, headers=headers, timeout=30)
        if r.status_code != 200:
            return new_urls
        html = r.text
        base = game_frame_url.rsplit("/", 1)[0]
        # 匹配 config = { ... } 对象
        m = re.search(r'config\s*=\s*\{([^}]+)\}', html)
        if not m:
            return new_urls
        config_body = m.group(1)
        # 提取所有 "xxxUrl": "path" 或 xxxUrl: "path" 键值对
        for kv in re.finditer(r'(\w*Url)\s*:\s*["\']([^"\']+)["\']', config_body):
            rel_path = kv.group(2)
            # 拼成绝对 URL(相对 game_frame_url)
            full = urljoin(game_frame_url + "/", rel_path)
            if full not in captured and full not in new_urls:
                new_urls[full] = referer
        # 也提取 loaderUrl(UnityLoader 加载器)
        for kv in re.finditer(r'(loaderUrl|buildUrl)\s*[:=]\s*["\']([^"\']+)["\']', html):
            rel_path = kv.group(2)
            if rel_path not in ("Build", "buildUrl"):
                full = urljoin(game_frame_url + "/", rel_path)
                if full not in captured and full not in new_urls:
                    new_urls[full] = referer
        # streamingAssetsUrl 也可能指向资源目录
        for kv in re.finditer(r'(streamingAssetsUrl)\s*:\s*["\']([^"\']+)["\']', html):
            # 这是目录路径,不直接下载,留给浏览器拦截
            pass
    except Exception:
        pass
    return new_urls


def collect_game_resources(url):
    """启动浏览器加载游戏,拦截所有资源请求"""
    from playwright.sync_api import sync_playwright

    captured = {}  # url -> referer(用拦截到的 referer)
    game_frame_url = ""  # 游戏所在 frame 的 URL

    print(f"\n[1/5] 启动浏览器加载游戏页面...")
    print(f"      URL: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        # 拦截所有请求,记录 URL 和 referer
        # 不限制资源类型,因为游戏引擎可能用 fetch/XHR 加载 .json/.png 等
        def on_request(request):
            # 跳过主文档导航请求(页面 HTML 本身,不是资源)
            if request.resource_type == "document":
                return
            u = request.url.split("?")[0]
            if u not in captured:
                captured[u] = request.headers.get("referer", "")

        def on_response(response):
            if response.status == 200:
                u = response.url.split("?")[0]
                if u not in captured:
                    captured[u] = response.request.headers.get("referer", "")

        context.on("request", on_request)
        context.on("response", on_response)

        # 加载页面
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"      ⚠️ 页面加载警告: {e}")

        page.wait_for_timeout(8000)
        print(f"      首页加载完成,已捕获 {len(captured)} 个资源")

        # 获取游戏名
        game_name = get_game_name(page, url)
        print(f"      游戏名: {game_name}")

        # 找真实游戏 frame(优先 files./cdn./含 index.html 的)
        # 部分平台用 gameframe 外壳,真实游戏在另一个域名的 iframe 里
        print(f"\n[2/5] 模拟交互触发动态资源加载...")

        # 先尝试点击 "Play" 按钮 —— 很多平台点击后才加载游戏本体到 iframe
        play_clicked = False
        for sel in [
            "button:has-text('Play')", "a:has-text('Play')",
            "[data-test='play-button']", ".play-button", "#play-button",
            "button[aria-label*='lay']", ".game-button",
            # itch.io 用 "Run game" 文案 + .play_btn / watch_btn 类名
            "a:has-text('Run game')", "a.play_btn", "a.watch_btn",
            "button.watch_btn", "[data-action='play_game']",
            # Newgrounds 用 "Play Game!" / "Play Movie!" 文案
            "a:has-text('Play Game')", "a:has-text('Play Movie')",
            "a[data-href*='play']", ".play_link",
        ]:
            try:
                el = page.query_selector(sel)
                if el:
                    el.scroll_into_view_if_needed(timeout=2000)
                    page.wait_for_timeout(400)
                    el.click(timeout=3000)
                    print(f"      ✓ 点击 Play 按钮")
                    play_clicked = True
                    break
            except Exception:
                continue
        if play_clicked:
            page.wait_for_timeout(9000)  # 等游戏本体加载(部分平台游戏 frame 延迟出现)

        # 重新获取 frame 列表(点 Play 后可能新增游戏 frame)
        frames = page.frames
        game_frame = None
        # 优先级 1:含 index.html 的 frame(真实游戏本体,而非入口 wrapper)
        for f in frames:
            if f == page.main_frame:
                continue
            fu = f.url.lower()
            if not fu or fu == "about:blank" or "doubleclick" in fu or "google" in fu:
                continue
            if "index.html" in fu:
                game_frame = f
                game_frame_url = f.url
                break
        # 优先级 2:游戏 CDN 关键字(files/cdn/gdn/games/game-files)
        if not game_frame:
            for f in frames:
                if f == page.main_frame:
                    continue
                fu = f.url.lower()
                if not fu or fu == "about:blank":
                    continue
                if any(k in fu for k in ("files.", "cdn.", "gdn.", "games.", "/game-files/",
                                         "ungrounded.net", "itch.zone", "html5.")):
                    game_frame = f
                    game_frame_url = f.url
                    break
        # 优先级 3:任何非主页面且非 about:blank 的 frame
        if not game_frame:
            for f in frames:
                fu = f.url.lower() if f.url else ""
                if f != page.main_frame and fu and fu != "about:blank" \
                   and "doubleclick" not in fu:
                    game_frame = f
                    game_frame_url = f.url
                    break

        if game_frame_url:
            print(f"      游戏 frame: {game_frame_url[:100]}")

        # 点击 canvas 触发动态加载
        click_target = game_frame if game_frame else page
        for click_round in range(6):
            try:
                canvas = click_target.query_selector("canvas")
                if canvas:
                    box = canvas.bounding_box()
                    if box:
                        positions = [
                            (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2),
                            (box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.8),
                            (box["x"] + box["width"] * 0.3, box["y"] + box["height"] / 2),
                            (box["x"] + box["width"] * 0.7, box["y"] + box["height"] / 2),
                        ]
                        x, y = positions[click_round % len(positions)]
                        click_target.click("canvas", position={"x": x - box["x"], "y": y - box["y"]}, force=True, timeout=2000)
                        print(f"      ✓ 点击 canvas ({click_round + 1}/6)")
            except Exception:
                pass
            page.wait_for_timeout(3000)

        # 等待动态资源加载
        print(f"      等待动态资源加载(20 秒)...")
        page.wait_for_timeout(20000)

        # 再次更新 frame 列表(canvas 点击/等待后可能再触发新游戏 frame)
        # 即使已找到 frame,如果发现含 index.html 的更优 frame,也更新
        # (例如 Poki 先出现 games.poki.com 入口,后才出现 xxx.gdn.poki.com/.../index.html 真实本体)
        frames = page.frames
        better_frame = None
        for f in frames:
            if f == page.main_frame:
                continue
            fu = f.url.lower() if f.url else ""
            if not fu or fu == "about:blank":
                continue
            if "index.html" in fu:
                better_frame = f
                break
        if better_frame:
            game_frame = better_frame
            game_frame_url = better_frame.url
            print(f"      更新为真实游戏本体 frame: {game_frame_url[:100]}")

        # [3/5] 引擎识别 + 引擎专属补抓
        print(f"\n[3/5] 识别游戏引擎...")
        engine = detect_engine(page, game_frame)
        print(f"      引擎: {engine}")

        # 先收集拦截到的 .js URL,供后续 JS 字符串扫描兜底用
        js_urls_intercepted = [
            u for u in captured
            if u.endswith(".js") and urlparse(u).netloc == (
                urlparse(game_frame_url).netloc if game_frame_url
                else urlparse(url).netloc
            )
        ]

        browser.close()

    # 引擎特定的补抓:对有清单的引擎优先解析清单
    extra = {}
    if game_frame_url:
        referer_for_extra = game_frame_url
        if engine == "cocos":
            print(f"      → Cocos Creator:解析 settings.js + 各 bundle config.json")
            extra.update(parse_cocos_manifest(game_frame_url, referer_for_extra, captured))
        elif engine == "unity":
            # Unity WebGL:解析 index.html 的 createUnityInstance config 对象
            # (浏览器拦截 wasm 流式请求时 URL 可能截断,需直接解析)
            print(f"      → Unity WebGL:解析 index.html 的 config 对象")
            extra.update(parse_unity_index(game_frame_url, referer_for_extra, captured))

    # 通用兜底:扫描所有拦截到的 JS 文件,提取明文资源路径
    # 适用于纯 HTML5/Phaser/PixiJS/Three.js 等无清单引擎
    if js_urls_intercepted:
        base_for_scan = game_frame_url if game_frame_url else url
        print(f"      → 通用兜底:扫描 {len(js_urls_intercepted)} 个 JS 文件提取资源路径")
        js_extra = scan_js_strings(
            js_urls_intercepted, base_for_scan, base_for_scan, captured
        )
        # 只保留同域的资源(避免抓到第三方)
        same_host = urlparse(base_for_scan).netloc
        for u, ref in js_extra.items():
            if urlparse(u).netloc == same_host:
                extra[u] = ref

    if extra:
        print(f"      引擎补抓新增资源: {len(extra)} 个")
        captured.update(extra)

    # 过滤策略:
    # 1. 必须是 http(s) URL
    # 2. 优先白名单:只保留和游戏 frame 同 host 的资源(最严格,保证游戏能跑)
    # 3. 如果游戏 frame 没找到,退回到黑名单过滤(保留所有非追踪域)
    filtered = {}
    if game_frame_url:
        # 同根域白名单:游戏 frame 的根域 + 同根域的资源都保留
        # 比如游戏 frame 在 games.poki.com,资源在 xxx.gdn.poki.com,
        # 两者根域都是 poki.com,应一并保留
        game_root = root_domain(urlparse(game_frame_url).netloc)
        for u, ref in captured.items():
            if not u.startswith("http"):
                continue
            if root_domain(urlparse(u).netloc) == game_root:
                # 排除明显的网站 UI 打包路径(避免抓网站外壳资源)
                if is_website_ui_path(u):
                    continue
                # 排除 API/追踪端点(下载必失败,无意义)
                if is_api_endpoint(u):
                    continue
                filtered[u] = ref
    else:
        # 没找到游戏 frame,用黑名单过滤
        blocked_domains = ("doubleclick.net", "google-analytics.com", "googletagmanager.com",
                           "facebook.net", "googlesyndication.com", "scorecardresearch.com",
                           "sparteo.com", "taboola.com", "outbrain.com", "criteo.com",
                           "amazon-adsystem.com", "pubmatic.com", "openx.net", "rubiconproject.com",
                           "adsrvr.org", "adnxs.com", "quantserve.com", "bidswitch.net",
                           "tapad.com", "moatads.com", "adlightning.com", "contextweb.com",
                           "3lift.com", "casalemedia.com", "rlcdn.com")
        for u, ref in captured.items():
            if not u.startswith("http"):
                continue
            if any(d in u for d in blocked_domains):
                continue
            if is_website_ui_path(u):
                continue
            if is_api_endpoint(u):
                continue
            filtered[u] = ref

    # 推断主域:优先用游戏 frame URL 的 host(决定本地保存路径的根)
    if game_frame_url:
        main_host = urlparse(game_frame_url).netloc
        print(f"\n      游戏 CDN 主域: {main_host}")
    else:
        main_host = urlparse(url).netloc

    print(f"      总捕获资源: {len(filtered)} 个(已过滤第三方追踪和网站 UI)")
    return filtered, game_name, main_host


def download_resources(resources, game_name, main_host):
    """批量下载资源到 ./<game_name>/ 目录"""
    out_dir = Path(__file__).parent / game_name
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n[4/5] 下载资源到: {out_dir}")
    print(f"      主域: {main_host}")

    headers_base = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }

    # 把 URL 列表整理出来,带各自的 referer
    urls = list(resources.items())  # [(url, referer), ...]

    def download_one(item):
        url, referer = item
        try:
            headers = headers_base.copy()
            if referer:
                headers["Referer"] = referer
                headers["Origin"] = urlparse(referer).scheme + "://" + urlparse(referer).netloc

            # 推算本地保存路径
            parsed = urlparse(url)
            safe_host = re.sub(r'[\\/:*?"<>|]', "_", parsed.netloc)
            rel_path = parsed.path.lstrip("/")
            rel_path = unquote(rel_path)
            rel_path = re.sub(r'[\\:*?"<>|]', "_", rel_path)

            # 主域资源直接放根目录,跨域资源放 _external/<host>/
            if parsed.netloc == main_host:
                full_rel = rel_path
            else:
                full_rel = f"_external/{safe_host}/{rel_path}"

            # 无后缀路径(没有 .)直接加 .bin,避免和目录冲突
            filename = os.path.basename(full_rel)
            if filename and "." not in filename:
                full_rel = full_rel + ".bin"

            local_path = out_dir / full_rel

            # 检查路径上每层有没有同名文件,有就把那个旧文件改名为 .bin
            check = local_path.parent
            while check != out_dir.parent and check != out_dir:
                if check.exists() and check.is_file():
                    # 把这个冲突的文件改名为 .bin
                    try:
                        new_name = str(check) + ".bin"
                        if not os.path.exists(new_name):
                            check.rename(new_name)
                    except Exception:
                        pass
                    break
                check = check.parent

            # 已存在且非空则跳过
            if local_path.exists() and local_path.is_file() and local_path.stat().st_size > 0:
                return (url, True, 0, "skipped")

            # 如果 local_path 已存在为目录,加 .bin 后缀
            if local_path.exists() and local_path.is_dir():
                local_path = local_path.with_name(local_path.name + ".bin")

            local_path.parent.mkdir(parents=True, exist_ok=True)

            last_err = None
            for attempt in range(4):  # 重试 4 次,避免网络抖动
                try:
                    r = requests.get(url, headers=headers, timeout=60)
                    if r.status_code != 200:
                        last_err = f"HTTP {r.status_code}"
                        continue
                    with open(local_path, "wb") as f:
                        f.write(r.content)
                    return (url, True, len(r.content), None)
                except Exception as e:
                    last_err = str(e)[:80]
                    time.sleep(1.5)
            return (url, False, 0, last_err)
        except Exception as e:
            return (url, False, 0, f"ERR: {str(e)[:80]}")

    success = fail = skip = 0
    total_bytes = 0
    fail_list = []
    start = time.time()
    total = len(urls)

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(download_one, item): item for item in urls}
        done = 0
        for fut in as_completed(futures):
            url, ok, size, err = fut.result()
            done += 1
            if ok:
                if err == "skipped":
                    skip += 1
                else:
                    success += 1
                    total_bytes += size
            else:
                fail += 1
                fail_list.append((url, err))
            if done % 30 == 0 or done == total:
                print(f"      进度 {done}/{total}  成功 {success}  跳过 {skip}  失败 {fail}")

    print(f"\n[5/5] 下载完成")
    print(f"      成功: {success}")
    print(f"      跳过: {skip}")
    print(f"      失败: {fail}")
    print(f"      大小: {total_bytes / 1024 / 1024:.2f} MB")
    print(f"      用时: {time.time() - start:.1f}s")

    if fail_list:
        fail_file = out_dir / "_failed.txt"
        with open(fail_file, "w", encoding="utf-8") as f:
            for url, err in fail_list:
                f.write(f"{url}\t{err}\n")
        print(f"      失败列表已保存到: {fail_file}")

    return out_dir


def main():
    # 解析参数
    if len(sys.argv) >= 2:
        url = sys.argv[1]
    else:
        url = input("请输入游戏页面 URL: ").strip()
        if not url:
            print("URL 不能为空")
            return

    print("=" * 70)
    print("  网页游戏资源抓取工具")
    print("=" * 70)

    ensure_browser()

    try:
        resources, game_name, main_host = collect_game_resources(url)
    except Exception as e:
        print(f"\n❌ 抓取失败: {e}")
        import traceback
        traceback.print_exc()
        return

    if not resources:
        print("\n❌ 没有抓到任何资源")
        return

    out_dir = download_resources(resources, game_name, main_host)
    print(f"\n✅ 完成!资源已保存到: {out_dir}")

    # 找出 index.html 的相对路径,给用户准确的访问 URL
    index_files = list(out_dir.rglob("index.html"))
    if index_files:
        rel = index_files[0].relative_to(out_dir).as_posix()
        print(f"\n💡 本地运行:")
        print(f"   cd \"{out_dir}\"")
        print(f"   python -m http.server 8080")
        print(f"   浏览器打开 http://localhost:8080/{rel}")


if __name__ == "__main__":
    main()

import unittest

from webgame_crawler.manifests import extract_resource_urls, supplement_resources
from webgame_crawler.models import ResourceRecord


class ManifestTests(unittest.TestCase):
    def test_unity_urls_resolve_beside_index_document(self):
        text = """
        const config = {
          dataUrl: "Build/game.data.br",
          frameworkUrl: "Build/game.framework.js.br",
          codeUrl: "Build/game.wasm.br"
        };
        """

        urls = extract_resource_urls(
            text, "https://cdn.example.com/game/index.html", engine="unity"
        )

        self.assertEqual(
            urls,
            {
                "https://cdn.example.com/game/Build/game.data.br",
                "https://cdn.example.com/game/Build/game.framework.js.br",
                "https://cdn.example.com/game/Build/game.wasm.br",
            },
        )

    def test_construct_and_generic_media_formats_are_included(self):
        text = """
        {"files":["media/walk.webm","box2d.wasm","textures/road.ktx2",
        "models/car.glb","video/intro.mp4","packs/level.pck"]}
        """

        urls = extract_resource_urls(
            text, "https://files.example.com/game/data.json", engine="construct"
        )

        self.assertIn("https://files.example.com/game/media/walk.webm", urls)
        self.assertIn("https://files.example.com/game/box2d.wasm", urls)
        self.assertIn("https://files.example.com/game/textures/road.ktx2", urls)
        self.assertIn("https://files.example.com/game/video/intro.mp4", urls)
        self.assertIn("https://files.example.com/game/packs/level.pck", urls)

    def test_laya_and_cocos_resource_formats_are_included(self):
        text = """
        ["res/ui.atlas","scene/main.ls","models/hero.lh","models/body.lm",
        "materials/hero.lmat","anim/run.ani","skeleton/hero.sk",
        "assets/main/config.abc.json","native/aa/texture.webp"]
        """

        urls = extract_resource_urls(
            text, "https://cdn.example.com/release/version.json", engine="laya"
        )

        expected_suffixes = (
            "res/ui.atlas",
            "scene/main.ls",
            "models/hero.lh",
            "models/body.lm",
            "materials/hero.lmat",
            "anim/run.ani",
            "skeleton/hero.sk",
            "assets/main/config.abc.json",
            "native/aa/texture.webp",
        )
        for suffix in expected_suffixes:
            self.assertIn("https://cdn.example.com/release/" + suffix, urls)

    def test_supplement_resources_deduplicates_full_urls(self):
        source = ResourceRecord(
            url="https://game.example/scripts/main.js?version=2",
            resource_type="script",
            frame_url="https://game.example/index.html",
            status=200,
            request_headers={"referer": "https://game.example/index.html"},
        )

        def fetch_text(url, _headers):
            self.assertEqual(url, source.url)
            return "'assets/level.json?version=1' 'assets/level.json?version=2'"

        supplemented = supplement_resources(
            [source],
            {source.frame_url: "html5"},
            fetch_text,
        )

        self.assertEqual(
            [record.url for record in supplemented],
            [
                "https://game.example/scripts/assets/level.json?version=1",
                "https://game.example/scripts/assets/level.json?version=2",
            ],
        )
        self.assertTrue(all(not record.required for record in supplemented))

    def test_rejects_bare_extensions_and_javascript_diagnostics(self):
        text = """
        '.mp3' '.js' 'build.wasm'
        'Detected deprecated API. Refer to https://docs.unity3d.com/manual/info.html#api\n'
        ')) { const value = broken; } weird.bundle.js'
        """

        urls = extract_resource_urls(
            text, "https://cdn.example.com/Build/loader.js", engine="unity"
        )

        self.assertEqual(urls, {"https://cdn.example.com/Build/build.wasm"})


if __name__ == "__main__":
    unittest.main()

import unittest

from webgame_crawler.manifests import extract_resource_urls, supplement_resources
from webgame_crawler.models import ResourceRecord


class ManifestTests(unittest.TestCase):
    def test_cocos_config_expands_all_versioned_imports(self):
        text = """
        {
          "uuids": ["ecpdLyjvZBwrvm+cedCcQy"],
          "importBase": "import",
          "versions": {
            "import": [0, "a1b2c", "01f944abd", "6aa8e"]
          }
        }
        """

        urls = extract_resource_urls(
            text,
            "https://cdn.example/game/assets/main/config.12345.json",
            engine="cocos",
        )

        self.assertEqual(
            urls,
            {
                "https://cdn.example/game/assets/main/import/ec/"
                "eca5d2f2-8ef6-41c2-bbe6-f9c79d09c432.a1b2c.json",
                "https://cdn.example/game/assets/main/import/01/"
                "01f944abd.6aa8e.json",
            },
        )

    def test_cocos_import_decodes_uuid_with_subasset_suffix(self):
        text = """
        {
          "uuids": ["5awIg39ZFO/5Yc26OXjv+J@f9941"],
          "versions": {"import": [0, "bf995"]}
        }
        """

        urls = extract_resource_urls(
            text,
            "https://cdn.example/game/assets/resources/config.json",
            engine="cocos",
        )

        self.assertEqual(
            urls,
            {
                "https://cdn.example/game/assets/resources/import/5a/"
                "5ac08837-f591-4eff-961c-dba3978eff89@f9941.bf995.json"
            },
        )

    def test_cocos_import_uses_binary_extension_map(self):
        text = """
        {
          "uuids": ["7051cea2-46b6-46d7-9a6a-836a4d780015"],
          "extensionMap": {".cconb": [0]},
          "versions": {"import": [0, "d1dca"]}
        }
        """

        urls = extract_resource_urls(
            text,
            "https://cdn.example/game/assets/main/config.json",
            engine="cocos",
        )

        self.assertEqual(
            urls,
            {
                "https://cdn.example/game/assets/main/import/70/"
                "7051cea2-46b6-46d7-9a6a-836a4d780015.d1dca.bin"
            },
        )

    def test_cocos_import_ignores_malformed_extension_map(self):
        for extension_map in ("null", "[]"):
            with self.subTest(extension_map=extension_map):
                text = f"""
                {{
                  "uuids": ["7051cea2-46b6-46d7-9a6a-836a4d780015"],
                  "extensionMap": {extension_map},
                  "versions": {{"import": [0, "d1dca"]}}
                }}
                """

                urls = extract_resource_urls(
                    text,
                    "https://cdn.example/game/assets/main/config.json",
                    engine="cocos",
                )

                self.assertEqual(
                    urls,
                    {
                        "https://cdn.example/game/assets/main/import/70/"
                        "7051cea2-46b6-46d7-9a6a-836a4d780015.d1dca.json"
                    },
                )

    def test_cocos_extension_map_resolves_numeric_string_uuid_index(self):
        text = """
        {
          "uuids": ["7051cea2-46b6-46d7-9a6a-836a4d780015"],
          "extensionMap": {".cconb": ["0"]},
          "versions": {"import": [0, "d1dca"]}
        }
        """

        urls = extract_resource_urls(
            text,
            "https://cdn.example/game/assets/main/config.json",
            engine="cocos",
        )

        self.assertEqual(
            urls,
            {
                "https://cdn.example/game/assets/main/import/70/"
                "7051cea2-46b6-46d7-9a6a-836a4d780015.d1dca.bin"
            },
        )

    def test_cocos_config_expands_versioned_native_candidates_by_type(self):
        text = """
        {
          "uuids": ["ecpdLyjvZBwrvm+cedCcQy", "1102b2af0"],
          "types": ["cc.AudioClip", "cc.Texture2D"],
          "paths": {
            "0": ["sound/hit", 0],
            "1": ["images/atlas", 1]
          },
          "nativeBase": "native",
          "versions": {
            "native": [0, "abc12", 1, "def34"]
          }
        }
        """

        urls = extract_resource_urls(
            text,
            "https://cdn.example/game/assets/main/config.12345.json",
            engine="cocos",
        )

        self.assertIn(
            "https://cdn.example/game/assets/main/native/ec/"
            "eca5d2f2-8ef6-41c2-bbe6-f9c79d09c432.abc12.mp3",
            urls,
        )
        self.assertIn(
            "https://cdn.example/game/assets/main/native/11/"
            "1102b2af0.def34.png",
            urls,
        )

    def test_supplement_probes_cocos_native_candidates(self):
        source = ResourceRecord(
            url="https://cdn.example/game/assets/main/config.12345.json",
            resource_type="fetch",
            frame_url="https://cdn.example/game/index.html",
            response_headers={"content-type": "application/json"},
        )
        config = """
        {
          "uuids": ["ecpdLyjvZBwrvm+cedCcQy"],
          "types": ["cc.AudioClip"],
          "paths": {"0": ["sound/hit", 0]},
          "versions": {"native": [0, "abc12"]}
        }
        """
        expected = (
            "https://cdn.example/game/assets/main/native/ec/"
            "eca5d2f2-8ef6-41c2-bbe6-f9c79d09c432.abc12.mp3"
        )

        def probe_urls(urls, _headers):
            self.assertGreater(len(urls), 1)
            return {expected}

        supplemented = supplement_resources(
            [source],
            {source.frame_url: "cocos"},
            lambda *_: config,
            probe_urls=probe_urls,
        )

        self.assertEqual([record.url for record in supplemented], [expected])

    def test_supplement_keeps_declared_cocos_import_when_probe_is_inconclusive(self):
        source = ResourceRecord(
            url="https://cdn.example/game/assets/main/config.json",
            resource_type="fetch",
            frame_url="https://cdn.example/game/index.html",
            response_headers={"content-type": "application/json"},
        )
        config = """
        {
          "uuids": ["01f944abd"],
          "versions": {"import": [0, "6aa8e"]}
        }
        """
        expected = (
            "https://cdn.example/game/assets/main/import/01/"
            "01f944abd.6aa8e.json"
        )

        supplemented = supplement_resources(
            [source],
            {source.frame_url: "cocos"},
            lambda *_: config,
            probe_urls=lambda *_: set(),
        )

        self.assertEqual([record.url for record in supplemented], [expected])

    def test_supplement_verifies_speculative_cocos_script_references(self):
        source = ResourceRecord(
            url="https://cdn.example/game/src/main.js",
            resource_type="script",
            frame_url="https://cdn.example/game/index.html",
            response_headers={"content-type": "application/javascript"},
        )
        existing = "https://cdn.example/game/src/assets/real.png"
        missing = "https://cdn.example/game/src/chunks/ghost.js"
        script = "'assets/real.png' 'chunks/ghost.js'"

        def probe_urls(urls, _headers):
            self.assertEqual(urls, {existing, missing})
            return {existing}

        supplemented = supplement_resources(
            [source],
            {source.frame_url: "cocos"},
            lambda *_: script,
            probe_urls=probe_urls,
        )

        self.assertEqual([record.url for record in supplemented], [existing])

    def test_supplement_verifies_speculative_generic_script_references(self):
        source = ResourceRecord(
            url="https://cdn.example/game/main.js",
            resource_type="script",
            frame_url="https://cdn.example/game/index.html",
            response_headers={"content-type": "application/javascript"},
        )
        existing = "https://cdn.example/game/assets/real.json"
        missing = "https://cdn.example/game/assets/missing.json"

        supplemented = supplement_resources(
            [source],
            {source.frame_url: "html5"},
            lambda *_: "'assets/real.json' 'assets/missing.json'",
            probe_urls=lambda urls, _headers: urls & {existing},
        )

        self.assertEqual([record.url for record in supplemented], [existing])

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

import asyncio
import copy
import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


PROJECT_PARENT = Path(__file__).resolve().parents[2]
if str(PROJECT_PARENT) not in sys.path:
    sys.path.insert(0, str(PROJECT_PARENT))


def install_astrbot_stubs():
    if "astrbot.api" in sys.modules:
        return

    astrbot_mod = types.ModuleType("astrbot")
    api_mod = types.ModuleType("astrbot.api")
    event_mod = types.ModuleType("astrbot.api.event")
    star_mod = types.ModuleType("astrbot.api.star")
    comp_mod = types.ModuleType("astrbot.api.message_components")
    bs4_mod = types.ModuleType("bs4")

    class Logger:
        def debug(self, *args, **kwargs):
            pass

        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    class AstrBotConfig(dict):
        def save_config(self, replace_config=None):
            if replace_config:
                self.update(replace_config)

    class MessageChain:
        def __init__(self, chain=None):
            self.chain = chain or []

    class Filter:
        class PermissionType:
            ADMIN = "admin"

        class EventMessageType:
            ALL = "all"

        def command(self, *args, **kwargs):
            return lambda func: func

        def permission_type(self, *args, **kwargs):
            return lambda func: func

        def event_message_type(self, *args, **kwargs):
            return lambda func: func

    class Star:
        def __init__(self, context=None, config=None):
            self.context = context

    class Context:
        pass

    class Plain:
        def __init__(self, text=""):
            self.text = text

    class Image:
        def __init__(self, file="", path="", url=""):
            self.file = file
            self.path = path
            self.url = url

        @classmethod
        def fromURL(cls, url):
            return cls(file=url, url=url)

        @classmethod
        def fromFileSystem(cls, path):
            return cls(file=f"file:///{Path(path).resolve()}", path=str(path))

    class Video:
        def __init__(self, file="", path="", url=""):
            self.file = file
            self.path = path
            self.url = url

        @classmethod
        def fromURL(cls, url):
            return cls(file=url, url=url)

        @classmethod
        def fromFileSystem(cls, path):
            return cls(file=f"file:///{Path(path).resolve()}", path=str(path))

    class Node:
        def __init__(self, content=None, name=""):
            self.content = content or []
            self.name = name

    class Nodes:
        def __init__(self, nodes=None):
            self.nodes = nodes or []

    class BeautifulSoup:
        def __init__(self, *args, **kwargs):
            pass

    api_mod.AstrBotConfig = AstrBotConfig
    api_mod.logger = Logger()
    event_mod.AstrMessageEvent = object
    event_mod.MessageChain = MessageChain
    event_mod.filter = Filter()
    star_mod.Context = Context
    star_mod.Star = Star
    comp_mod.Plain = Plain
    comp_mod.Image = Image
    comp_mod.Video = Video
    comp_mod.Node = Node
    comp_mod.Nodes = Nodes
    bs4_mod.BeautifulSoup = BeautifulSoup

    sys.modules["astrbot"] = astrbot_mod
    sys.modules["astrbot.api"] = api_mod
    sys.modules["astrbot.api.event"] = event_mod
    sys.modules["astrbot.api.star"] = star_mod
    sys.modules["astrbot.api.message_components"] = comp_mod
    sys.modules["bs4"] = bs4_mod


install_astrbot_stubs()
twitter_main = importlib.import_module("astrbot_plugin_twitter.main")


class MemoryConfig(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_count = 0

    def save_config(self, replace_config=None):
        self.save_count += 1
        if replace_config:
            self.update(replace_config)


class MemoryTwitterPlugin(twitter_main.TwitterPlugin):
    def __init__(self, config=None):
        self.config = MemoryConfig(config or {})
        self.store = {}
        self.put_count = 0
        self.fail_next_put = False
        self._subs_lock = asyncio.Lock()
        self.no_text = bool(self.config.get("twitter_no_text", False))
        self.media_cache_max_bytes = int(
            float(self.config.get("twitter_media_cache_max_mb", 512)) * 1024 * 1024
        )
        self.media_cache_ttl_seconds = (
            float(self.config.get("twitter_media_cache_ttl_hours", 24)) * 3600
        )
        self.media_max_file_bytes = int(
            float(self.config.get("twitter_media_max_file_mb", 64)) * 1024 * 1024
        )
        self.media_cache_dir = Path(tempfile.mkdtemp()) / "media"
        self.twitter_api = None

    async def get_kv_data(self, key, default):
        if key != twitter_main.KV_SUBS_KEY:
            return copy.deepcopy(default)
        return copy.deepcopy(self.store)

    async def put_kv_data(self, key, value):
        if key != twitter_main.KV_SUBS_KEY:
            return
        self.put_count += 1
        if self.fail_next_put:
            self.fail_next_put = False
            self.store = {
                "existing": {
                    "screen_name": "Existing",
                    "since_id": "9",
                    "subscribers": {
                        "qq2:GroupMessage:1": {
                            "status": True,
                            "r18": False,
                            "media": False,
                        }
                    },
                }
            }
            raise RuntimeError(
                "UNIQUE constraint failed: preferences.scope, "
                "preferences.scope_id, preferences.key"
            )
        self.store = copy.deepcopy(value)


class FakeMediaAPI:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = {}

    async def download_media(self, url, max_bytes):
        self.calls[url] = self.calls.get(url, 0) + 1
        return self.payloads[url]


class SubscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().slow_callback_duration = 1.0

    async def test_save_subs_retries_and_merges_after_unique_conflict(self):
        plugin = MemoryTwitterPlugin()
        plugin.fail_next_put = True

        await plugin._save_subs(
            {
                "alice": {
                    "screen_name": "Alice",
                    "since_id": "10",
                    "subscribers": {
                        "default:GroupMessage:1": {
                            "status": True,
                            "r18": True,
                            "media": False,
                        }
                    },
                }
            }
        )

        self.assertEqual(plugin.put_count, 2)
        self.assertIn("existing", plugin.store)
        self.assertIn("alice", plugin.store)
        self.assertIn(
            "default:GroupMessage:1",
            plugin.store["alice"]["subscribers"],
        )

    async def test_configured_umo_subscriptions_are_exposed_as_runtime_subs(self):
        plugin = MemoryTwitterPlugin(
            {
                "twitter_subscriptions": [
                    {
                        "__template_key": "subscription",
                        "username": "@alice",
                        "unified_msg_origin": "qq2:GroupMessage:123",
                        "enabled": True,
                        "r18": True,
                        "media": False,
                        "screen_name": "Alice",
                        "since_id": "20",
                    },
                    {
                        "__template_key": "subscription",
                        "username": "bob",
                        "unified_msg_origin": "default:FriendMessage:456",
                        "enabled": False,
                        "r18": False,
                        "media": True,
                        "screen_name": "",
                        "since_id": "",
                    },
                ]
            }
        )

        subs = await plugin._get_subs()

        self.assertEqual(subs["alice"]["screen_name"], "Alice")
        self.assertEqual(subs["alice"]["since_id"], "20")
        self.assertEqual(
            subs["alice"]["subscribers"]["qq2:GroupMessage:123"],
            {"status": True, "r18": True, "media": False},
        )
        self.assertEqual(
            subs["bob"]["subscribers"]["default:FriendMessage:456"],
            {"status": False, "r18": False, "media": True},
        )

    async def test_legacy_kv_subscriptions_are_synced_to_config_panel(self):
        plugin = MemoryTwitterPlugin()
        plugin.store = {
            "alice": {
                "screen_name": "Alice",
                "since_id": "42",
                "subscribers": {
                    "qq2:GroupMessage:123": {
                        "status": True,
                        "r18": False,
                        "media": True,
                    }
                },
            }
        }

        await plugin._sync_kv_subscriptions_to_config()

        entries = plugin.config["twitter_subscriptions"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["username"], "alice")
        self.assertEqual(entries[0]["unified_msg_origin"], "qq2:GroupMessage:123")
        self.assertEqual(entries[0]["screen_name"], "Alice")
        self.assertEqual(entries[0]["since_id"], "42")
        self.assertTrue(entries[0]["enabled"])
        self.assertFalse(entries[0]["r18"])
        self.assertTrue(entries[0]["media"])

    async def test_panel_deleted_subscription_is_not_restored_from_kv(self):
        plugin = MemoryTwitterPlugin({"twitter_subscriptions": []})
        plugin.store = {
            "alice": {
                "screen_name": "Alice",
                "since_id": "42",
                "subscribers": {
                    "qq2:GroupMessage:123": {
                        "status": True,
                        "r18": False,
                        "media": True,
                    }
                },
            }
        }

        await plugin._sync_kv_subscriptions_to_config()
        subs = await plugin._get_subs()

        self.assertEqual(plugin.config["twitter_subscriptions"], [])
        self.assertNotIn("alice", subs)
        self.assertEqual(plugin.config.save_count, 0)

    async def test_panel_changed_umo_removes_old_umo_from_runtime_and_kv(self):
        plugin = MemoryTwitterPlugin(
            {
                "twitter_subscriptions": [
                    {
                        "__template_key": "subscription",
                        "username": "alice",
                        "unified_msg_origin": "qq2:GroupMessage:new",
                        "enabled": True,
                        "r18": True,
                        "media": False,
                        "screen_name": "Alice",
                        "since_id": "42",
                    }
                ]
            }
        )
        plugin.store = {
            "alice": {
                "screen_name": "Alice",
                "since_id": "42",
                "subscribers": {
                    "qq2:GroupMessage:old": {
                        "status": True,
                        "r18": False,
                        "media": True,
                    }
                },
            }
        }

        subs = await plugin._get_subs()
        await plugin._save_subs(subs)

        self.assertIn("alice", subs)
        self.assertIn("qq2:GroupMessage:new", subs["alice"]["subscribers"])
        self.assertNotIn("qq2:GroupMessage:old", subs["alice"]["subscribers"])
        self.assertIn("qq2:GroupMessage:new", plugin.store["alice"]["subscribers"])
        self.assertNotIn("qq2:GroupMessage:old", plugin.store["alice"]["subscribers"])
        self.assertEqual(
            plugin.store["alice"]["subscribers"]["qq2:GroupMessage:new"],
            {"status": True, "r18": True, "media": False},
        )

    async def test_tweet_chain_downloads_media_to_local_cache(self):
        image_url = "https://nitter.net/pic/media%2Fabc.jpg"
        video_url = "https://nitter.net/video/abc.mp4"
        plugin = MemoryTwitterPlugin()
        plugin.twitter_api = FakeMediaAPI(
            {
                image_url: (b"image-bytes", "image/jpeg"),
                video_url: (b"video-bytes", "video/mp4"),
            }
        )

        chain = await plugin._build_tweet_chain(
            "alice",
            {
                "tweet_id": "1",
                "screen_name": "Alice",
                "text": "hello",
                "images": [image_url],
                "videos": [video_url],
            },
        )

        images = [item for item in chain if isinstance(item, twitter_main.Comp.Image)]
        videos = [item for item in chain if isinstance(item, twitter_main.Comp.Video)]
        self.assertEqual(len(images), 1)
        self.assertEqual(len(videos), 1)
        self.assertTrue(images[0].file.startswith("file:///"))
        self.assertTrue(videos[0].file.startswith("file:///"))
        self.assertEqual(Path(images[0].path).read_bytes(), b"image-bytes")
        self.assertEqual(Path(videos[0].path).read_bytes(), b"video-bytes")

    async def test_tweet_chain_reuses_cached_media_file(self):
        image_url = "https://nitter.net/pic/media%2Fsame.jpg"
        plugin = MemoryTwitterPlugin()
        plugin.twitter_api = FakeMediaAPI({image_url: (b"image-bytes", "image/jpeg")})
        tweet_info = {
            "tweet_id": "1",
            "screen_name": "Alice",
            "text": "hello",
            "images": [image_url],
            "videos": [],
        }

        first_chain = await plugin._build_tweet_chain("alice", tweet_info)
        second_chain = await plugin._build_tweet_chain("alice", tweet_info)

        first_image = next(
            item for item in first_chain if isinstance(item, twitter_main.Comp.Image)
        )
        second_image = next(
            item for item in second_chain if isinstance(item, twitter_main.Comp.Image)
        )
        self.assertEqual(first_image.path, second_image.path)
        self.assertEqual(plugin.twitter_api.calls[image_url], 1)

    async def test_media_cache_cleanup_removes_expired_and_oversized_files(self):
        plugin = MemoryTwitterPlugin(
            {
                "twitter_media_cache_max_mb": 0.00001,
                "twitter_media_cache_ttl_hours": 0.00001,
            }
        )
        plugin.media_cache_dir.mkdir(parents=True, exist_ok=True)
        expired_file = plugin.media_cache_dir / "expired.jpg"
        large_file = plugin.media_cache_dir / "large.jpg"
        fresh_file = plugin.media_cache_dir / "fresh.jpg"
        expired_file.write_bytes(b"old")
        large_file.write_bytes(b"x" * 12)
        fresh_file.write_bytes(b"ok")
        old_time = 1
        os.utime(expired_file, (old_time, old_time))
        os.utime(large_file, (old_time + 1, old_time + 1))

        plugin._cleanup_media_cache()

        self.assertFalse(expired_file.exists())
        self.assertFalse(large_file.exists())
        self.assertTrue(fresh_file.exists())


if __name__ == "__main__":
    unittest.main()

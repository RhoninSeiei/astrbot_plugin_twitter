import asyncio
import copy
import importlib
import sys
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
        @classmethod
        def fromURL(cls, url):
            inst = cls()
            inst.url = url
            return inst

    class Video:
        @classmethod
        def fromURL(cls, url):
            inst = cls()
            inst.url = url
            return inst

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


class SubscriptionTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()

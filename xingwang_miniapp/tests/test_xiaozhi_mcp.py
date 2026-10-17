"""Offline-only Xiaozhi MCP protocol tests; no tokens or external requests."""
import asyncio
import json
import unittest
from xingwang_miniapp.xiaozhi_mcp import handle_message, valid_endpoint

class XiaozhiProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_handshake(self):
        async def stub(code):
            return {"ok": True, "code": code, "stock_rolls": 3}
        init = await handle_message({"jsonrpc":"2.0","id":1,"method":"initialize",
                                     "params":{"protocolVersion":"2024-11-05"}},stub)
        self.assertEqual(init["result"]["serverInfo"]["name"],"XINGWANG Stock Read-only")
        tools = await handle_message({"jsonrpc":"2.0","id":2,"method":"tools/list"},stub)
        self.assertEqual([v["name"] for v in tools["result"]["tools"]], ["search_stock"])
        resp = await handle_message({"jsonrpc":"2.0","id":3,"method":"tools/call",
                      "params":{"name":"search_stock","arguments":{"code":"158-217-"}}},stub)
        self.assertEqual(json.loads(resp["result"]["content"][0]["text"])["code"],"158-217-")
        self.assertFalse(resp["result"]["isError"])
        self.assertIsNone(await handle_message({"jsonrpc":"2.0","method":"notifications/initialized"},stub))
        self.assertEqual((await handle_message({"jsonrpc":"2.0","id":4,"method":"ping"},stub))["result"],{})

    async def test_invalid_tool(self):
        resp = await handle_message({"jsonrpc":"2.0","id":3,"method":"tools/call",
                         "params":{"name":"delete_order","arguments":{"code":"1314"}}})
        self.assertEqual(resp["error"]["code"],-32602)

    def test_wss_host(self):
        self.assertTrue(valid_endpoint("wss://api.xiaozhi.me/mcp/?token="+"a"*40))
        self.assertFalse(valid_endpoint("wss://api.xiaozhi.me.evil.org/?token="+"a"*40))
        self.assertFalse(valid_endpoint("https://api.xiaozhi.me/mcp/?token="+"a"*40))
        self.assertFalse(valid_endpoint("wss://api.xiaozhi.me/mcp/"))

if __name__=="__main__":
    unittest.main()

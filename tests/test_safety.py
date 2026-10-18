import asyncio
import os
import sys

from dbagent import server

HUMAN_ONLY = {"approve", "reject", "restore", "run_sql", "execute_sql", "delete", "drop_table"}


def test_human_only_actions_are_not_exposed():
    assert HUMAN_ONLY.isdisjoint(server.EXPOSED_TOOLS)


def test_registered_tools_match_allow_list():
    assert {t.name for t in asyncio.run(server.mcp.list_tools())} == set(server.EXPOSED_TOOLS)


def test_mcp_stdio_roundtrip(database):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "dbagent.server"], env=dict(os.environ))
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            ok = await s.call_tool("run_query", {"sql": "SELECT COUNT(*) FROM cust"})
            bad = await s.call_tool("run_query", {"sql": "SELECT email FROM cust"})
            return names, ok, bad

    names, ok, bad = asyncio.run(go())
    assert names == set(server.EXPOSED_TOOLS)
    assert not ok.isError and "500" in "".join(getattr(c, "text", "") for c in ok.content)
    assert bad.isError

#!/usr/bin/env python3
"""Independent streamable HTTP MCP client smoke test, loopback-only."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT=Path(__file__).resolve().parents[1]
HOST="127.0.0.1"
PORT=28761

def listening():
    with socket.socket() as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((HOST,PORT))==0

async def probe():
    async with streamablehttp_client(f"http://{HOST}:{PORT}/mcp",timeout=15,sse_read_timeout=15) as (read,write,_):
        async with ClientSession(read,write) as session:
            await session.initialize()
            tools=await session.list_tools()
            names=[tool.name for tool in tools.tools]
            print("MCP_TOOLS",names)
            assert "rag_search" in names
            result=await session.call_tool("rag_search",{"query":"OpenCode coding agents","limit":1})
            print("MCP_SEARCH",{"error":result.isError,"content_blocks":len(result.content)})
            assert not result.isError and result.content
            payload=json.loads(next(block.text for block in result.content if getattr(block,"text",None)))
            assert payload["results"] and payload["results"][0]["source"]=="docs/sample.md"
            assert len(payload["results"][0]["id"])==64
            print("MCP_PROVENANCE_VALID",True)

def main():
    assert not listening(), "Isolated port already occupied; will not interrupt a foreign service"
    env=dict(os.environ,CITERAG_MCP_HOST=HOST,CITERAG_MCP_PORT=str(PORT),CITERAG_OFFLINE="1",PYTHONDONTWRITEBYTECODE="1")
    process=subprocess.Popen([sys.executable,"-m","citerag.server"],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for i in range(100):
            if listening():break
            if process.poll() is not None:raise RuntimeError("CiteRAG MCP server exited before listener readiness")
            time.sleep(0.25)
        else:raise TimeoutError("MCP listener startup deadline exceeded")
        asyncio.run(probe())
    finally:
        process.terminate()
        try:process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        for i in range(20):
            if not listening():break
            time.sleep(0.1)
        print("MCP_PORT_CLOSED",not listening())
        assert not listening(), "Isolated MCP port remained open"

if __name__=="__main__":main()

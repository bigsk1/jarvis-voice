"""Direct price routes must not stall unrelated requests while a tool waits."""

import asyncio
import importlib.util
import sys
import threading
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from lib.config_loader import config_scope, get_active_config_mode, get_config_value


@pytest.fixture
def price_api(monkeypatch):
    # Load only this router; importing the production app would initialize other services.
    path = Path(__file__).resolve().parents[1] / "api/routes/prices.py"
    name = "_price_api_concurrency_test"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router)

    @app.get("/api/alert-probe")
    async def alert_probe():
        return {"responsive": True}

    return module, app


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("path", [
    "/api/prices/stock/EXAMPLE",
    "/api/prices/crypto/BTC",
    "/api/prices/crypto/BTC/chart",
    "/api/prices/batch?stocks=EXAMPLE",
    "/api/prices/batch?crypto=BTC",
])
def test_waiting_price_tool_leaves_event_loop_responsive(price_api, monkeypatch, mode, path):
    module, app = price_api
    entered = threading.Event()
    release = threading.Event()
    seen = []
    event_loop_thread = threading.get_ident()

    def blocking_tool(_name, _args):
        seen.append((threading.get_ident(), get_active_config_mode(),
                     get_config_value("PRICE_TEST_SETTING")))
        entered.set()
        assert release.wait(5), "Unrelated request did not release the controlled price lookup"
        return {"ok": True, "data": {"coin_id": "bitcoin", "requested": "btc"}}

    monkeypatch.setattr(module, "call_tool", blocking_tool)

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            with config_scope(mode, overrides={"PRICE_TEST_SETTING": "request-scoped"}):
                pending = asyncio.create_task(client.get(path))
                try:
                    assert await asyncio.to_thread(entered.wait, 5)
                    response = await asyncio.wait_for(client.get("/api/alert-probe"), 2)
                    assert response.status_code == 200
                    assert response.json() == {"responsive": True}
                    assert not pending.done(), "Price tool completed before the unrelated request"
                finally:
                    release.set()
                    price_response = await asyncio.wait_for(pending, 5)
                assert price_response.status_code == 200
                assert price_response.json()["ok"] is True

    asyncio.run(exercise())
    assert len(seen) == 1
    assert seen[0][0] != event_loop_thread
    assert seen[0][1:] == (mode, "request-scoped")


@pytest.mark.parametrize(("path", "tool_name", "args"), [
    ("/api/prices/stock/EXAMPLE", "stock_price", {"symbol": "EXAMPLE"}),
    ("/api/prices/crypto/BTC", "crypto_price", {"coin": "btc"}),
    ("/api/prices/crypto/ETH/chart?days=30&vs_currency=EUR&points_limit=12", "crypto_chart",
     {"coin": "eth", "days": "30", "vs_currency": "eur", "points_limit": 12}),
])
@pytest.mark.parametrize("ok", [False, True])
def test_single_price_routes_preserve_arguments_payloads_and_errors(
    price_api, monkeypatch, path, tool_name, args, ok,
):
    module, app = price_api
    calls = []
    payload = {"ok": ok, "data": {"price_usd": 123.45}, "error": "Price unavailable"}

    def tool(name, actual_args):
        calls.append((name, actual_args))
        return payload

    monkeypatch.setattr(module, "call_tool", tool)

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(path)
            assert response.status_code == (200 if ok else 404)
            assert response.json() == (payload if ok else {"detail": "Price unavailable"})

    asyncio.run(exercise())
    assert calls == [(tool_name, args)]


def test_batch_preserves_sequential_stock_calls_and_one_batched_crypto_call(price_api, monkeypatch):
    module, app = price_api
    calls = []

    def tool(name, args):
        calls.append((name, args))
        if name == "stock_price":
            if args["symbol"] == "BAD":
                return {"ok": False, "error": "No quote"}
            return {"ok": True, "data": {
                "price_usd": 0, "change_today_percent": -1, "company": "Example"}}
        return {"ok": True, "data": {"coins": [
            {"coin_id": "bitcoin", "requested": "btc", "coin": "Bitcoin", "price_usd": 10,
             "change_24h_percent": 2},
            {"coin_id": "sol", "coin": "Solana", "price_usd": 20, "change_24h_percent": 3},
        ]}}

    monkeypatch.setattr(module, "call_tool", tool)

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/prices/batch", params={
                "stocks": "GOOD, ,BAD", "crypto": "BTC, sol, missing"})
            assert response.status_code == 200
            assert response.json() == {"ok": True, "stocks": {
                "GOOD": {"price": 0, "change_percent": -1, "name": "Example"},
                "BAD": {"error": "No quote"},
            }, "crypto": {
                "BTC": {"price": 10, "change_percent": 2, "name": "Bitcoin"},
                "sol": {"price": 20, "change_percent": 3, "name": "Solana"},
                "missing": {"error": "No data found for 'missing'."},
            }}

    asyncio.run(exercise())
    assert calls == [
        ("stock_price", {"symbol": "GOOD"}),
        ("stock_price", {"symbol": "BAD"}),
        ("crypto_price", {"coins": ["btc", "sol", "missing"]}),
    ]

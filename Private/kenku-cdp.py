"""Выполнить JS в окне Kenku FM через Chrome DevTools Protocol.

Использование:
    python kenku-cdp.py <заголовок-окна> <файл-со-скриптом-js>
"""
import json
import sys
import urllib.request

import websocket

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def targets():
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list") as response:
        return json.load(response)


def evaluate(ws_url, expression):
    ws = websocket.create_connection(ws_url, timeout=20, suppress_origin=True)
    try:
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True,
                       "awaitPromise": True},
        }))
        while True:
            message = json.loads(ws.recv())
            if message.get("id") == 1:
                return message
    finally:
        ws.close()


def main():
    title, script_path = sys.argv[1], sys.argv[2]
    target = next(t for t in targets() if t["title"] == title)
    with open(script_path, encoding="utf-8") as handle:
        expression = handle.read()
    result = evaluate(target["webSocketDebuggerUrl"], expression)
    if "exceptionDetails" in result.get("result", {}):
        print("ОШИБКА:", json.dumps(result["result"]["exceptionDetails"],
                                    ensure_ascii=False)[:2000])
        sys.exit(1)
    print(json.dumps(result["result"]["result"].get("value"),
                     ensure_ascii=False, indent=2)[:6000])


if __name__ == "__main__":
    main()

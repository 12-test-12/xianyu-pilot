"""Start the original API's SQLite adaptation without external services."""
import argparse
import os


def main():
    parser = argparse.ArgumentParser(description="闲鱼助手 SQLite 存储基础（业务接口适配中）")
    parser.add_argument("--port", type=int, default=15177)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口须为 1024–65535")
    os.environ["RUNTIME_MODE"] = "desktop"
    os.environ["DESKTOP_PORT"] = str(args.port)
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, workers=1, reload=False)


if __name__ == "__main__":
    main()

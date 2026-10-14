"""Start the shop on Botkeep or another persistent Python host."""
import os
from pathlib import Path

from dotenv import load_dotenv
import uvicorn


def main():
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env", override=False)
    os.chdir(root)
    raw_port = os.getenv("SERVER_PORT") or os.getenv("PORT") or "8000"
    try:
        port = int(raw_port)
    except ValueError:
        raise SystemExit("SERVER_PORT/PORT must be an integer") from None
    if not 1 <= port <= 65535:
        raise SystemExit("SERVER_PORT/PORT must be between 1 and 65535")
    uvicorn.run("app:app", host="0.0.0.0", port=port, workers=1)


if __name__ == "__main__":
    main()

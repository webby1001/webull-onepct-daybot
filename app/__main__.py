"""python -m app"""

import uvicorn

from app.config import get_settings


def main() -> None:
    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, reload=False)


if __name__ == "__main__":
    main()

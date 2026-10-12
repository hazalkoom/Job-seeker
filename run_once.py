import json

from app.runner import run_once

if __name__ == "__main__":
    print(json.dumps(run_once(), indent=2, ensure_ascii=False))

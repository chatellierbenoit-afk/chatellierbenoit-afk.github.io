import json
import ssl
import urllib.request
import zipfile
from io import BytesIO

AMO50_URL = "http://data.assemblee-nationale.fr/static/openData/repository/17/amo/acteurs_mandats_organes_divises/AMO50_acteurs_mandats_organes_divises.json.zip"

SSL_CONTEXT = ssl.create_default_context()

def download_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(request, context=SSL_CONTEXT, timeout=120) as response:
        return response.read()

def summarize(obj, depth=0, max_depth=3):
    indent = "  " * depth
    if depth > max_depth:
        print(f"{indent}...")
        return

    if isinstance(obj, dict):
        print(f"{indent}dict keys={list(obj.keys())[:15]}")
        for key, value in list(obj.items())[:5]:
            print(f"{indent}- key: {key}")
            summarize(value, depth + 1, max_depth)
    elif isinstance(obj, list):
        print(f"{indent}list len={len(obj)}")
        if obj:
            summarize(obj[0], depth + 1, max_depth)
    else:
        print(f"{indent}{type(obj).__name__}: {str(obj)[:120]}")

def main():
    raw = download_bytes(AMO50_URL)

    with zipfile.ZipFile(BytesIO(raw)) as zf:
        print("FICHIERS DANS L'ARCHIVE :")
        for name in zf.namelist():
            print("-", name)

        for name in zf.namelist():
            if not name.lower().endswith(".json"):
                continue

            print()
            print("=" * 80)
            print("FICHIER :", name)
            data = json.loads(zf.read(name).decode("utf-8"))
            summarize(data)

if __name__ == "__main__":
    main()

import json
import ssl
import urllib.request
import zipfile
from io import BytesIO

SCRUTINS_URL = "http://data.assemblee-nationale.fr/static/openData/repository/17/loi/scrutins/Scrutins.json.zip"
AMO50_URL = "http://data.assemblee-nationale.fr/static/openData/repository/17/amo/acteurs_mandats_organes_divises/AMO50_acteurs_mandats_organes_divises.json.zip"

SSL_CONTEXT = ssl.create_default_context()

def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=120) as r:
        return r.read()

def show_sample(zf, prefix: str, limit: int = 1):
    matches = [n for n in zf.namelist() if n.startswith(prefix) and n.endswith(".json")]
    print(f"{prefix} -> {len(matches)} fichier(s)")
    for name in matches[:limit]:
        print(f"--- SAMPLE {name}")
        data = json.loads(zf.read(name).decode("utf-8"))
        print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])

def main():
    print("TEST URL SCRUTINS...")
    raw_scrutins = download(SCRUTINS_URL)
    with zipfile.ZipFile(BytesIO(raw_scrutins)) as zf:
        print("SCRUTINS ZIP OK")
        print("Premier fichier:", zf.namelist()[0])

    print()
    print("TEST URL AMO50...")
    raw_amo = download(AMO50_URL)
    with zipfile.ZipFile(BytesIO(raw_amo)) as zf:
        names = zf.namelist()
        print("AMO50 ZIP OK")
        print("Nombre total de fichiers:", len(names))

        show_sample(zf, "acteur/")
        print()
        show_sample(zf, "organe/")
        print()
        show_sample(zf, "mandat/")

if __name__ == "__main__":
    main()

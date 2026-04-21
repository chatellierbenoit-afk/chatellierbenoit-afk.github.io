import json
import ssl
import urllib.request
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path


TARGET_YEAR = "2025"

SCRUTINS_URL = "http://data.assemblee-nationale.fr/static/openData/repository/17/loi/scrutins/Scrutins.json.zip"
AMO50_URL = "http://data.assemblee-nationale.fr/static/openData/repository/17/amo/acteurs_mandats_organes_divises/AMO50_acteurs_mandats_organes_divises.json.zip"

BASE_DIR = Path("data/current")
ARCHIVE_DIR = Path(f"data/archives/{TARGET_YEAR}")

INDEX_FILE = BASE_DIR / "index.json"
SCRUTINS_FILE = BASE_DIR / "scrutins.json"

SSL_CONTEXT = ssl.create_default_context()


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data):
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def download(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=120) as r:
        return r.read()


def ensure_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def clean_text(value):
    if value is None:
        return ""
    return " ".join(str(value).replace("\u00a0", " ").split()).strip()


def get_uid(value):
    if isinstance(value, dict):
        return clean_text(value.get("#text") or value.get("uid") or "")
    return clean_text(value)


def load_amo50():
    print("Chargement AMO50…")
    raw = download(AMO50_URL)
    zf = zipfile.ZipFile(BytesIO(raw))

    actor_meta = {}
    organes = {}

    for name in zf.namelist():
        if name.startswith("acteur/") and name.endswith(".json"):
            data = json.loads(zf.read(name).decode("utf-8"))
            acteur = data.get("acteur", {})

            uid = get_uid(acteur.get("uid"))
            ident = acteur.get("etatCivil", {}).get("ident", {})

            prenom = clean_text(ident.get("prenom") or "")
            nom = clean_text(ident.get("nom") or "")
            nom_complet = clean_text(f"{prenom} {nom}")

            actor_meta[uid] = {
                "uid": uid,
                "nom": nom_complet or uid,
                "groupe": "",
                "departement": "",
                "circonscription": "",
            }

        elif name.startswith("organe/") and name.endswith(".json"):
            data = json.loads(zf.read(name).decode("utf-8"))
            organe = data.get("organe", {})

            uid = clean_text(organe.get("uid"))

            dep = ""
            lieu = organe.get("lieu", {})
            if isinstance(lieu, dict):
                dep_obj = lieu.get("departement", {})
                if isinstance(dep_obj, dict):
                    dep = clean_text(dep_obj.get("libelle"))

            organes[uid] = {
                "codeType": clean_text(organe.get("codeType")),
                "libelle": clean_text(organe.get("libelle")),
                "libelleAbrev": clean_text(organe.get("libelleAbrev")),
                "libelleAbrege": clean_text(organe.get("libelleAbrege")),
                "departement": dep,
            }

    for name in zf.namelist():
        if not name.startswith("mandat/"):
            continue

        data = json.loads(zf.read(name).decode("utf-8"))
        mandat = data.get("mandat", {})

        acteur_ref = clean_text(mandat.get("acteurRef"))
        if acteur_ref not in actor_meta:
            continue

        if clean_text(mandat.get("legislature")) != "17":
            continue

        organes_block = mandat.get("organes", {})
        organe_refs = ensure_list(organes_block.get("organeRef")) if isinstance(organes_block, dict) else []

        latest_dep = ""
        latest_circo = ""

        for org_ref in organe_refs:
            org = organes.get(clean_text(org_ref), {})
            code = org.get("codeType")

            if code == "CIRCONSCRIPTION":
                latest_dep = org.get("departement")
                latest_circo = org.get("libelle")

            if code == "GP":
                groupe = org.get("libelleAbrev") or org.get("libelleAbrege") or org.get("libelle")
                if groupe:
                    actor_meta[acteur_ref]["groupe"] = groupe

        if latest_dep:
            actor_meta[acteur_ref]["departement"] = latest_dep
            actor_meta[acteur_ref]["circonscription"] = latest_circo

    print("Acteurs :", len(actor_meta))
    print("Organes :", len(organes))

    return actor_meta, organes


def load_scrutins(actor_meta, organes):
    print("Chargement scrutins…")
    raw = download(SCRUTINS_URL)
    zf = zipfile.ZipFile(BytesIO(raw))

    scrutins = []

    for name in zf.namelist():
        if not name.endswith(".json"):
            continue

        data = json.loads(zf.read(name).decode("utf-8"))
        scrutin = data.get("scrutin", data)

        date = clean_text(scrutin.get("dateScrutin"))
        if not date.startswith(TARGET_YEAR):
            continue

        votes = []

        groupes = ensure_list(
            ((scrutin.get("ventilationVotes") or {}).get("organe") or {}).get("groupes", {}).get("groupe")
        )

        for g in groupes:
            decompte = (g.get("vote") or {}).get("decompteNominatif", {})

            for key, label in [
                ("pours", "Pour"),
                ("contres", "Contre"),
                ("abstentions", "Abstention"),
                ("nonVotants", "Non-votant"),
            ]:
                bucket = decompte.get(key) or {}
                for v in ensure_list(bucket.get("votant")):
                    uid = clean_text(v.get("acteurRef"))
                    dep = actor_meta.get(uid, {})

                    votes.append({
                        "depute_uid": uid,
                        "nom": dep.get("nom"),
                        "groupe": dep.get("groupe"),
                        "vote": label,
                        "departement": dep.get("departement")
                    })

        if votes:
            scrutins.append({
                "date": date,
                "votes": votes
            })

    return scrutins


def main():
    actor_meta, organes = load_amo50()
    scrutins = load_scrutins(actor_meta, organes)

    total_votes = sum(len(s["votes"]) for s in scrutins)
    updated_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    index_data = {
        "version": "2.0",
        "year": int(TARGET_YEAR),
        "updated_at": updated_at,
        "counts": {
            "scrutins": len(scrutins),
            "votes": total_votes
        },
        "files": {
            "scrutins": "data/current/scrutins.json"
        }
    }

    scrutins_data = {
        "year": int(TARGET_YEAR),
        "updated_at": updated_at,
        "scrutins": scrutins
    }

    write_json(INDEX_FILE, index_data)
    write_json(SCRUTINS_FILE, scrutins_data)
    write_json(
        ARCHIVE_DIR / f"{datetime.utcnow().strftime('%Y-%m-%d')}.json",
        scrutins_data
    )

    print(f"Scrutins : {len(scrutins)}")
    print(f"Votes : {total_votes}")


if __name__ == "__main__":
    main()

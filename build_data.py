import json
import ssl
import urllib.request
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from collections import defaultdict


TARGET_YEAR = "2025"

SCRUTINS_URL = "http://data.assemblee-nationale.fr/static/openData/repository/17/loi/scrutins/Scrutins.json.zip"
AMO50_URL = "http://data.assemblee-nationale.fr/static/openData/repository/17/amo/acteurs_mandats_organes_divises/AMO50_acteurs_mandats_organes_divises.json.zip"

BASE_DIR = Path("data/current")
MONTHS_DIR = BASE_DIR / "months"
INDEX_FILE = BASE_DIR / "index.json"

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
            actor_meta[uid] = {
                "uid": uid,
                "nom": clean_text(f"{prenom} {nom}") or uid,
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
                latest_dep = org.get("departement") or ""
                latest_circo = org.get("libelle") or ""

            if code == "GP":
                groupe = org.get("libelleAbrev") or org.get("libelleAbrege") or org.get("libelle") or ""
                if groupe:
                    actor_meta[acteur_ref]["groupe"] = groupe

        if latest_dep:
            actor_meta[acteur_ref]["departement"] = latest_dep
            actor_meta[acteur_ref]["circonscription"] = latest_circo

    print("Acteurs :", len(actor_meta))
    print("Organes :", len(organes))
    return actor_meta, organes


def build_group_summary(votes):
    by_group = defaultdict(lambda: {"pour": 0, "contre": 0, "abstention": 0, "non_votant": 0, "total": 0})

    for v in votes:
        g = v.get("groupe") or "Inconnu"
        by_group[g]["total"] += 1
        if v["vote"] == "Pour":
            by_group[g]["pour"] += 1
        elif v["vote"] == "Contre":
            by_group[g]["contre"] += 1
        elif v["vote"] == "Abstention":
            by_group[g]["abstention"] += 1
        elif v["vote"] == "Non-votant":
            by_group[g]["non_votant"] += 1

    return [
        {
            "groupe": groupe,
            **stats
        }
        for groupe, stats in sorted(by_group.items())
    ]


def load_scrutins(actor_meta):
    print("Chargement scrutins…")
    raw = download(SCRUTINS_URL)
    zf = zipfile.ZipFile(BytesIO(raw))

    by_month = defaultdict(list)
    total_votes = 0

    for name in zf.namelist():
        if not name.endswith(".json"):
            continue

        data = json.loads(zf.read(name).decode("utf-8"))
        scrutin = data.get("scrutin", data)

        date = clean_text(scrutin.get("dateScrutin"))
        if not date.startswith(TARGET_YEAR):
            continue

        uid = clean_text(scrutin.get("uid") or scrutin.get("numero") or "")
        numero = scrutin.get("numero")
        titre = clean_text(scrutin.get("titre")) or f"Scrutin n°{numero}"
        description = clean_text(((scrutin.get("objet") or {}).get("libelle")) or ((scrutin.get("objet") or {}).get("titre")) or "")

        votes = []

        groupes = ensure_list(
            ((scrutin.get("ventilationVotes") or {}).get("organe") or {}).get("groupes", {}).get("groupe")
        )

        for g in groupes:
            decompte = (g.get("vote") or {}).get("decompteNominatif", {})
            groupe_nom = clean_text(g.get("libelle") or "")

            for key, label in [
                ("pours", "Pour"),
                ("contres", "Contre"),
                ("abstentions", "Abstention"),
                ("nonVotants", "Non-votant"),
            ]:
                bucket = decompte.get(key) or {}
                for v in ensure_list(bucket.get("votant")):
                    uid_dep = clean_text(v.get("acteurRef"))
                    depute = actor_meta.get(uid_dep, {})

                    votes.append({
                        "depute_uid": uid_dep,
                        "nom": depute.get("nom") or uid_dep,
                        "groupe": depute.get("groupe") or groupe_nom or "Inconnu",
                        "vote": label,
                        "departement": depute.get("departement") or ""
                    })

        if not votes:
            continue

        total_votes += len(votes)
        month_key = date[:7]

        by_month[month_key].append({
            "uid": uid,
            "numero": numero,
            "date": date,
            "titre": titre,
            "description": description,
            "votes_count": len(votes),
            "groupes_summary": build_group_summary(votes),
            "votes": votes
        })

    return by_month, total_votes


def main():
    actor_meta, organes = load_amo50()
    by_month, total_votes = load_scrutins(actor_meta)

    months_index = []
    total_scrutins = 0

    for month in sorted(by_month.keys()):
        scrutins = sorted(by_month[month], key=lambda x: x["date"], reverse=True)
        total_scrutins += len(scrutins)

        file_path = MONTHS_DIR / f"{month}.json"
        write_json(file_path, {
            "month": month,
            "year": int(TARGET_YEAR),
            "scrutins": scrutins
        })

        months_index.append({
            "month": month,
            "file": f"data/current/months/{month}.json",
            "scrutins": len(scrutins)
        })

    updated_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    write_json(INDEX_FILE, {
        "version": "2.1",
        "year": int(TARGET_YEAR),
        "updated_at": updated_at,
        "counts": {
            "scrutins": total_scrutins,
            "votes": total_votes
        },
        "months": months_index
    })

    print(f"Scrutins : {total_scrutins}")
    print(f"Votes : {total_votes}")
    print(f"Mois générés : {len(months_index)}")


if __name__ == "__main__":
    main()

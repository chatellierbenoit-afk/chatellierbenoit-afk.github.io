import json
import ssl
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime
from io import BytesIO
from pathlib import Path

MIN_YEAR = 2024

SCRUTINS_URL = "http://data.assemblee-nationale.fr/static/openData/repository/17/loi/scrutins/Scrutins.json.zip"
AMO50_URL = "http://data.assemblee-nationale.fr/static/openData/repository/17/amo/acteurs_mandats_organes_divises/AMO50_acteurs_mandats_organes_divises.json.zip"

BASE_DIR = Path("data/current")
MONTHS_DIR = BASE_DIR / "months"

SSL_CONTEXT = ssl.create_default_context()


def ensure_dir(path):
    path.mkdir(parents=True, exist_ok=True)


def write_json(path, data):
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=SSL_CONTEXT) as r:
        return r.read()


def ensure_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def clean(v):
    return "" if v is None else str(v).strip()


def get_uid(v):
    if isinstance(v, dict):
        return clean(v.get("#text"))
    return clean(v)


# 🔥 extraction robuste
def extract_votants(node):
    result = []

    if isinstance(node, dict):
        if "votant" in node:
            result.extend(ensure_list(node["votant"]))
        elif "acteurRef" in node:
            result.append(node)
        else:
            for v in node.values():
                result.extend(extract_votants(v))

    elif isinstance(node, list):
        for item in node:
            result.extend(extract_votants(item))

    return result


# ======================
# ACTEURS + GROUPES
# ======================

def load_amo():
    raw = download(AMO50_URL)
    zf = zipfile.ZipFile(BytesIO(raw))

    actors = {}
    organes = {}

    for name in zf.namelist():

        if name.startswith("acteur/"):
            data = json.loads(zf.read(name))
            a = data.get("acteur", {})

            uid = get_uid(a.get("uid"))
            ident = a.get("etatCivil", {}).get("ident", {})

            nom = f"{clean(ident.get('prenom'))} {clean(ident.get('nom'))}".strip()

            actors[uid] = {
                "nom": nom,
                "groupe": "",
                "departement": ""
            }

        elif name.startswith("organe/"):
            data = json.loads(zf.read(name))
            o = data.get("organe", {})

            uid = clean(o.get("uid"))

            dep = ""
            lieu = o.get("lieu", {})
            if isinstance(lieu, dict):
                d = lieu.get("departement", {})
                if isinstance(d, dict):
                    dep = clean(d.get("libelle"))

            organes[uid] = {
                "type": clean(o.get("codeType")),
                "nom": clean(o.get("libelleAbrev") or o.get("libelle")),
                "departement": dep
            }

    # mandats
    for name in zf.namelist():
        if not name.startswith("mandat/"):
            continue

        data = json.loads(zf.read(name))
        m = data.get("mandat", {})

        if clean(m.get("legislature")) != "17":
            continue

        acteur = clean(m.get("acteurRef"))
        if acteur not in actors:
            continue

        refs = ensure_list(m.get("organes", {}).get("organeRef"))

        for ref in refs:
            o = organes.get(clean(ref), {})

            if o.get("type") == "GP":
                actors[acteur]["groupe"] = o.get("nom")

            if o.get("type") == "CIRCONSCRIPTION":
                actors[acteur]["departement"] = o.get("departement")

    return actors


# ======================
# SCRUTINS
# ======================

def compute_stats(votes):
    return {
        "pour": sum(1 for v in votes if v["vote"] == "Pour"),
        "contre": sum(1 for v in votes if v["vote"] == "Contre"),
        "abstention": sum(1 for v in votes if v["vote"] == "Abstention"),
        "non_votant": sum(1 for v in votes if v["vote"] == "Non-votant"),
        "total_votes": len(votes)
    }


def compute_groupes(votes):
    grouped = defaultdict(list)
    for v in votes:
        grouped[v["groupe"]].append(v)

    result = []
    for g, items in grouped.items():
        stats = compute_stats(items)
        result.append({
            "groupe": g,
            "pour": stats["pour"],
            "contre": stats["contre"],
            "abstention": stats["abstention"],
            "non_votant": stats["non_votant"],
            "total": stats["total_votes"]
        })

    return sorted(result, key=lambda x: x["groupe"])


def load_scrutins(actors):
    raw = download(SCRUTINS_URL)
    zf = zipfile.ZipFile(BytesIO(raw))

    scrutins = []

    for name in zf.namelist():
        data = json.loads(zf.read(name))
        s = data.get("scrutin", data)

        date = clean(s.get("dateScrutin"))
        if not date:
            continue

        if int(date[:4]) < MIN_YEAR:
            continue

        votes = []

        groupes = ensure_list(
            s.get("ventilationVotes", {})
             .get("organe", {})
             .get("groupes", {})
             .get("groupe")
        )

        for g in groupes:

            decompte = (g.get("vote") or {}).get("decompteNominatif", {})

            for key, label in [
                ("pours", "Pour"),
                ("contres", "Contre"),
                ("abstentions", "Abstention"),
                ("nonVotants", "Non-votant"),
            ]:
                votants = extract_votants(decompte.get(key))

                for v in votants:
                    uid = clean(v.get("acteurRef"))
                    dep = actors.get(uid, {})

                    votes.append({
                        "depute_uid": uid,
                        "nom": dep.get("nom") or uid,
                        "groupe": dep.get("groupe") or "Inconnu",
                        "vote": label,
                        "departement": dep.get("departement", "")
                    })

        if not votes:
            continue

        stats = compute_stats(votes)

        scrutins.append({
            "uid": clean(s.get("uid")),
            "numero": s.get("numero"),
            "date": date,
            "titre": clean(s.get("titre")),
            "description": "",
            "theme": "Autres",
            "stats": stats,
            "groupes_summary": compute_groupes(votes),
            "departements_summary": [],
            "votes": votes
        })

    return scrutins


# ======================
# BUILD
# ======================

def main():
    actors = load_amo()
    scrutins = load_scrutins(actors)

    months = defaultdict(list)

    for s in scrutins:
        m = s["date"][:7]
        months[m].append(s)

    month_list = []

    for m, data in months.items():
        path = f"data/current/months/{m}.json"

        write_json(
            MONTHS_DIR / f"{m}.json",
            {
                "month": m,
                "year": int(m[:4]),
                "scrutins": data
            }
        )

        month_list.append({
            "month": m,
            "file": path,
            "scrutins": len(data)
        })

    total_votes = sum(s["stats"]["total_votes"] for s in scrutins)

    index = {
        "version": "2.2",
        "year": 2025,
        "updated_at": datetime.utcnow().isoformat(),
        "counts": {
            "scrutins": len(scrutins),
            "votes": total_votes,
            "deputes": len(actors),
            "groupes": len(set(a["groupe"] for a in actors.values() if a["groupe"])),
            "departements": len(set(a["departement"] for a in actors.values() if a["departement"]))
        },
        "months": sorted(month_list, key=lambda x: x["month"], reverse=True)
    }

    write_json(BASE_DIR / "index.json", index)

    print("Scrutins :", len(scrutins))
    print("Votes :", total_votes)
    print("Mois :", len(month_list))


if __name__ == "__main__":
    main()

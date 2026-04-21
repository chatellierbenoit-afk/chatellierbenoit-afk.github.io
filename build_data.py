import json
import ssl
import urllib.request
import zipfile
from collections import defaultdict
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
DEPUTES_FILE = BASE_DIR / "deputes.json"
GROUPES_FILE = BASE_DIR / "groupes.json"
DEPARTEMENTS_FILE = BASE_DIR / "departements.json"

SSL_CONTEXT = ssl.create_default_context()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def download(url: str) -> bytes:
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
        return clean_text(value.get("#text") or value.get("uid") or value.get("text") or "")
    return clean_text(value)


def normalize_vote_label(value):
    mapping = {
        "pour": "Pour",
        "pours": "Pour",
        "contre": "Contre",
        "contres": "Contre",
        "abstention": "Abstention",
        "abstentions": "Abstention",
        "non-votant": "Non-votant",
        "non-votants": "Non-votant",
        "non votant": "Non-votant",
        "non votants": "Non-votant",
        "nonvotant": "Non-votant",
        "nonvotants": "Non-votant",
    }
    raw = clean_text(value).lower()
    return mapping.get(raw, value or "Inconnu")


def guess_theme(text):
    t = clean_text(text).lower()
    rules = [
        ("Budget / Finances", ["budget", "finance", "fiscal", "plf", "plfr", "plfss", "taxe", "impôt"]),
        ("Santé", ["santé", "hôpital", "médical", "soin"]),
        ("Éducation", ["éducation", "école", "université", "enseignement"]),
        ("Écologie / Énergie", ["écologie", "climat", "énergie", "environnement"]),
        ("Travail / Social", ["travail", "emploi", "retraite", "social", "salaires", "chômage"]),
        ("Justice / Sécurité", ["justice", "sécurité", "police", "prison", "pénal"]),
        ("Immigration", ["immigration", "asile", "étranger", "mayotte"]),
        ("Institutions", ["motion", "censure", "constitution", "règlement", "procédure"]),
        ("Agriculture", ["agriculture", "aliment"]),
        ("Culture / Médias", ["culture", "audiovisuel", "presse", "patrimoine"]),
        ("Défense / International", ["défense", "armée", "international", "europe"]),
        ("Logement / Transports", ["logement", "transport", "mobilité", "ferroviaire"]),
    ]
    for theme, keywords in rules:
        if any(keyword in t for keyword in keywords):
            return theme
    return "Autres"


def extract_votants_from_bucket(node):
    result = []

    if isinstance(node, dict):
        if "votant" in node:
            result.extend(ensure_list(node["votant"]))
        elif "acteurRef" in node:
            result.append(node)
        else:
            for value in node.values():
                result.extend(extract_votants_from_bucket(value))

    elif isinstance(node, list):
        for item in node:
            result.extend(extract_votants_from_bucket(item))

    return result


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
            etat_civil = acteur.get("etatCivil", {})
            ident = etat_civil.get("ident", {})

            prenom = clean_text(ident.get("prenom") or ident.get("prenomUsuel") or "")
            nom = clean_text(ident.get("nom") or ident.get("nomFamille") or "")
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
            code_type = clean_text(organe.get("codeType"))
            libelle = clean_text(organe.get("libelle"))
            libelle_abrev = clean_text(organe.get("libelleAbrev"))
            libelle_abrege = clean_text(organe.get("libelleAbrege"))

            departement = ""
            lieu = organe.get("lieu", {})
            if isinstance(lieu, dict):
                dep = lieu.get("departement", {})
                if isinstance(dep, dict):
                    departement = clean_text(dep.get("libelle"))

            organes[uid] = {
                "uid": uid,
                "codeType": code_type,
                "libelle": libelle,
                "libelleAbrev": libelle_abrev,
                "libelleAbrege": libelle_abrege,
                "departement": departement,
            }

    for name in zf.namelist():
        if not (name.startswith("mandat/") and name.endswith(".json")):
            continue

        data = json.loads(zf.read(name).decode("utf-8"))
        mandat = data.get("mandat", {})

        acteur_ref = clean_text(mandat.get("acteurRef"))
        if not acteur_ref or acteur_ref not in actor_meta:
            continue

        legislature = clean_text(mandat.get("legislature"))
        if legislature and legislature != "17":
            continue

        organes_block = mandat.get("organes", {})
organe_refs = ensure_list(organes_block.get("organeRef")) if isinstance(organes_block, dict) else []

for org_ref in organe_refs:
    organe_info = organes.get(clean_text(org_ref), {})
    code_type = organe_info.get("codeType", "")

    if code_type == "CIRCONSCRIPTION":
        actor_meta[acteur_ref]["circonscription"] = organe_info.get("libelle", "")
        actor_meta[acteur_ref]["departement"] = organe_info.get("departement", "")

        type_organe = clean_text(mandat.get("typeOrgane"))
        if type_organe == "GP" or code_type == "GP":
            groupe = (
                organe_info.get("libelleAbrev")
                or organe_info.get("libelleAbrege")
                or organe_info.get("libelle")
                or ""
            )
            if groupe:
                actor_meta[acteur_ref]["groupe"] = groupe

        if code_type == "CIRCONSCRIPTION":
            actor_meta[acteur_ref]["circonscription"] = organe_info.get("libelle", "")
            dep = organe_info.get("departement")

if not dep:
    lieu = organe_info.get("lieu", {})
    if isinstance(lieu, dict):
        dep_obj = lieu.get("departement", {})
        if isinstance(dep_obj, dict):
            dep = dep_obj.get("libelle")

actor_meta[acteur_ref]["departement"] = dep or ""
    print("Acteurs :", len(actor_meta))
    print("Organes :", len(organes))
    return actor_meta, organes


def load_scrutins(actor_meta, organes):
    print("Chargement scrutins…")
    raw = download(SCRUTINS_URL)
    zf = zipfile.ZipFile(BytesIO(raw))

    scrutins = []
    json_files = [n for n in zf.namelist() if n.endswith(".json")]
    print("Fichiers scrutins détectés :", len(json_files))

    for name in json_files:
        data = json.loads(zf.read(name).decode("utf-8"))
        scrutin = data.get("scrutin", data)

        date = clean_text(scrutin.get("dateScrutin"))
        if not date.startswith(TARGET_YEAR):
            continue

        uid = clean_text(scrutin.get("uid") or scrutin.get("numero") or "")
        numero = scrutin.get("numero")
        titre = clean_text(scrutin.get("titre"))
        if not titre and numero:
            titre = f"Scrutin n°{numero}"

        objet = scrutin.get("objet", {})
        description = ""
        if isinstance(objet, dict):
            description = clean_text(objet.get("libelle") or objet.get("titre") or "")

        votes = []

        ventilation = scrutin.get("ventilationVotes", {})
        organe = ventilation.get("organe", {})
        groupes = ensure_list((organe.get("groupes") or {}).get("groupe"))

        for groupe in groupes:
            groupe_uid = clean_text(groupe.get("organeRef") or groupe.get("uid") or "")
            groupe_info = organes.get(groupe_uid, {})

            groupe_nom = (
                clean_text(groupe.get("libelle"))
                or groupe_info.get("libelleAbrev")
                or groupe_info.get("libelleAbrege")
                or groupe_info.get("libelle")
                or groupe_uid
                or "Inconnu"
            )

            decompte = (groupe.get("vote") or {}).get("decompteNominatif", {})

            for bucket_key, label in [
                ("pours", "Pour"),
                ("contres", "Contre"),
                ("abstentions", "Abstention"),
                ("nonVotants", "Non-votant"),
            ]:
                bucket = decompte.get(bucket_key)
                votants = extract_votants_from_bucket(bucket)

                for votant in votants:
                    acteur_ref = clean_text(votant.get("acteurRef"))
                    depute = actor_meta.get(acteur_ref, {})

                    votes.append({
                        "depute_uid": acteur_ref,
                        "nom": depute.get("nom") or acteur_ref or "Inconnu",
                        "groupe": depute.get("groupe") or groupe_nom or "Inconnu",
                        "vote": normalize_vote_label(label),
                        "departement": depute.get("departement", "")
                    })

        if not votes:
            continue

        stats = compute_stats(votes)
        groupes_summary = compute_groupes_summary(votes)
        departements_summary = compute_departements_summary(votes)

        scrutins.append({
            "uid": uid,
            "numero": numero,
            "date": date,
            "titre": titre,
            "description": description,
            "theme": guess_theme(f"{titre} {description}"),
            "stats": stats,
            "groupes_summary": groupes_summary,
            "departements_summary": departements_summary,
            "votes": sorted(votes, key=lambda v: (v["groupe"], v["nom"]))
        })

    scrutins.sort(key=lambda s: s["date"], reverse=True)
    return scrutins


def compute_stats(votes):
    pour = sum(1 for v in votes if v["vote"] == "Pour")
    contre = sum(1 for v in votes if v["vote"] == "Contre")
    abstention = sum(1 for v in votes if v["vote"] == "Abstention")
    non_votant = sum(1 for v in votes if v["vote"] == "Non-votant")
    return {
        "pour": pour,
        "contre": contre,
        "abstention": abstention,
        "non_votant": non_votant,
        "total_votes": len(votes)
    }


def compute_groupes_summary(votes):
    grouped = defaultdict(list)
    for v in votes:
        grouped[v["groupe"]].append(v)

    result = []
    for groupe, items in sorted(grouped.items()):
        stats = compute_stats(items)
        result.append({
            "groupe": groupe,
            "pour": stats["pour"],
            "contre": stats["contre"],
            "abstention": stats["abstention"],
            "non_votant": stats["non_votant"],
            "total": stats["total_votes"]
        })
    return result


def compute_departements_summary(votes):
    grouped = defaultdict(list)
    for v in votes:
        dep = v.get("departement", "")
        if dep:
            grouped[dep].append(v)

    result = []
    for dep, items in sorted(grouped.items()):
        stats = compute_stats(items)
        result.append({
            "departement": dep,
            "pour": stats["pour"],
            "contre": stats["contre"],
            "abstention": stats["abstention"],
            "non_votant": stats["non_votant"],
            "total": stats["total_votes"]
        })
    return result


def build_deputes_file(scrutins):
    by_uid = {}

    for scrutin in scrutins:
        for vote in scrutin["votes"]:
            uid = vote["depute_uid"] or vote["nom"]
            if uid not in by_uid:
                by_uid[uid] = {
                    "uid": uid,
                    "nom": vote["nom"],
                    "groupe": vote["groupe"],
                    "departement": vote["departement"],
                    "votes_count": 0,
                    "votes_pour": 0,
                    "votes_contre": 0,
                    "votes_abstention": 0,
                    "votes_non_votant": 0
                }

            by_uid[uid]["votes_count"] += 1
            if vote["vote"] == "Pour":
                by_uid[uid]["votes_pour"] += 1
            elif vote["vote"] == "Contre":
                by_uid[uid]["votes_contre"] += 1
            elif vote["vote"] == "Abstention":
                by_uid[uid]["votes_abstention"] += 1
            elif vote["vote"] == "Non-votant":
                by_uid[uid]["votes_non_votant"] += 1

    return {"deputes": sorted(by_uid.values(), key=lambda d: d["nom"])}


def build_groupes_file(scrutins):
    by_group = {}

    for scrutin in scrutins:
        for vote in scrutin["votes"]:
            groupe = vote["groupe"]
            if groupe not in by_group:
                by_group[groupe] = {
                    "nom": groupe,
                    "deputes_set": set(),
                    "votes_count": 0
                }

            by_group[groupe]["deputes_set"].add(vote["depute_uid"] or vote["nom"])
            by_group[groupe]["votes_count"] += 1

    groupes = []
    for g in sorted(by_group.values(), key=lambda x: x["nom"]):
        groupes.append({
            "nom": g["nom"],
            "deputes_count": len(g["deputes_set"]),
            "votes_count": g["votes_count"]
        })

    return {"groupes": groupes}


def build_departements_file(scrutins):
    by_dep = {}

    for scrutin in scrutins:
        for vote in scrutin["votes"]:
            dep = vote.get("departement", "")
            if not dep:
                continue

            if dep not in by_dep:
                by_dep[dep] = {
                    "nom": dep,
                    "deputes_set": set(),
                    "groupes_set": set(),
                    "votes_count": 0
                }

            by_dep[dep]["deputes_set"].add(vote["depute_uid"] or vote["nom"])
            by_dep[dep]["groupes_set"].add(vote["groupe"])
            by_dep[dep]["votes_count"] += 1

    departements = []
    for d in sorted(by_dep.values(), key=lambda x: x["nom"]):
        departements.append({
            "nom": d["nom"],
            "deputes_count": len(d["deputes_set"]),
            "votes_count": d["votes_count"],
            "groupes": sorted(d["groupes_set"])
        })

    return {"departements": departements}


def main():
    actor_meta, organes = load_amo50()
    scrutins = load_scrutins(actor_meta, organes)

    deputes_file = build_deputes_file(scrutins)
    groupes_file = build_groupes_file(scrutins)
    departements_file = build_departements_file(scrutins)

    deputes_count = len(deputes_file["deputes"])
    groupes_count = len(groupes_file["groupes"])
    departements_count = len(departements_file["departements"])
    total_votes = sum(s["stats"]["total_votes"] for s in scrutins)

    updated_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    index_data = {
        "version": "2.0",
        "year": int(TARGET_YEAR),
        "updated_at": updated_at,
        "counts": {
            "scrutins": len(scrutins),
            "deputes": deputes_count,
            "groupes": groupes_count,
            "departements": departements_count,
            "votes": total_votes
        },
        "files": {
            "scrutins": "data/current/scrutins.json",
            "deputes": "data/current/deputes.json",
            "groupes": "data/current/groupes.json",
            "departements": "data/current/departements.json"
        }
    }

    scrutins_data = {
        "year": int(TARGET_YEAR),
        "updated_at": updated_at,
        "scrutins": scrutins
    }

    write_json(INDEX_FILE, index_data)
    write_json(SCRUTINS_FILE, scrutins_data)
    write_json(DEPUTES_FILE, deputes_file)
    write_json(GROUPES_FILE, groupes_file)
    write_json(DEPARTEMENTS_FILE, departements_file)

    write_json(
        ARCHIVE_DIR / f"{datetime.utcnow().strftime('%Y-%m-%d')}.json",
        scrutins_data
    )

    print(f"Scrutins : {len(scrutins)}")
    print(f"Députés : {deputes_count}")
    print(f"Groupes : {groupes_count}")
    print(f"Départements : {departements_count}")
    print(f"Votes : {total_votes}")


if __name__ == "__main__":
    main()

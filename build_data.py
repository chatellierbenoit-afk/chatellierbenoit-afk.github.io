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

# Mapping explicite des groupes de la XVIIe législature
GROUP_LABELS = {
    "PO845401": "Rassemblement National",
    "PO845407": "Ensemble pour la République",
    "PO845413": "La France insoumise - Nouveau Front Populaire",
    "PO845419": "Socialistes et apparentés",
    "PO845425": "Droite Républicaine",
    "PO845439": "Les Démocrates",
    "PO845454": "Écologiste et Social",
    "PO845470": "Horizons & Indépendants",
    "PO845485": "Libertés, indépendants, outre-mer et territoires",
    "PO845514": "Gauche démocrate et républicaine",
    "PO847173": "UDR",
    "PO840056": "Non inscrits",
    "NI": "Non inscrits",
    "PO872880": "Union des droites pour la République",
    "PO0": "Autre groupe"
}


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
        return clean(v.get("#text") or v.get("uid") or "")
    return clean(v)


def extract_votants(node):
    result = []

    if isinstance(node, dict):
        if "votant" in node:
            result.extend(ensure_list(node["votant"]))
        elif "acteurRef" in node:
            result.append(node)
        else:
            for value in node.values():
                result.extend(extract_votants(value))

    elif isinstance(node, list):
        for item in node:
            result.extend(extract_votants(item))

    return result


def extract_organe_refs(node):
    result = []

    if isinstance(node, dict):
        if "organeRef" in node:
            result.extend(ensure_list(node["organeRef"]))
        else:
            for value in node.values():
                result.extend(extract_organe_refs(value))

    elif isinstance(node, list):
        for item in node:
            result.extend(extract_organe_refs(item))

    return result


def guess_theme(text):
    t = clean(text).lower()
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


def normalize_group_label(value):
    raw = clean(value)
    if raw in GROUP_LABELS:
        return GROUP_LABELS[raw]
    return raw or "Inconnu"


def load_amo():
    raw = download(AMO50_URL)
    zf = zipfile.ZipFile(BytesIO(raw))

    actors = {}
    organes = {}

    for name in zf.namelist():
        if name.startswith("acteur/") and name.endswith(".json"):
            data = json.loads(zf.read(name))
            acteur = data.get("acteur", {})

            uid = get_uid(acteur.get("uid"))
            ident = acteur.get("etatCivil", {}).get("ident", {})

            prenom = clean(ident.get("prenom"))
            nom = clean(ident.get("nom"))
            nom_complet = f"{prenom} {nom}".strip()

            actors[uid] = {
                "uid": uid,
                "nom": nom_complet or uid,
                "groupe": "",
                "departement": "",
                "circonscription": ""
            }

        elif name.startswith("organe/") and name.endswith(".json"):
            data = json.loads(zf.read(name))
            organe = data.get("organe", {})

            uid = clean(organe.get("uid"))
            code_type = clean(organe.get("codeType"))

            lieu = organe.get("lieu", {})
            departement = ""
            if isinstance(lieu, dict):
                dep = lieu.get("departement", {})
                if isinstance(dep, dict):
                    departement = clean(dep.get("libelle"))

            organes[uid] = {
                "uid": uid,
                "codeType": code_type,
                "libelle": clean(organe.get("libelle")),
                "libelleAbrev": clean(organe.get("libelleAbrev")),
                "libelleAbrege": clean(organe.get("libelleAbrege")),
                "departement": departement
            }

    for name in zf.namelist():
        if not name.startswith("mandat/") or not name.endswith(".json"):
            continue

        data = json.loads(zf.read(name))
        mandat = data.get("mandat", {})

        acteur_ref = clean(mandat.get("acteurRef"))
        if acteur_ref not in actors:
            continue

        legislature = clean(mandat.get("legislature"))
        if legislature and legislature != "17":
            continue

        organe_refs = extract_organe_refs(mandat.get("organes", {}))

        for ref in organe_refs:
            ref = clean(ref)
            organe = organes.get(ref, {})
            code_type = organe.get("codeType", "")

            if code_type in {"GP", "GRP"} or clean(mandat.get("typeOrgane")) == "GP":
                groupe = (
                    organe.get("libelleAbrev")
                    or organe.get("libelleAbrege")
                    or organe.get("libelle")
                    or ref
                    or ""
                )
                if groupe:
                    actors[acteur_ref]["groupe"] = normalize_group_label(groupe)

            if code_type == "CIRCONSCRIPTION":
                dep = organe.get("departement", "")
                circo = organe.get("libelle", "")
                if dep:
                    actors[acteur_ref]["departement"] = dep
                if circo:
                    actors[acteur_ref]["circonscription"] = circo

    return actors, organes


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

    for vote in votes:
        grouped[vote["groupe"]].append(vote)

    result = []
    for groupe, items in grouped.items():
        stats = compute_stats(items)
        result.append({
            "groupe": groupe,
            "pour": stats["pour"],
            "contre": stats["contre"],
            "abstention": stats["abstention"],
            "non_votant": stats["non_votant"],
            "total": stats["total_votes"]
        })

    return sorted(result, key=lambda x: x["groupe"])


def compute_departements(votes):
    grouped = defaultdict(list)

    for vote in votes:
        dep = vote.get("departement", "")
        if dep:
            grouped[dep].append(vote)

    result = []
    for dep, items in grouped.items():
        stats = compute_stats(items)
        result.append({
            "departement": dep,
            "pour": stats["pour"],
            "contre": stats["contre"],
            "abstention": stats["abstention"],
            "non_votant": stats["non_votant"],
            "total": stats["total_votes"]
        })

    return sorted(result, key=lambda x: x["departement"])


def load_scrutins(actors, organes):
    raw = download(SCRUTINS_URL)
    zf = zipfile.ZipFile(BytesIO(raw))

    scrutins = []

    for name in zf.namelist():
        if not name.endswith(".json"):
            continue

        data = json.loads(zf.read(name))
        scrutin = data.get("scrutin", data)

        date = clean(scrutin.get("dateScrutin"))
        if not date:
            continue

        year = int(date[:4])
        if year < MIN_YEAR:
            continue

        uid = clean(scrutin.get("uid"))
        numero = scrutin.get("numero")
        titre = clean(scrutin.get("titre")) or f"Scrutin n°{numero}"

        objet = scrutin.get("objet", {})
        description = ""
        if isinstance(objet, dict):
            description = clean(objet.get("libelle") or objet.get("titre") or "")

        groupes = ensure_list(
            ((scrutin.get("ventilationVotes") or {}).get("organe") or {}).get("groupes", {}).get("groupe")
        )

        votes = []

        for groupe_block in groupes:
            groupe_ref = clean(groupe_block.get("organeRef"))
            groupe_organe = organes.get(groupe_ref, {})

            groupe_nom = normalize_group_label(
                groupe_block.get("libelle")
                or groupe_block.get("libelleAbrev")
                or groupe_organe.get("libelleAbrev")
                or groupe_organe.get("libelleAbrege")
                or groupe_organe.get("libelle")
                or groupe_ref
                or ""
            )

            decompte = (groupe_block.get("vote") or {}).get("decompteNominatif", {})

            for key, label in [
                ("pours", "Pour"),
                ("contres", "Contre"),
                ("abstentions", "Abstention"),
                ("nonVotants", "Non-votant"),
            ]:
                votants = extract_votants(decompte.get(key))

                for votant in votants:
                    uid_dep = clean(votant.get("acteurRef"))
                    acteur = actors.get(uid_dep, {})

                    nom = acteur.get("nom") or uid_dep
                    groupe = normalize_group_label(acteur.get("groupe") or groupe_nom or "Inconnu")
                    departement = acteur.get("departement") or ""

                    votes.append({
                        "depute_uid": uid_dep,
                        "nom": nom,
                        "groupe": groupe,
                        "vote": label,
                        "departement": departement
                    })

        if not votes:
            continue

        stats = compute_stats(votes)

        scrutins.append({
            "uid": uid,
            "numero": numero,
            "date": date,
            "titre": titre,
            "description": description,
            "theme": guess_theme(f"{titre} {description}"),
            "stats": stats,
            "groupes_summary": compute_groupes(votes),
            "departements_summary": compute_departements(votes),
            "votes": votes
        })

    return scrutins


def main():
    actors, organes = load_amo()
    scrutins = load_scrutins(actors, organes)

    months = defaultdict(list)

    for scrutin in scrutins:
        month_key = scrutin["date"][:7]
        months[month_key].append(scrutin)

    month_list = []
    for month_key, items in months.items():
        file_path = f"data/current/months/{month_key}.json"

        write_json(
            MONTHS_DIR / f"{month_key}.json",
            {
                "month": month_key,
                "year": int(month_key[:4]),
                "scrutins": sorted(items, key=lambda x: x["date"], reverse=True)
            }
        )

        month_list.append({
            "month": month_key,
            "file": file_path,
            "scrutins": len(items)
        })

    total_votes = sum(s["stats"]["total_votes"] for s in scrutins)
    unique_groupes = sorted({v["groupe"] for s in scrutins for v in s["votes"] if v["groupe"]})
    unique_departements = sorted({v["departement"] for s in scrutins for v in s["votes"] if v["departement"]})

    index_data = {
        "version": "2.6",
        "year": datetime.utcnow().year,
        "updated_at": datetime.utcnow().isoformat(),
        "counts": {
            "scrutins": len(scrutins),
            "votes": total_votes,
            "deputes": len(actors),
            "groupes": len(unique_groupes),
            "departements": len(unique_departements)
        },
        "months": sorted(month_list, key=lambda x: x["month"], reverse=True)
    }

    write_json(BASE_DIR / "index.json", index_data)

    print("Scrutins :", len(scrutins))
    print("Votes :", total_votes)
    print("Députés :", len(actors))
    print("Groupes :", len(unique_groupes))
    print("Départements :", len(unique_departements))
    print("Mois :", len(month_list))


if __name__ == "__main__":
    main()

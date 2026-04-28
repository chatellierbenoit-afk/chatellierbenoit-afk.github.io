import json
import re
import ssl
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from html import unescape
from io import BytesIO
from pathlib import Path

CURRENT_YEAR = datetime.utcnow().year
MIN_YEAR = CURRENT_YEAR - 1

SCRUTINS_URL = "http://data.assemblee-nationale.fr/static/openData/repository/17/loi/scrutins/Scrutins.json.zip"
AMO50_URL = "http://data.assemblee-nationale.fr/static/openData/repository/17/amo/acteurs_mandats_organes_divises/AMO50_acteurs_mandats_organes_divises.json.zip"

BASE_DIR = Path("data/current")
MONTHS_DIR = BASE_DIR / "months"
DEPUTES_FILE = BASE_DIR / "deputes.json"
INDEX_FILE = BASE_DIR / "index.json"

SSL_CONTEXT = ssl.create_default_context()

GROUP_LABELS = {
    "PO845401": "Rassemblement National",
    "RN": "Rassemblement National",
    "RASSEMBLEMENT NATIONAL": "Rassemblement National",

    "PO845407": "Ensemble pour la République",
    "EPR": "Ensemble pour la République",
    "ENSEMBLE POUR LA REPUBLIQUE": "Ensemble pour la République",

    "PO845413": "La France insoumise - Nouveau Front Populaire",
    "LFI-NFP": "La France insoumise - Nouveau Front Populaire",
    "LFI": "La France insoumise - Nouveau Front Populaire",
    "LA FRANCE INSOUMISE - NOUVEAU FRONT POPULAIRE": "La France insoumise - Nouveau Front Populaire",

    "PO845419": "Socialistes et apparentés",
    "SOC": "Socialistes et apparentés",
    "SOCIALISTES ET APPARENTES": "Socialistes et apparentés",

    "PO845425": "Droite Républicaine",
    "DR": "Droite Républicaine",
    "DROITE REPUBLICAINE": "Droite Républicaine",

    "PO845439": "Les Démocrates",
    "DEM": "Les Démocrates",
    "LES DEMOCRATES": "Les Démocrates",

    "PO845454": "Écologiste et Social",
    "ECOS": "Écologiste et Social",
    "ECOLOGISTE ET SOCIAL": "Écologiste et Social",

    "PO845470": "Horizons & Indépendants",
    "HOR": "Horizons & Indépendants",
    "HORIZONS & INDEPENDANTS": "Horizons & Indépendants",
    "HORIZONS ET INDEPENDANTS": "Horizons & Indépendants",

    "PO845485": "Libertés, Indépendants, Outre-mer et Territoires",
    "LIOT": "Libertés, Indépendants, Outre-mer et Territoires",
    "LIBERTES, INDEPENDANTS, OUTRE-MER ET TERRITOIRES": "Libertés, Indépendants, Outre-mer et Territoires",

    "PO845514": "Gauche démocrate et républicaine",
    "GDR": "Gauche démocrate et républicaine",
    "GAUCHE DEMOCRATE ET REPUBLICAINE": "Gauche démocrate et républicaine",

    "PO847173": "UDR",
    "UDR": "UDR",

    "PO872880": "Union des droites pour la République",
    "UNION DES DROITES POUR LA REPUBLIQUE": "Union des droites pour la République",

    "PO840056": "Non inscrits",
    "NI": "Non inscrits",
    "DEPUTES NON INSCRITS": "Non inscrits",
    "NON INSCRITS": "Non inscrits",

    "PO0": "Autre groupe",
}

UNKNOWN_GROUPS = set()
PROFILE_CACHE = {}


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data):
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=120) as r:
        return r.read()


def download_text(url: str) -> str:
    return download(url).decode("utf-8", errors="ignore")


def ensure_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def clean(v):
    if v is None:
        return ""
    return " ".join(str(v).replace("\u00a0", " ").split()).strip()


def normalize_key(text: str) -> str:
    t = clean(text).upper()
    t = (
        t.replace("É", "E").replace("È", "E").replace("Ê", "E").replace("Ë", "E")
        .replace("À", "A").replace("Â", "A")
        .replace("Î", "I").replace("Ï", "I")
        .replace("Ô", "O")
        .replace("Ù", "U").replace("Û", "U").replace("Ü", "U")
        .replace("Ç", "C")
        .replace("’", "'")
    )
    return t


def strip_tags(html_text: str) -> str:
    return clean(re.sub(r"<[^>]+>", " ", html_text))


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
        ("Budget / Finances", ["budget", "finance", "fiscal", "plf", "plfr", "plfss", "taxe", "impôt", "mercosur"]),
        ("Santé", ["santé", "hôpital", "médical", "soin"]),
        ("Éducation", ["éducation", "école", "université", "enseignement"]),
        ("Écologie / Énergie", ["écologie", "climat", "énergie", "environnement"]),
        ("Travail / Social", ["travail", "emploi", "retraite", "social", "salaires", "chômage"]),
        ("Justice / Sécurité", ["justice", "sécurité", "police", "prison", "pénal", "attentat", "rétention"]),
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
    if not raw:
        return ""

    if raw in GROUP_LABELS:
        return GROUP_LABELS[raw]

    norm = normalize_key(raw)
    if norm in GROUP_LABELS:
        return GROUP_LABELS[norm]

    if raw.startswith("PO"):
        UNKNOWN_GROUPS.add(raw)
        return raw

    if norm.startswith("PO"):
        UNKNOWN_GROUPS.add(norm)
        return norm

    return raw


def fetch_depute_profile(uid: str):
    if not uid:
        return {}

    if uid in PROFILE_CACHE:
        return PROFILE_CACHE[uid]

    url = f"https://www.assemblee-nationale.fr/dyn/deputes/{uid}"

    try:
        html = download_text(url)
    except Exception:
        PROFILE_CACHE[uid] = {}
        return {}

    text = strip_tags(unescape(html))

    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title_text = strip_tags(unescape(title_match.group(1))) if title_match else ""

    nom = ""
    if " - " in title_text:
        nom = clean(title_text.split(" - ")[0])
    elif title_text:
        nom = title_text

    departement = ""
    circonscription = ""

    dep_match = re.search(r"((?:Ain|Aisne|Allier|Alpes-de-Haute-Provence|Hautes-Alpes|Alpes-Maritimes|Ardèche|Ardennes|Ariège|Aube|Aude|Aveyron|Bouches-du-Rhône|Calvados|Cantal|Charente|Charente-Maritime|Cher|Corrèze|Corse-du-Sud|Haute-Corse|Côte-d'Or|Côtes-d'Armor|Creuse|Dordogne|Doubs|Drôme|Eure|Eure-et-Loir|Finistère|Gard|Haute-Garonne|Gers|Gironde|Hérault|Ille-et-Vilaine|Indre|Indre-et-Loire|Isère|Jura|Landes|Loir-et-Cher|Loire|Haute-Loire|Loire-Atlantique|Loiret|Lot|Lot-et-Garonne|Lozère|Maine-et-Loire|Manche|Marne|Haute-Marne|Mayenne|Meurthe-et-Moselle|Meuse|Morbihan|Moselle|Nièvre|Nord|Oise|Orne|Pas-de-Calais|Puy-de-Dôme|Pyrénées-Atlantiques|Hautes-Pyrénées|Pyrénées-Orientales|Bas-Rhin|Haut-Rhin|Rhône|Haute-Saône|Saône-et-Loire|Sarthe|Savoie|Haute-Savoie|Paris|Seine-Maritime|Seine-et-Marne|Yvelines|Deux-Sèvres|Somme|Tarn|Tarn-et-Garonne|Var|Vaucluse|Vendée|Vienne|Haute-Vienne|Vosges|Yonne|Territoire de Belfort|Essonne|Hauts-de-Seine|Seine-Saint-Denis|Val-de-Marne|Val-d'Oise|Guadeloupe|Martinique|Guyane|La Réunion|Mayotte))", text, re.IGNORECASE)
    if dep_match:
        departement = clean(dep_match.group(1))

    circ_match = re.search(r"(\d+(?:re|ère|e)?\s+circonscription)", text, re.IGNORECASE)
    if circ_match:
        circonscription = clean(circ_match.group(1))

    group_code_matches = re.findall(r"PO\d{5,}", html)
    groupe = normalize_group_label(group_code_matches[0]) if group_code_matches else ""

    bio = ""
    bio_patterns = [
        r"Biographie(.*?)(?:Mandat en cours|Autres fonctions|Commission|Contact|Question écrite|$)",
        r"N[ée] le .*?(?:\.)",
    ]
    for pattern in bio_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            candidate = clean(match.group(1) if match.lastindex else match.group(0))
            if len(candidate) > 20:
                bio = candidate[:500]
                break

    profile = {
        "nom": nom,
        "groupe": groupe,
        "departement": departement,
        "circonscription": circonscription,
        "bio": bio,
    }
    PROFILE_CACHE[uid] = profile
    return profile


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

            prenom = clean(ident.get("prenom") or ident.get("prenomUsuel"))
            nom = clean(ident.get("nom") or ident.get("nomFamille"))
            nom_complet = f"{prenom} {nom}".strip()

            actors[uid] = {
                "uid": uid,
                "nom": nom_complet or uid,
                "groupe": "",
                "departement": "",
                "circonscription": "",
                "bio": "",
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
                "departement": departement,
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
                groupe = normalize_group_label(
                    organe.get("libelleAbrev")
                    or organe.get("libelleAbrege")
                    or organe.get("libelle")
                    or ref
                )
                if groupe:
                    actors[acteur_ref]["groupe"] = groupe

            if code_type == "CIRCONSCRIPTION":
                dep = organe.get("departement", "")
                circo = organe.get("libelle", "")
                if dep:
                    actors[acteur_ref]["departement"] = dep
                if circo:
                    actors[acteur_ref]["circonscription"] = circo

    for uid, actor in actors.items():
        profile = fetch_depute_profile(uid)

        if profile.get("nom") and actor["nom"] == uid:
            actor["nom"] = profile["nom"]

        if not actor.get("groupe") and profile.get("groupe"):
            actor["groupe"] = profile["groupe"]

        if not actor.get("departement") and profile.get("departement"):
            actor["departement"] = profile["departement"]

        if not actor.get("circonscription") and profile.get("circonscription"):
            actor["circonscription"] = profile["circonscription"]

        if profile.get("bio"):
            actor["bio"] = profile["bio"]

    return actors, organes


def compute_stats(votes):
    return {
        "pour": sum(1 for v in votes if v["vote"] == "Pour"),
        "contre": sum(1 for v in votes if v["vote"] == "Contre"),
        "abstention": sum(1 for v in votes if v["vote"] == "Abstention"),
        "non_votant": sum(1 for v in votes if v["vote"] == "Non-votant"),
        "total_votes": len(votes),
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
            "total": stats["total_votes"],
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
            "total": stats["total_votes"],
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
                    actor = actors.get(uid_dep, {})

                    nom = actor.get("nom") or uid_dep
                    groupe = groupe_nom or actor.get("groupe") or "Inconnu"
                    departement = actor.get("departement") or ""
                    circonscription = actor.get("circonscription") or ""

                    votes.append({
                        "depute_uid": uid_dep,
                        "nom": nom,
                        "groupe": groupe,
                        "vote": label,
                        "departement": departement,
                        "circonscription": circonscription,
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
            "votes": votes,
        })

    return scrutins


def build_deputes_file(scrutins, actors):
    by_uid = {}

    for scrutin in scrutins:
        for vote in scrutin["votes"]:
            uid = vote["depute_uid"]

            if uid not in by_uid:
                actor = actors.get(uid, {})
                by_uid[uid] = {
                    "uid": uid,
                    "nom": vote["nom"],
                    "circonscription": vote.get("circonscription", "") or actor.get("circonscription", ""),
                    "bio": actor.get("bio", ""),
                    "group_counts": Counter(),
                    "votes_count": 0,
                    "votes_pour": 0,
                    "votes_contre": 0,
                    "votes_abstention": 0,
                    "votes_non_votant": 0,
                }

            by_uid[uid]["group_counts"][vote["groupe"]] += 1
            by_uid[uid]["votes_count"] += 1

            if vote["vote"] == "Pour":
                by_uid[uid]["votes_pour"] += 1
            elif vote["vote"] == "Contre":
                by_uid[uid]["votes_contre"] += 1
            elif vote["vote"] == "Abstention":
                by_uid[uid]["votes_abstention"] += 1
            elif vote["vote"] == "Non-votant":
                by_uid[uid]["votes_non_votant"] += 1

            if not by_uid[uid]["circonscription"] and vote.get("circonscription"):
                by_uid[uid]["circonscription"] = vote["circonscription"]

    deputes = []
    for uid, item in by_uid.items():
        actor = actors.get(uid, {})
        dominant_group = item["group_counts"].most_common(1)[0][0] if item["group_counts"] else actor.get("groupe", "")

        deputes.append({
            "uid": uid,
            "nom": item["nom"],
            "groupe": dominant_group,
            "circonscription": item["circonscription"] or actor.get("circonscription", ""),
            "bio": item["bio"] or actor.get("bio", ""),
            "votes_count": item["votes_count"],
            "votes_pour": item["votes_pour"],
            "votes_contre": item["votes_contre"],
            "votes_abstention": item["votes_abstention"],
            "votes_non_votant": item["votes_non_votant"],
        })

    deputes.sort(key=lambda d: d["nom"])
    return {"deputes": deputes}


def main():
    actors, organes = load_amo()
    scrutins = load_scrutins(actors, organes)
    deputes_file = build_deputes_file(scrutins, actors)

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
                "scrutins": sorted(items, key=lambda x: x["date"], reverse=True),
            },
        )

        month_list.append({
            "month": month_key,
            "file": file_path,
            "scrutins": len(items),
        })

    total_votes = sum(s["stats"]["total_votes"] for s in scrutins)
    unique_groupes = sorted({d["groupe"] for d in deputes_file["deputes"] if d["groupe"]})

    index_data = {
        "version": "4.2",
        "year": CURRENT_YEAR,
        "updated_at": datetime.utcnow().isoformat(),
        "counts": {
            "scrutins": len(scrutins),
            "votes": total_votes,
            "deputes": len(deputes_file["deputes"]),
            "groupes": len(unique_groupes),
        },
        "months": sorted(month_list, key=lambda x: x["month"], reverse=True),
        "files": {
            "deputes": "data/current/deputes.json",
        },
    }

    write_json(INDEX_FILE, index_data)
    write_json(DEPUTES_FILE, deputes_file)

    print("Scrutins :", len(scrutins))
    print("Votes :", total_votes)
    print("Députés :", len(deputes_file["deputes"]))
    print("Groupes :", len(unique_groupes))
    print("Mois :", len(month_list))
    print("Groupes inconnus restants :", sorted(UNKNOWN_GROUPS))


if __name__ == "__main__":
    main()

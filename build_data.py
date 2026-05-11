import json
import re
import ssl
import time
import socket
import http.client
import urllib.request
import urllib.error
import zipfile
from collections import defaultdict
from datetime import datetime
from html import unescape
from io import BytesIO
from pathlib import Path

CURRENT_YEAR = datetime.utcnow().year
PREVIOUS_YEAR = CURRENT_YEAR - 1
MIN_YEAR = PREVIOUS_YEAR

SCRUTINS_URL = "https://data.assemblee-nationale.fr/static/openData/repository/17/loi/scrutins/Scrutins.json.zip"
AMO50_URL = "https://data.assemblee-nationale.fr/static/openData/repository/17/amo/acteurs_mandats_organes_divises/AMO50_acteurs_mandats_organes_divises.json.zip"

BASE_DIR = Path("data/current")
MONTHS_DIR = BASE_DIR / "months"

SSL_CONTEXT = ssl.create_default_context()

GROUP_CODE_TO_LABEL = {
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
    "PO872880": "Union des droites pour la République",
    "PO840056": "Non inscrits",
    "NI": "Non inscrits",
}

GROUP_TEXT_ALIASES = {
    "Rassemblement National": "Rassemblement National",
    "Ensemble pour la République": "Ensemble pour la République",
    "La France insoumise - Nouveau Front Populaire": "La France insoumise - Nouveau Front Populaire",
    "Socialistes et apparentés": "Socialistes et apparentés",
    "Droite Républicaine": "Droite Républicaine",
    "Les Démocrates": "Les Démocrates",
    "Écologiste et Social": "Écologiste et Social",
    "Horizons & Indépendants": "Horizons & Indépendants",
    "Horizons et Indépendants": "Horizons & Indépendants",
    "Libertés, indépendants, outre-mer et territoires": "Libertés, indépendants, outre-mer et territoires",
    "Libertés, Indépendants, Outre-mer et Territoires": "Libertés, indépendants, outre-mer et territoires",
    "Gauche démocrate et républicaine": "Gauche démocrate et républicaine",
    "Gauche Démocrate et Républicaine": "Gauche démocrate et républicaine",
    "UDR": "UDR",
    "Union des droites pour la République": "Union des droites pour la République",
    "Non inscrits": "Non inscrits",
    "Non inscrit": "Non inscrits",
    "Ensemble pour la Republique": "Ensemble pour la République",
    "Ecologiste et Social": "Écologiste et Social",
    "Libertes, independants, outre-mer et territoires": "Libertés, indépendants, outre-mer et territoires",
    "Gauche democrate et republicaine": "Gauche démocrate et républicaine",
}

MANUAL_NAME_FIXES = {
    "PA793334": {
        "nom": "Cyril Tribuiani",
        "groupe": "Rassemblement National",
        "departement": "Alpes-Maritimes",
        "circonscription": "6e circonscription",
    },
    "PA721210": {
        "nom": "Alexis Corbière",
        "groupe": "Écologiste et Social",
        "departement": "Seine-Saint-Denis",
        "circonscription": "7e circonscription",
    },
    "PA588884": {
        "nom": "Clémentine Autain",
        "groupe": "Écologiste et Social",
    },
    "PA796018": {
        "nom": "Danielle Simonnet",
        "groupe": "Écologiste et Social",
    },
    "PA722142": {
        "nom": "François Ruffin",
        "groupe": "Écologiste et Social",
    },
    "PA795076": {
        "nom": "Sandrine Rousseau",
        "groupe": "Écologiste et Social",
    },
    "PA794008": {
        "nom": "Cyrielle Chatelain",
        "groupe": "Écologiste et Social",
    },
    "PA793780": {
        "nom": "Christine Arrighi",
        "groupe": "Écologiste et Social",
    },
    "PA793452": {
        "nom": "Hendrik Davi",
        "groupe": "Écologiste et Social",
    },
}

UNKNOWN_GROUPS = set()
PROFILE_CACHE = {}

EXPECTED_ASSEMBLY_SIZE = 577

OFFICIAL_COMPOSITION = {
    "Rassemblement National": 122,
    "Ensemble pour la République": 91,
    "La France insoumise - Nouveau Front Populaire": 71,
    "Socialistes et apparentés": 68,
    "Droite Républicaine": 48,
    "Écologiste et Social": 38,
    "Les Démocrates": 37,
    "Horizons & Indépendants": 35,
    "Libertés, indépendants, outre-mer et territoires": 23,
    "Union des droites pour la République": 17,
    "Gauche démocrate et républicaine": 17,
    "Non inscrits": 10,
}


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data):
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def read_json_if_exists(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def download(url: str, retries: int = 5, pause: float = 3.0, chunk_size: int = 1024 * 256) -> bytes:
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "*/*",
                    "Connection": "close",
                },
            )

            with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=240) as r:
                chunks = []
                while True:
                    chunk = r.read(chunk_size)
                    if not chunk:
                        break
                    chunks.append(chunk)

                data = b"".join(chunks)
                if not data:
                    raise ValueError(f"Téléchargement vide pour {url}")

                return data

        except (http.client.IncompleteRead, urllib.error.URLError, socket.timeout, TimeoutError, ConnectionResetError, ValueError) as e:
            last_error = e
            print(f"Téléchargement échoué ({attempt}/{retries}) pour {url} : {e}")
            if attempt < retries:
                time.sleep(pause * attempt)

        except Exception as e:
            last_error = e
            print(f"Erreur inattendue ({attempt}/{retries}) pour {url} : {e}")
            if attempt < retries:
                time.sleep(pause * attempt)

    raise last_error


def download_zip(url: str, retries: int = 5, pause: float = 3.0) -> bytes:
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            data = download(url, retries=1, pause=0)

            if len(data) < 4 or data[:2] != b"PK":
                preview = data[:200].decode("utf-8", errors="ignore")
                raise ValueError(f"Réponse non ZIP pour {url}. Début reçu: {preview!r}")

            return data

        except Exception as e:
            last_error = e
            print(f"Téléchargement ZIP invalide ({attempt}/{retries}) pour {url} : {e}")
            if attempt < retries:
                time.sleep(pause * attempt)

    raise last_error


def download_text(url: str) -> str:
    return download(url).decode("utf-8", errors="ignore")


def ensure_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def clean(v) -> str:
    if v is None:
        return ""
    return " ".join(str(v).replace("\u00a0", " ").split()).strip()


def strip_tags(html_text: str) -> str:
    return clean(re.sub(r"<[^>]+>", " ", html_text))


def get_uid(v) -> str:
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


def normalize_group_label(value: str) -> str:
    raw = clean(value)

    if not raw:
        return "Inconnu"

    if raw in GROUP_CODE_TO_LABEL:
        return GROUP_CODE_TO_LABEL[raw]

    if raw in GROUP_TEXT_ALIASES:
        return GROUP_TEXT_ALIASES[raw]

    if raw.startswith("PO"):
        UNKNOWN_GROUPS.add(raw)
        return "Inconnu"

    return raw


def normalize_circonscription_label(value: str) -> str:
    raw = clean(value)
    if not raw:
        return ""
    raw = raw.replace("1ère", "1re").replace("2ème", "2e").replace("3ème", "3e").replace("4ème", "4e")
    raw = raw.replace("5ème", "5e").replace("6ème", "6e").replace("7ème", "7e").replace("8ème", "8e")
    raw = raw.replace("9ème", "9e").replace("10ème", "10e")
    return raw


def apply_manual_fix(uid: str, actor: dict) -> dict:
    fix = MANUAL_NAME_FIXES.get(uid)
    if not fix:
        return actor

    actor = actor or {
        "uid": uid,
        "nom": "",
        "groupe": "",
        "departement": "",
        "circonscription": "",
        "bio": "",
        "mandat_en_cours": False,
    }

    for key in ["nom", "groupe", "departement", "circonscription", "bio"]:
        value = clean(fix.get(key))
        if value:
            actor[key] = value

    return actor


def extract_meta_description(html: str) -> str:
    m = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if m:
        return clean(unescape(m.group(1)))
    return ""


def extract_group_from_description(description: str) -> str:
    desc = clean(description)

    patterns = [
        r"déput[ée]\s+du groupe\s+(.+?)(?:\s*[.,]|$)",
        r"membre du groupe\s+(.+?)(?:\s*[.,]|$)",
        r"apparent[ée] au groupe\s+(.+?)(?:\s*[.,]|$)",
    ]

    for pattern in patterns:
        m = re.search(pattern, desc, re.IGNORECASE)
        if m:
            return normalize_group_label(clean(m.group(1)))

    if "non inscrit" in desc.lower():
        return "Non inscrits"

    return ""


def extract_group_from_visible_text_precise(html: str) -> str:
    text = strip_tags(unescape(html))

    patterns = [
        r"groupe politique\s*[:\-]?\s*(Rassemblement National|Ensemble pour la République|La France insoumise - Nouveau Front Populaire|Socialistes et apparentés|Droite Républicaine|Les Démocrates|Écologiste et Social|Horizons\s*&\s*Indépendants|Libertés,\s*indépendants,\s*outre-mer et territoires|Gauche démocrate et républicaine|Union des droites pour la République|UDR|Non inscrits)",
        r"membre du groupe\s*(Rassemblement National|Ensemble pour la République|La France insoumise - Nouveau Front Populaire|Socialistes et apparentés|Droite Républicaine|Les Démocrates|Écologiste et Social|Horizons\s*&\s*Indépendants|Libertés,\s*indépendants,\s*outre-mer et territoires|Gauche démocrate et républicaine|Union des droites pour la République|UDR|Non inscrits)",
        r"déput[ée]\s+du groupe\s*(Rassemblement National|Ensemble pour la République|La France insoumise - Nouveau Front Populaire|Socialistes et apparentés|Droite Républicaine|Les Démocrates|Écologiste et Social|Horizons\s*&\s*Indépendants|Libertés,\s*indépendants,\s*outre-mer et territoires|Gauche démocrate et républicaine|Union des droites pour la République|UDR|Non inscrits)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return normalize_group_label(clean(m.group(1)))

    return ""


def fetch_depute_profile(uid: str) -> dict:
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
    meta_description = extract_meta_description(html)

    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title_text = strip_tags(unescape(title_match.group(1))) if title_match else ""

    nom = ""
    if " - " in title_text:
        nom = clean(title_text.split(" - ")[0])
    elif title_text:
        nom = clean(title_text)

    if not nom or nom.startswith("PA"):
        h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
        if h1_match:
            h1_text = clean(strip_tags(unescape(h1_match.group(1))))
            if h1_text and not h1_text.startswith("PA"):
                nom = h1_text

    departement = ""
    if " - " in title_text:
        zone = clean(title_text.split(" - ", 1)[1])
        if " (" in zone:
            departement = clean(zone.split(" (", 1)[0])
        else:
            departement = zone

    circonscription = ""
    circ_match = re.search(r"(\d+(?:re|er|e)?\s+circonscription)", text, re.IGNORECASE)
    if circ_match:
        circonscription = normalize_circonscription_label(circ_match.group(1))

    groupe = extract_group_from_description(meta_description)
    if not groupe:
        groupe = extract_group_from_visible_text_precise(html)

    bio = ""
    bio_match = re.search(
        r"Biographie(.*?)(Commission|Historique > Anciens mandats et fonctions|Archives des travaux parlementaires|Voir le groupe politique|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if bio_match:
        bio = clean(bio_match.group(1))
    if not bio:
        bio = clean(text[:500])

    profile = {
        "nom": nom if nom and not nom.startswith("PA") else "",
        "groupe": normalize_group_label(groupe),
        "departement": departement,
        "circonscription": circonscription,
        "bio": bio,
        "mandat_en_cours": True,
        "meta_description": meta_description,
    }
    PROFILE_CACHE[uid] = profile
    return profile


def guess_theme(text: str) -> str:
    t = clean(text).lower()
    rules = [
        ("Budget / Finances", ["budget", "finance", "fiscal", "plf", "plfr", "plfss", "taxe", "impôt", "impot"]),
        ("Santé", ["santé", "hopital", "hôpital", "médical", "medical", "soin"]),
        ("Éducation", ["éducation", "education", "école", "ecole", "université", "universite", "enseignement"]),
        ("Écologie / Énergie", ["écologie", "ecologie", "climat", "énergie", "energie", "environnement"]),
        ("Travail / Social", ["travail", "emploi", "retraite", "social", "salaires", "chômage", "chomage"]),
        ("Justice / Sécurité", ["justice", "sécurité", "securite", "police", "prison", "pénal", "penal"]),
        ("Immigration", ["immigration", "asile", "étranger", "etranger", "mayotte"]),
        ("Institutions", ["motion", "censure", "constitution", "règlement", "reglement", "procédure", "procedure"]),
        ("Agriculture", ["agriculture", "aliment"]),
        ("Culture / Médias", ["culture", "audiovisuel", "presse", "patrimoine"]),
        ("Défense / International", ["défense", "defense", "armée", "armee", "international", "europe"]),
        ("Logement / Transports", ["logement", "transport", "mobilité", "mobilite", "ferroviaire"]),
    ]
    for theme, keywords in rules:
        if any(keyword in t for keyword in keywords):
            return theme
    return "Autres"


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

    return sorted(result, key=lambda x: (-x["total"], x["groupe"]))


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


def load_amo():
    raw = download_zip(AMO50_URL)
    zf = zipfile.ZipFile(BytesIO(raw))

    actors = {}
    organes = {}
    active_mandate_uids = set()

    for name in zf.namelist():
        if name.startswith("acteur/") and name.endswith(".json"):
            data = json.loads(zf.read(name))
            acteur = data.get("acteur", {})

            uid = get_uid(acteur.get("uid"))
            ident = acteur.get("etatCivil", {}).get("ident", {})

            prenom = clean(ident.get("prenom"))
            nom = clean(ident.get("nom"))
            nom_complet = clean(f"{prenom} {nom}")

            actors[uid] = {
                "uid": uid,
                "nom": nom_complet if nom_complet and not nom_complet.startswith("PA") else "",
                "groupe": "",
                "departement": "",
                "circonscription": "",
                "bio": "",
                "mandat_en_cours": True,
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

        date_fin = clean(mandat.get("dateFin"))
        if date_fin:
            continue

        active_mandate_uids.add(acteur_ref)

        type_organe = clean(mandat.get("typeOrgane"))
        organe_refs = extract_organe_refs(mandat.get("organes", {}))

        for ref in organe_refs:
            ref = clean(ref)
            organe = organes.get(ref, {})
            code_type = organe.get("codeType", "")

            if code_type in {"GP", "GRP"} or type_organe in {"GP", "GRP"}:
                groupe = (
                    organe.get("libelleAbrev")
                    or organe.get("libelleAbrege")
                    or organe.get("libelle")
                    or ref
                    or ""
                )
                actors[acteur_ref]["groupe"] = normalize_group_label(groupe)

            if code_type == "CIRCONSCRIPTION":
                dep = organe.get("departement", "")
                circo = organe.get("libelle", "")
                if dep:
                    actors[acteur_ref]["departement"] = dep
                if circo:
                    actors[acteur_ref]["circonscription"] = normalize_circonscription_label(circo)

    current_actors = {uid: actors[uid] for uid in active_mandate_uids if uid in actors}

    for uid, actor in list(current_actors.items()):
        current_actors[uid] = apply_manual_fix(uid, actor)

    return current_actors, organes


def enrich_actor_if_needed(uid: str, actor: dict) -> dict:
    actor = actor or {
        "uid": uid,
        "nom": "",
        "groupe": "",
        "departement": "",
        "circonscription": "",
        "bio": "",
        "mandat_en_cours": True,
    }

    actor = apply_manual_fix(uid, actor)

    need_name = (not clean(actor.get("nom"))) or clean(actor.get("nom")).startswith("PA")
    need_group = (not clean(actor.get("groupe"))) or clean(actor.get("groupe")).startswith("PO") or clean(actor.get("groupe")) == "Inconnu"
    need_dep = not clean(actor.get("departement"))
    need_circ = not clean(actor.get("circonscription"))
    need_bio = not clean(actor.get("bio"))

    if not (need_name or need_group or need_dep or need_circ or need_bio):
        return actor

    profile = fetch_depute_profile(uid)

    if need_name:
        profile_nom = clean(profile.get("nom"))
        if profile_nom and not profile_nom.startswith("PA"):
            actor["nom"] = profile_nom

    profile_group = normalize_group_label(profile.get("groupe"))
    if need_group and profile_group and profile_group != "Inconnu":
        actor["groupe"] = profile_group

    if need_dep and clean(profile.get("departement")):
        actor["departement"] = clean(profile.get("departement"))

    if need_circ and clean(profile.get("circonscription")):
        actor["circonscription"] = normalize_circonscription_label(profile.get("circonscription"))

    if need_bio and clean(profile.get("bio")):
        actor["bio"] = clean(profile.get("bio"))

    actor = apply_manual_fix(uid, actor)
    return actor


def load_scrutins(actors, organes):
    raw = download_zip(SCRUTINS_URL)
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
                    actor = enrich_actor_if_needed(uid_dep, actors.get(uid_dep, {}))
                    actor = apply_manual_fix(uid_dep, actor)
                    actors[uid_dep] = actor

                    nom = clean(actor.get("nom"))
                    if not nom or nom.startswith("PA"):
                        nom = f"Député {uid_dep}"

                    actor_group = normalize_group_label(actor.get("groupe") or "")
                    scrutin_group = normalize_group_label(groupe_nom or "")

                    if actor_group and actor_group != "Inconnu":
                        groupe = actor_group
                    else:
                        groupe = scrutin_group or "Inconnu"

                    votes.append({
                        "depute_uid": uid_dep,
                        "nom": nom,
                        "groupe": groupe,
                        "groupe_scrutin": scrutin_group,
                        "vote": label,
                        "departement": clean(actor.get("departement")),
                        "circonscription": normalize_circonscription_label(actor.get("circonscription")),
                    })

        if not votes:
            continue

        stats = compute_stats(votes)

        scrutins.append({
            "uid": uid,
            "numero": numero,
            "date": date,
            "year": year,
            "titre": titre,
            "description": description,
            "theme": guess_theme(f"{titre} {description}"),
            "stats": stats,
            "groupes_summary": compute_groupes(votes),
            "departements_summary": compute_departements(votes),
            "votes": votes,
            "expose_sommaire": "",
        })

    return scrutins


def build_deputes_file(actors, scrutins):
    votes_by_uid = defaultdict(list)

    for scrutin in scrutins:
        for vote in scrutin.get("votes", []):
            votes_by_uid[vote["depute_uid"]].append(vote)

    deputes = []
    seen = set()

    for uid, actor in actors.items():
        actor = enrich_actor_if_needed(uid, actor)
        actor = apply_manual_fix(uid, actor)
        actors[uid] = actor

        if uid in seen:
            continue
        seen.add(uid)

        actor_votes = votes_by_uid.get(uid, [])

        nom = clean(actor.get("nom"))
        if not nom or nom.startswith("PA"):
            continue

        observed_group_counts = defaultdict(int)
        observed_scrutin_group_counts = defaultdict(int)

        for vote in actor_votes:
            g = clean(vote.get("groupe"))
            if g and g != "Inconnu":
                observed_group_counts[g] += 1

            gs = clean(vote.get("groupe_scrutin"))
            if gs and gs != "Inconnu":
                observed_scrutin_group_counts[gs] += 1

        observed_main_group = (
            sorted(observed_group_counts.items(), key=lambda x: (-x[1], x[0]))[0][0]
            if observed_group_counts
            else ""
        )

        observed_main_scrutin_group = (
            sorted(observed_scrutin_group_counts.items(), key=lambda x: (-x[1], x[0]))[0][0]
            if observed_scrutin_group_counts
            else ""
        )

        groupe_final = normalize_group_label(clean(actor.get("groupe")))

        if not groupe_final or groupe_final == "Inconnu":
            groupe_final = observed_main_group

        actor_fixed = apply_manual_fix(uid, {
            "uid": uid,
            "nom": nom,
            "groupe": groupe_final,
            "departement": clean(actor.get("departement")),
            "circonscription": normalize_circonscription_label(actor.get("circonscription")),
            "bio": clean(actor.get("bio")),
        })

        groupe_final = normalize_group_label(clean(actor_fixed.get("groupe")))

        if not groupe_final or groupe_final == "Inconnu":
            continue

        deputes.append({
            "uid": uid,
            "nom": clean(actor_fixed.get("nom")),
            "groupe": groupe_final,
            "groupe_observe": observed_main_group,
            "groupe_scrutin": observed_main_scrutin_group,
            "departement": clean(actor_fixed.get("departement")),
            "circonscription": normalize_circonscription_label(actor_fixed.get("circonscription")),
            "bio": clean(actor_fixed.get("bio")),
            "votes_count": len(actor_votes),
        })

    deputes.sort(key=lambda x: x["nom"])

    print("Nombre de deputes retenus :", len(deputes))
    print("Exemples deputes retenus :", [
        (
            d["nom"],
            d["uid"],
            d["groupe"],
            d.get("groupe_observe", ""),
            d.get("groupe_scrutin", ""),
            d["circonscription"],
            d["departement"],
        )
        for d in deputes[:50]
    ])

    corbiere = next((d for d in deputes if d["uid"] == "PA721210"), None)
    print("DEBUG CORBIERE FINAL :", corbiere)

    write_json(BASE_DIR / "deputes.json", {"deputes": deputes})


def build_composition_file():
    deputes_payload = read_json_if_exists(BASE_DIR / "deputes.json", {"deputes": []})
    deputes = deputes_payload.get("deputes", [])

    observed_by_group = defaultdict(list)
    seen = set()

    for d in deputes:
        uid = clean(d.get("uid"))
        nom = clean(d.get("nom"))
        groupe = normalize_group_label(clean(d.get("groupe")))
        departement = clean(d.get("departement"))
        circonscription = normalize_circonscription_label(d.get("circonscription"))

        if not uid or uid in seen:
            continue
        if not nom or nom.startswith("PA"):
            continue
        if not groupe or groupe == "Inconnu":
            continue

        seen.add(uid)
        observed_by_group[groupe].append({
            "uid": uid,
            "nom": nom,
            "groupe": groupe,
            "departement": departement,
            "circonscription": circonscription,
        })

    total = sum(OFFICIAL_COMPOSITION.values())

    groupes = []
    for groupe, count in OFFICIAL_COMPOSITION.items():
        members = sorted(observed_by_group.get(groupe, []), key=lambda x: x["nom"])
        groupes.append({
            "groupe": groupe,
            "count": count,
            "pct": round((count / total) * 100, 1) if total else 0,
            "members": members,
        })

    groupes.sort(key=lambda x: (-x["count"], x["groupe"]))

    write_json(BASE_DIR / "composition.json", {
        "total": total,
        "expected_total": EXPECTED_ASSEMBLY_SIZE,
        "is_valid": total == EXPECTED_ASSEMBLY_SIZE,
        "groupes": groupes,
        "source": "official_manual",
    })


def build_year_index(scrutins):
    years = defaultdict(list)
    for scrutin in scrutins:
        years[scrutin["year"]].append(scrutin)

    result = {}
    for year, items in years.items():
        months = defaultdict(list)
        for scrutin in items:
            month_key = scrutin["date"][:7]
            months[month_key].append(scrutin)

        month_list = []
        for month_key, month_items in months.items():
            month_list.append({
                "month": month_key,
                "file": f"data/current/months/{month_key}.json",
                "scrutins": len(month_items),
            })

        total_votes = sum(s["stats"]["total_votes"] for s in items)
        unique_groupes = sorted({
            v["groupe"] for s in items for v in s["votes"]
            if v["groupe"] and v["groupe"] != "Inconnu"
        })

        result[str(year)] = {
            "counts": {
                "scrutins": len(items),
                "votes": total_votes,
                "groupes": len(unique_groupes),
            },
            "months": sorted(month_list, key=lambda x: x["month"], reverse=True),
        }

    return result


def write_month_files(scrutins):
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

    return month_list


def write_fallback_index():
    existing_index = read_json_if_exists(BASE_DIR / "index.json", {})
    existing_deputes = read_json_if_exists(BASE_DIR / "deputes.json", {"deputes": []})
    existing_composition = read_json_if_exists(
        BASE_DIR / "composition.json",
        {
            "total": 0,
            "expected_total": EXPECTED_ASSEMBLY_SIZE,
            "is_valid": False,
            "groupes": [],
        },
    )

    if existing_index:
        existing_index["updated_at"] = datetime.utcnow().isoformat()
        existing_index["composition"] = {
            "is_valid": bool(existing_composition.get("is_valid", False)),
            "total": int(existing_composition.get("total", 0)),
            "expected_total": int(existing_composition.get("expected_total", EXPECTED_ASSEMBLY_SIZE)),
            "fallback_used": True,
        }
        write_json(BASE_DIR / "index.json", existing_index)

    write_json(BASE_DIR / "deputes.json", existing_deputes)
    write_json(BASE_DIR / "composition.json", existing_composition)

    print("FALLBACK ACTIVÉ")
    print("Composition totale (fallback) :", existing_composition.get("total", 0))
    print("Composition valide (fallback) :", existing_composition.get("is_valid", False))


def main():
    print("========== BUILD DATA START ==========")
    print("VERSION BUILD DATA = CORBIERE_FIX_GROUPES_VOTES")

    try:
        actors, organes = load_amo()
        scrutins = load_scrutins(actors, organes)

        month_list = write_month_files(scrutins)
        build_deputes_file(actors, scrutins)
        build_composition_file()

        composition_data = json.loads((BASE_DIR / "composition.json").read_text(encoding="utf-8"))

        index_data = {
            "version": "9.1",
            "year": CURRENT_YEAR,
            "updated_at": datetime.utcnow().isoformat(),
            "available_years": [CURRENT_YEAR, PREVIOUS_YEAR],
            "default_year": CURRENT_YEAR,
            "counts": {
                "scrutins": len([s for s in scrutins if s["year"] == CURRENT_YEAR]),
                "votes": sum(s["stats"]["total_votes"] for s in scrutins if s["year"] == CURRENT_YEAR),
            },
            "months": sorted(
                [m for m in month_list if int(m["month"][:4]) == CURRENT_YEAR],
                key=lambda x: x["month"],
                reverse=True
            ),
            "years": build_year_index(scrutins),
            "composition": {
                "is_valid": composition_data.get("is_valid", False),
                "total": composition_data.get("total", 0),
                "expected_total": composition_data.get("expected_total", EXPECTED_ASSEMBLY_SIZE),
                "fallback_used": False,
            }
        }

        write_json(BASE_DIR / "index.json", index_data)

        print("Composition totale :", composition_data["total"])
        print("Composition valide :", composition_data["is_valid"])
        print("Groupes composition :", [(g["groupe"], g["count"]) for g in composition_data["groupes"]])
        print("Groupes inconnus restants :", sorted(UNKNOWN_GROUPS))

    except Exception as e:
        print("ERREUR BUILD :", e)
        print("Fallback sur les derniers fichiers versionnés.")
        write_fallback_index()

    print("========== BUILD DATA END ==========")


if __name__ == "__main__":
    main()

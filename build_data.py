import json
import re
import ssl
import time
import socket
import http.client
import urllib.request
import urllib.error
import zipfile

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

LEGISLATURE = "17"
CURRENT_YEAR = datetime.now(timezone.utc).year
MIN_YEAR = CURRENT_YEAR - 1
MAX_ASSEMBLY_SEATS = 577

AMO40_URL = (
    "https://data.assemblee-nationale.fr/static/openData/repository/17/amo/"
    "deputes_actifs_mandats_actifs_organes_divises/"
    "AMO40_deputes_actifs_mandats_actifs_organes_divises.json.zip"
)

SCRUTINS_URL = (
    "https://data.assemblee-nationale.fr/static/openData/repository/17/loi/"
    "scrutins/Scrutins.json.zip"
)

GROUP_LIST_URL = (
    "https://www2.assemblee-nationale.fr/deputes/liste/groupe-politique"
)

BASE_DIR = Path("data/current")
MONTHS_DIR = BASE_DIR / "months"
SSL_CONTEXT = ssl.create_default_context()


# ============================================================
# GROUPES
# ============================================================

GROUP_ALIASES = {
    "Rassemblement national": "Rassemblement National",
    "Rassemblement National": "Rassemblement National",

    "Ensemble pour la Republique": "Ensemble pour la République",
    "Ensemble pour la République": "Ensemble pour la République",

    "La France insoumise-Nouveau Front Populaire":
        "La France insoumise - Nouveau Front Populaire",
    "La France insoumise - Nouveau Front Populaire":
        "La France insoumise - Nouveau Front Populaire",

    "Socialistes et apparentes": "Socialistes et apparentés",
    "Socialistes et apparentés": "Socialistes et apparentés",

    "Droite republicaine": "Droite Républicaine",
    "Droite Républicaine": "Droite Républicaine",

    "Ecologiste et Social": "Écologiste et Social",
    "Écologiste et Social": "Écologiste et Social",

    "Les Democrates": "Les Démocrates",
    "Les Démocrates": "Les Démocrates",

    "Horizons et Indépendants": "Horizons & Indépendants",
    "Horizons et indépendants": "Horizons & Indépendants",
    "Horizons & Indépendants": "Horizons & Indépendants",

    "Libertés, indépendants, outre-mer et territoires":
        "Libertés, Indépendants, Outre-mer et Territoires",
    "Libertés, Indépendants, Outre-mer et Territoires":
        "Libertés, Indépendants, Outre-mer et Territoires",

    "Gauche démocrate et républicaine": "Gauche Démocrate et Républicaine",
    "Gauche Démocrate et Républicaine": "Gauche Démocrate et Républicaine",
    "Groupe de la Gauche démocrate et républicaine":
        "Gauche Démocrate et Républicaine",
    "de la Gauche démocrate et républicaine":
        "Gauche Démocrate et Républicaine",

    "Union des Droites pour la République":
        "Union des droites pour la République",
    "Union des droites pour la République":
        "Union des droites pour la République",
    "Groupe UDR": "Union des droites pour la République",
    "UDR": "Union des droites pour la République",
    "À Droite": "Union des droites pour la République",
    "A Droite": "Union des droites pour la République",

    "Non inscrit": "Non inscrits",
    "Non inscrite": "Non inscrits",
    "Non inscrits": "Non inscrits",
    "NI": "Non inscrits",
}

GROUP_SIGLES = {
    "Rassemblement National": "RN",
    "Ensemble pour la République": "EPR",
    "La France insoumise - Nouveau Front Populaire": "LFI-NFP",
    "Socialistes et apparentés": "SOC",
    "Droite Républicaine": "DR",
    "Écologiste et Social": "ECOS",
    "Les Démocrates": "DEM",
    "Horizons & Indépendants": "HOR",
    "Libertés, Indépendants, Outre-mer et Territoires": "LIOT",
    "Gauche Démocrate et Républicaine": "GDR",
    "Union des droites pour la République": "UDR",
    "Non inscrits": "NI",
}


# ============================================================
# OUTILS
# ============================================================

def ensure_dir(path):
    path.mkdir(parents=True, exist_ok=True)


def clean(value):
    if value is None:
        return ""
    return " ".join(str(value).replace("\u00a0", " ").split()).strip()


def ensure_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def get_uid(value):
    if isinstance(value, dict):
        return clean(
            value.get("#text")
            or value.get("uid")
            or value.get("value")
            or ""
        )
    return clean(value)


def normalize_group(value):
    value = clean(value)
    if not value:
        return ""
    value = re.sub(r"^Groupe\s+", "", value, flags=re.I)
    value = re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", value).strip()
    return GROUP_ALIASES.get(value, value)


def group_sigle(group):
    return GROUP_SIGLES.get(normalize_group(group), "")


def ordinal_fr(number):
    try:
        n = int(clean(number))
    except Exception:
        return clean(number)
    return "1re" if n == 1 else f"{n}e"


def normalize_circonscription(value):
    value = clean(value)
    if not value:
        return ""
    value = re.sub(r"\b1(?:er|ère|ere)\b", "1re", value, flags=re.I)
    value = re.sub(r"\b(\d+)(?:ème|eme)\b", r"\1e", value, flags=re.I)
    return value


def write_json(path, data):
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def download(url, retries=5, pause=3, chunk_size=1024 * 256):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "*/*",
                    "Connection": "close",
                },
            )
            with urllib.request.urlopen(
                request,
                context=SSL_CONTEXT,
                timeout=240,
            ) as response:
                chunks = []
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    chunks.append(chunk)
                data = b"".join(chunks)
                if not data:
                    raise ValueError(f"Téléchargement vide : {url}")
                return data

        except (
            http.client.IncompleteRead,
            urllib.error.URLError,
            socket.timeout,
            TimeoutError,
            ConnectionResetError,
            ValueError,
        ) as error:
            last_error = error
            print(f"Téléchargement échoué ({attempt}/{retries}) : {url}")
            print(error)
            if attempt < retries:
                time.sleep(pause * attempt)

    raise last_error


def download_zip(url):
    data = download(url)
    if len(data) < 4 or data[:2] != b"PK":
        raise ValueError(f"Le fichier téléchargé n'est pas un ZIP : {url}")
    return data


def download_text(url):
    data = download(url)
    for encoding in ("utf-8", "utf-8-sig", "iso-8859-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def iter_zip_json(zf):
    for filename in zf.namelist():
        if not filename.lower().endswith(".json"):
            continue
        try:
            payload = json.loads(zf.read(filename).decode("utf-8-sig"))
            yield filename, payload
        except Exception as error:
            print("JSON ignoré :", filename, error)


def extract_organe_refs(node):
    refs = []

    if isinstance(node, dict):
        if "organeRef" in node:
            for item in ensure_list(node.get("organeRef")):
                uid = get_uid(item)
                if uid:
                    refs.append(uid)

        for value in node.values():
            refs.extend(extract_organe_refs(value))

    elif isinstance(node, list):
        for item in node:
            refs.extend(extract_organe_refs(item))

    return list(dict.fromkeys(refs))


def extract_votants(node):
    voters = []

    if isinstance(node, dict):
        if "votant" in node:
            for voter in ensure_list(node.get("votant")):
                if isinstance(voter, dict):
                    voters.append(voter)

        elif "acteurRef" in node:
            voters.append(node)

        else:
            for value in node.values():
                voters.extend(extract_votants(value))

    elif isinstance(node, list):
        for item in node:
            voters.extend(extract_votants(item))

    return voters


def get_organe_label(organe):
    if not isinstance(organe, dict):
        return ""

    for key in (
        "libelle",
        "libelleEdition",
        "libelleAbrege",
        "libelleAbrev",
    ):
        value = clean(organe.get(key))
        if value:
            return value
    return ""


def get_actor_mandates(actor):
    node = actor.get("mandats", {})

    if isinstance(node, dict):
        return [
            m
            for m in ensure_list(node.get("mandat"))
            if isinstance(m, dict)
        ]

    if isinstance(node, list):
        return [m for m in node if isinstance(m, dict)]

    return []


def date_text(value):
    if isinstance(value, dict):
        value = value.get("#text") or value.get("value") or ""
    return clean(value)


def parse_date(value):
    value = date_text(value)
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def mandate_is_active(mandate, today=None):
    today = today or date.today()
    start = parse_date(mandate.get("dateDebut"))
    end = parse_date(mandate.get("dateFin"))

    if start and start > today:
        return False
    if end and end < today:
        return False
    return True


# ============================================================
# LISTE OFFICIELLE DES GROUPES ACTUELS
#
# On utilise la page officielle "Liste des députés par groupe politique"
# comme autorité pour le groupe ACTUEL de chaque député.
#
# Les mandats AMO restent utilisés pour la circonscription, l'identité
# et les organes historiques des scrutins.
# ============================================================

class OfficialGroupListParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_h2 = False
        self.h2_parts = []
        self.current_group = ""
        self.current_anchor_uid = ""
        self.current_anchor_parts = []
        self.uid_to_group = {}

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        if tag == "h2":
            self.in_h2 = True
            self.h2_parts = []
            return

        if tag == "a" and self.current_group:
            href = dict(attrs).get("href", "")
            match = re.search(
                r"/deputes/fiche/(?:OMC_)?(PA\d+)",
                href,
                flags=re.I,
            )
            if match:
                self.current_anchor_uid = match.group(1).upper()
                self.current_anchor_parts = []

    def handle_data(self, data):
        if self.in_h2:
            self.h2_parts.append(data)

        if self.current_anchor_uid:
            self.current_anchor_parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag == "h2" and self.in_h2:
            heading = clean(" ".join(self.h2_parts))
            group = normalize_group(heading)

            if group in GROUP_SIGLES:
                self.current_group = group
            else:
                self.current_group = ""

            self.in_h2 = False
            self.h2_parts = []
            return

        if tag == "a" and self.current_anchor_uid:
            if self.current_group:
                self.uid_to_group[self.current_anchor_uid] = self.current_group
            self.current_anchor_uid = ""
            self.current_anchor_parts = []


def load_official_current_groups():
    print("")
    print("Téléchargement de la composition officielle des groupes…")

    html = download_text(GROUP_LIST_URL)
    parser = OfficialGroupListParser()
    parser.feed(html)

    uid_to_group = parser.uid_to_group
    counts = Counter(uid_to_group.values())

    print("Députés trouvés sur la page officielle :", len(uid_to_group))
    print("Composition officielle détectée :")

    for group, count in counts.most_common():
        print(f" - {group}: {count}")

    validate_official_group_map(uid_to_group)
    return uid_to_group


def validate_official_group_map(uid_to_group):
    total = len(uid_to_group)
    counts = Counter(uid_to_group.values())

    errors = []

    if not (500 <= total <= MAX_ASSEMBLY_SEATS):
        errors.append(f"nombre de députés incohérent sur la page groupes : {total}")

    if not (8 <= len(counts) <= 20):
        errors.append(f"nombre de groupes incohérent : {len(counts)}")

    if counts.get("Non inscrits", 0) > 40:
        errors.append(
            f"trop de Non inscrits : {counts.get('Non inscrits', 0)}"
        )

    if counts and max(counts.values()) > 200:
        errors.append(
            f"un groupe contient anormalement {max(counts.values())} députés"
        )

    if errors:
        raise RuntimeError(
            "La page officielle des groupes n'a pas pu être lue correctement : "
            + " ; ".join(errors)
        )


# ============================================================
# DÉPUTÉS ACTUELS + ORGANES
# ============================================================

def extract_department_from_lieu(lieu):
    if not isinstance(lieu, dict):
        return "", ""

    dep = lieu.get("departement")
    dep_name = ""
    dep_code = clean(
        lieu.get("numDepartement")
        or lieu.get("numeroDepartement")
        or ""
    )

    if isinstance(dep, dict):
        dep_name = clean(
            dep.get("libelle")
            or dep.get("nom")
            or dep.get("#text")
            or ""
        )
        dep_code = dep_code or clean(
            dep.get("code")
            or dep.get("numero")
            or ""
        )
    else:
        dep_name = clean(dep)

    return dep_name, dep_code


def choose_active_assembly_mandate(actor):
    candidates = []

    for mandate in get_actor_mandates(actor):
        if clean(mandate.get("typeOrgane")).upper() != "ASSEMBLEE":
            continue
        if not mandate_is_active(mandate):
            continue
        start = parse_date(mandate.get("dateDebut")) or date.min
        candidates.append((start, mandate))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def load_current_deputies():
    print("")
    print("Téléchargement AMO40 — députés actifs / mandats / organes…")

    raw = download_zip(AMO40_URL)
    zf = zipfile.ZipFile(BytesIO(raw))

    raw_actors = {}
    organes = {}

    for filename, payload in iter_zip_json(zf):
        if not isinstance(payload, dict):
            continue

        actor = payload.get("acteur")
        if isinstance(actor, dict):
            uid = get_uid(actor.get("uid"))
            if uid:
                raw_actors[uid] = actor
            continue

        organe = payload.get("organe")
        if isinstance(organe, dict):
            uid = get_uid(organe.get("uid"))
            if uid:
                organes[uid] = organe

    print("Acteurs AMO40 :", len(raw_actors))
    print("Organes AMO40 :", len(organes))

    group_ref_to_label = {}

    for uid, organe in organes.items():
        code_type = clean(organe.get("codeType")).upper()
        if code_type in {"GP", "GRP", "GROUPE"}:
            label_raw = get_organe_label(organe)
            label = normalize_group(label_raw)
            if label:
                group_ref_to_label[uid] = label

    print("Organes historiques de groupes identifiés :", len(group_ref_to_label))

    official_groups = load_official_current_groups()

    amo_uids = set(raw_actors)
    group_uids = set(official_groups)

    missing_group = sorted(amo_uids - group_uids)
    extra_group = sorted(group_uids - amo_uids)

    if missing_group or extra_group:
        raise RuntimeError(
            "Décalage entre AMO40 et la liste officielle des groupes. "
            f"Sans groupe dans la page officielle : {len(missing_group)} ; "
            f"présents dans la page groupes mais absents d'AMO40 : {len(extra_group)}. "
            "Le build est stoppé plutôt que de publier une composition incertaine."
        )

    deputies = {}

    for uid, actor in raw_actors.items():
        ident = (
            actor.get("etatCivil", {})
            .get("ident", {})
        )
        first_name = clean(ident.get("prenom"))
        last_name = clean(ident.get("nom"))
        name = clean(f"{first_name} {last_name}")

        if not name:
            continue

        assembly_mandate = choose_active_assembly_mandate(actor)

        if not assembly_mandate:
            raise RuntimeError(
                f"Mandat actif de député introuvable pour {name} ({uid})."
            )

        election = assembly_mandate.get("election", {})
        if not isinstance(election, dict):
            election = {}

        lieu = election.get("lieu", {})
        if not isinstance(lieu, dict):
            lieu = {}

        dep_name, dep_code = extract_department_from_lieu(lieu)

        num_circo = clean(
            lieu.get("numCirco")
            or lieu.get("numeroCirconscription")
            or ""
        )

        circonscription = (
            f"{ordinal_fr(num_circo)} circonscription"
            if num_circo
            else ""
        )

        if not circonscription:
            ref_circo = get_uid(election.get("refCirconscription"))
            if ref_circo and ref_circo in organes:
                circonscription = normalize_circonscription(
                    get_organe_label(organes[ref_circo])
                )

        current_group = official_groups[uid]

        deputies[uid] = {
            "uid": uid,
            "nom": name,
            "groupe_actuel": current_group,
            "groupe_sigle": group_sigle(current_group),
            "departement": dep_name,
            "num_departement": dep_code,
            "num_circonscription": num_circo,
            "circonscription": normalize_circonscription(circonscription),
        }

    validate_current_deputies(deputies)

    print("")
    print("Députés actuels retenus :", len(deputies))
    counts = Counter(d["groupe_actuel"] for d in deputies.values())

    for group, count in counts.most_common():
        print(f" - {group}: {count}")

    return deputies, organes, group_ref_to_label


def validate_current_deputies(deputies):
    total = len(deputies)
    counts = Counter(
        d.get("groupe_actuel") or "Inconnu"
        for d in deputies.values()
    )

    errors = []

    if not (500 <= total <= MAX_ASSEMBLY_SEATS):
        errors.append(f"nombre de députés incohérent : {total}")

    if not (8 <= len(counts) <= 20):
        errors.append(f"nombre de groupes incohérent : {len(counts)}")

    if counts.get("Non inscrits", 0) > 40:
        errors.append(
            f"trop de Non inscrits : {counts.get('Non inscrits', 0)}"
        )

    if counts and max(counts.values()) > 200:
        errors.append(
            f"un groupe contient anormalement {max(counts.values())} députés"
        )

    if errors:
        raise RuntimeError(
            "Validation de la composition impossible : " + " ; ".join(errors)
        )


# ============================================================
# SUJETS / THÈMES
# ============================================================

def truncate(value, max_length=180):
    value = clean(value)
    if len(value) <= max_length:
        return value
    return value[:max_length - 1].rstrip() + "…"


def extract_bill_context(text):
    text = clean(text)

    patterns = [
        r"(projet de loi de financement de la sécurité sociale[^.;]*)",
        r"(projet de loi de finances[^.;]*)",
        r"(projet de loi[^.;]*)",
        r"(proposition de loi[^.;]*)",
        r"(proposition de résolution[^.;]*)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return truncate(match.group(1), 130)

    return ""


def make_subject(official_title, description):
    official_title = clean(official_title)
    description = clean(description)
    source = description or official_title

    if not source:
        return "Scrutin"

    lower = source.lower()

    if "motion de censure" in lower:
        context = extract_bill_context(source)
        return truncate(
            f"Motion de censure — {context}" if context else "Motion de censure",
            170,
        )

    match = re.search(
        r"sous-amendement\s+n[°º]?\s*([0-9]+)",
        source,
        re.I,
    )
    if match:
        title = f"Sous-amendement n°{match.group(1)}"
        context = extract_bill_context(source)
        if context:
            title += f" — {context}"
        return truncate(title, 170)

    match = re.search(
        r"amendement\s+n[°º]?\s*([0-9]+)",
        source,
        re.I,
    )
    if match:
        title = f"Amendement n°{match.group(1)}"

        article = re.search(
            r"article\s+([0-9A-Za-zÀ-ÿ\-]+)",
            source,
            re.I,
        )
        if article:
            title += f" à l’article {article.group(1)}"

        context = extract_bill_context(source)
        if context:
            title += f" — {context}"

        return truncate(title, 170)

    article = re.search(
        r"article\s+([0-9A-Za-zÀ-ÿ\-]+)",
        source,
        re.I,
    )
    if article:
        title = f"Vote sur l’article {article.group(1)}"
        context = extract_bill_context(source)
        if context:
            title += f" — {context}"
        return truncate(title, 170)

    readable = re.sub(
        r"^\s*scrutin public sur\s+",
        "",
        source,
        flags=re.I,
    )
    readable = re.sub(
        r"^\s*vote sur\s+",
        "",
        readable,
        flags=re.I,
    )
    readable = clean(readable)

    if readable:
        readable = readable[0].upper() + readable[1:]

    return truncate(readable or "Scrutin", 170)


def guess_theme(text):
    text = clean(text).lower()

    rules = [
        ("Budget / Fiscalité", [
            "budget", "finances", "fiscal", "impôt", "impot",
            "taxe", "plf", "plfss", "déficit", "deficit",
        ]),
        ("Travail / Retraites / Social", [
            "travail", "emploi", "retraite", "retraites",
            "salaire", "salaires", "chômage", "chomage",
            "allocation", "social",
        ]),
        ("Santé", [
            "santé", "sante", "hôpital", "hopital", "médecin",
            "medecin", "médical", "medical", "soin", "soins",
        ]),
        ("Éducation", [
            "éducation", "education", "enseignement", "école",
            "ecole", "université", "universite", "étudiant", "etudiant",
        ]),
        ("Écologie / Énergie", [
            "écologie", "ecologie", "environnement", "climat",
            "énergie", "energie", "nucléaire", "nucleaire",
            "biodiversité", "biodiversite",
        ]),
        ("Immigration / Asile", [
            "immigration", "immigré", "immigre", "asile", "étranger",
            "etranger", "étrangers", "etrangers", "titre de séjour",
            "titre de sejour",
        ]),
        ("Justice / Sécurité", [
            "justice", "sécurité", "securite", "police", "gendarmerie",
            "prison", "pénal", "penal", "criminalité", "criminalite",
        ]),
        ("Agriculture / Alimentation", [
            "agriculture", "agricole", "agriculteur", "agriculteurs",
            "alimentation", "alimentaire", "élevage", "elevage",
        ]),
        ("Logement / Transports", [
            "logement", "habitat", "transport", "mobilité", "mobilite",
            "ferroviaire", "route",
        ]),
        ("Défense / International", [
            "défense", "defense", "armée", "armee", "militaire",
            "international", "ukraine", "europe", "européen", "europeen",
        ]),
        ("Institutions", [
            "constitution", "motion de censure", "censure",
            "assemblée nationale", "assemblee nationale", "institution",
        ]),
        ("Culture / Médias", [
            "culture", "culturel", "audiovisuel", "presse",
            "média", "media", "patrimoine",
        ]),
    ]

    for theme, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return theme

    return "Autres"


# ============================================================
# STATS
# ============================================================

def compute_vote_stats(votes):
    return {
        "pour": sum(v.get("vote") == "Pour" for v in votes),
        "contre": sum(v.get("vote") == "Contre" for v in votes),
        "abstention": sum(v.get("vote") == "Abstention" for v in votes),
        "non_votant": sum(v.get("vote") == "Non-votant" for v in votes),
        "total": len(votes),
    }


def dominant_position(stats):
    values = {
        "Pour": stats["pour"],
        "Contre": stats["contre"],
        "Abstention": stats["abstention"],
    }

    maximum = max(values.values())

    if maximum == 0:
        return "Non-votant"

    winners = [label for label, count in values.items() if count == maximum]

    return winners[0] if len(winners) == 1 else "Partagé"


def cohesion_percent(stats):
    expressed = stats["pour"] + stats["contre"] + stats["abstention"]

    if expressed == 0:
        return 0.0

    return round(
        max(stats["pour"], stats["contre"], stats["abstention"])
        / expressed
        * 100,
        1,
    )


def compute_group_summary(votes):
    grouped = defaultdict(list)

    for vote in votes:
        group = normalize_group(
            vote.get("groupe_au_vote")
            or vote.get("groupe")
            or ""
        ) or "Inconnu"

        grouped[group].append(vote)

    result = []

    for group, group_votes in grouped.items():
        stats = compute_vote_stats(group_votes)

        result.append({
            "groupe": group,
            "groupe_sigle": group_sigle(group),
            "pour": stats["pour"],
            "contre": stats["contre"],
            "abstention": stats["abstention"],
            "non_votant": stats["non_votant"],
            "total": stats["total"],
            "position": dominant_position(stats),
            "cohesion_pct": cohesion_percent(stats),
        })

    return sorted(
        result,
        key=lambda row: (-row["total"], row["groupe"]),
    )


# ============================================================
# SCRUTINS
# ============================================================

def infer_group_from_current_voters(block_voters, current_deputies):
    groups = []

    for actor_uid, _vote_label in block_voters:
        deputy = current_deputies.get(actor_uid)
        if not deputy:
            continue

        group = normalize_group(deputy.get("groupe_actuel"))
        if group:
            groups.append(group)

    if not groups:
        return ""

    counts = Counter(groups)
    group, count = counts.most_common(1)[0]

    if count / len(groups) >= 0.75:
        return group

    return ""


def load_scrutins(current_deputies, organes, group_ref_to_label):
    print("")
    print("Téléchargement des scrutins…")

    raw = download_zip(SCRUTINS_URL)
    zf = zipfile.ZipFile(BytesIO(raw))

    scrutins = []
    unresolved_group_refs = Counter()
    group_blocks_total = 0
    group_blocks_unknown = 0

    for _filename, payload in iter_zip_json(zf):
        if not isinstance(payload, dict):
            continue

        scrutin = payload.get("scrutin", payload)
        if not isinstance(scrutin, dict):
            continue

        scrutin_date = clean(scrutin.get("dateScrutin"))
        if not scrutin_date:
            continue

        try:
            year = int(scrutin_date[:4])
        except Exception:
            continue

        if year < MIN_YEAR:
            continue

        uid = get_uid(scrutin.get("uid"))
        if not uid:
            continue

        numero = scrutin.get("numero")
        official_title = clean(scrutin.get("titre"))

        objet = scrutin.get("objet", {})
        if not isinstance(objet, dict):
            objet = {}

        description = clean(
            objet.get("libelle")
            or objet.get("titre")
            or ""
        )

        subject = make_subject(official_title, description)
        theme = guess_theme(" ".join([official_title, description, subject]))

        ventilation = scrutin.get("ventilationVotes", {})
        if not isinstance(ventilation, dict):
            ventilation = {}

        organe_vote = ventilation.get("organe", {})
        if not isinstance(organe_vote, dict):
            organe_vote = {}

        groupes_node = organe_vote.get("groupes", {})
        if not isinstance(groupes_node, dict):
            groupes_node = {}

        group_blocks = ensure_list(groupes_node.get("groupe"))
        votes = []

        for group_block in group_blocks:
            if not isinstance(group_block, dict):
                continue

            group_blocks_total += 1

            group_ref = get_uid(group_block.get("organeRef"))

            group_raw = clean(
                group_block.get("libelle")
                or group_block.get("libelleAbrege")
                or group_block.get("libelleAbrev")
                or ""
            )

            if not group_raw and group_ref in organes:
                organe = organes[group_ref]
                if clean(organe.get("codeType")).upper() in {
                    "GP", "GRP", "GROUPE"
                }:
                    group_raw = get_organe_label(organe)

            group_name = normalize_group(group_raw)

            if not group_name and group_ref:
                group_name = group_ref_to_label.get(group_ref, "")

            vote_container = group_block.get("vote", {})
            if not isinstance(vote_container, dict):
                vote_container = {}

            nominative = vote_container.get("decompteNominatif", {})
            if not isinstance(nominative, dict):
                nominative = {}

            block_voters = []

            for key, label in (
                ("pours", "Pour"),
                ("contres", "Contre"),
                ("abstentions", "Abstention"),
                ("nonVotants", "Non-votant"),
            ):
                for voter in extract_votants(nominative.get(key)):
                    actor_uid = get_uid(voter.get("acteurRef"))
                    if actor_uid:
                        block_voters.append((actor_uid, label))

            if not group_name:
                group_name = infer_group_from_current_voters(
                    block_voters,
                    current_deputies,
                )

            if not group_name:
                group_name = "Inconnu"
                group_blocks_unknown += 1
                if group_ref:
                    unresolved_group_refs[group_ref] += 1

            for actor_uid, label in block_voters:
                deputy = current_deputies.get(actor_uid, {})

                votes.append({
                    "depute_uid": actor_uid,
                    "nom": clean(deputy.get("nom")) or actor_uid,
                    "groupe_au_vote": group_name,
                    "groupe_au_vote_brut": group_raw,
                    "groupe": group_name,
                    "groupe_actuel": normalize_group(
                        deputy.get("groupe_actuel")
                    ),
                    "groupe_actuel_sigle": group_sigle(
                        deputy.get("groupe_actuel")
                    ),
                    "vote": label,
                    "departement": clean(deputy.get("departement")),
                    "circonscription": normalize_circonscription(
                        deputy.get("circonscription")
                    ),
                })

        unique_votes = {}
        for vote in votes:
            actor_uid = vote.get("depute_uid")
            if actor_uid and actor_uid not in unique_votes:
                unique_votes[actor_uid] = vote

        votes = list(unique_votes.values())

        if not votes:
            continue

        stats = compute_vote_stats(votes)
        group_summary = compute_group_summary(votes)

        scrutins.append({
            "uid": uid,
            "numero": numero,
            "date": scrutin_date,
            "year": year,
            "sujet": subject,
            "titre_court": subject,
            "titre": official_title,
            "titre_officiel": official_title,
            "description": description or official_title,
            "theme": theme,
            "stats": {
                "pour": stats["pour"],
                "contre": stats["contre"],
                "abstention": stats["abstention"],
                "non_votant": stats["non_votant"],
                "total_votes": stats["total"],
            },
            "groupes_summary": group_summary,
            "votes": votes,
        })

    scrutins.sort(
        key=lambda row: (row.get("date", ""), str(row.get("numero", ""))),
        reverse=True,
    )

    validate_scrutins(
        scrutins,
        group_blocks_total,
        group_blocks_unknown,
    )

    print("Scrutins conservés :", len(scrutins))
    print(
        "Blocs de groupes inconnus :",
        f"{group_blocks_unknown}/{group_blocks_total}",
    )

    if unresolved_group_refs:
        print(
            "Références de groupes non résolues :",
            unresolved_group_refs.most_common(10),
        )

    return scrutins


def validate_scrutins(scrutins, group_blocks_total, group_blocks_unknown):
    if not scrutins:
        raise RuntimeError("Aucun scrutin n'a été récupéré.")

    if group_blocks_total:
        unknown_ratio = group_blocks_unknown / group_blocks_total
        if unknown_ratio > 0.05:
            raise RuntimeError(
                "Trop de groupes de scrutin sont inconnus "
                f"({unknown_ratio:.1%}). Le build est stoppé."
            )

    by_year = defaultdict(set)

    for scrutin in scrutins:
        for summary in scrutin.get("groupes_summary", []):
            group = summary.get("groupe")
            if group and group != "Inconnu":
                by_year[str(scrutin["year"])].add(group)

    for year, groups in by_year.items():
        if len(groups) < 8:
            raise RuntimeError(
                f"{year}: seulement {len(groups)} groupes distincts "
                "dans les scrutins. Le build est stoppé."
            )


# ============================================================
# FICHIERS DE SORTIE
# ============================================================

def build_deputes_file(current_deputies, scrutins):
    votes_by_uid = defaultdict(int)
    votes_by_uid_year = defaultdict(lambda: defaultdict(int))

    for scrutin in scrutins:
        year = str(scrutin["year"])

        for vote in scrutin.get("votes", []):
            uid = vote.get("depute_uid")

            if uid in current_deputies:
                votes_by_uid[uid] += 1
                votes_by_uid_year[uid][year] += 1

    deputes = []

    for uid, actor in current_deputies.items():
        group = actor["groupe_actuel"]

        deputes.append({
            "uid": uid,
            "nom": actor["nom"],
            "groupe": group,
            "groupe_actuel": group,
            "groupe_sigle": group_sigle(group),
            "departement": actor.get("departement", ""),
            "num_departement": actor.get("num_departement", ""),
            "num_circonscription": actor.get("num_circonscription", ""),
            "circonscription": actor.get("circonscription", ""),
            "votes_count": votes_by_uid.get(uid, 0),
            "votes_par_annee": dict(
                votes_by_uid_year.get(uid, {})
            ),
        })

    deputes.sort(key=lambda row: row["nom"].lower())

    write_json(
        BASE_DIR / "deputes.json",
        {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "total": len(deputes),
            "deputes": deputes,
        },
    )

    print("deputes.json :", len(deputes))
    return deputes


def build_composition_file(deputes):
    grouped = defaultdict(list)

    for deputy in deputes:
        grouped[deputy["groupe_actuel"]].append(deputy)

    total = len(deputes)
    groups = []

    for group, members in grouped.items():
        members.sort(key=lambda row: row["nom"].lower())

        groups.append({
            "groupe": group,
            "sigle": group_sigle(group),
            "count": len(members),
            "pct": round(len(members) / total * 100, 1) if total else 0,
            "members": [
                {
                    "uid": m["uid"],
                    "nom": m["nom"],
                    "departement": m["departement"],
                    "circonscription": m["circonscription"],
                }
                for m in members
            ],
        })

    groups.sort(key=lambda row: (-row["count"], row["groupe"]))

    composition = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total": total,
        "sieges_theoriques": MAX_ASSEMBLY_SEATS,
        "sieges_vacants": max(0, MAX_ASSEMBLY_SEATS - total),
        "is_valid": True,
        "groupes": groups,
        "source": (
            "Assemblée nationale — liste officielle des députés par groupe "
            "+ AMO40"
        ),
    }

    write_json(BASE_DIR / "composition.json", composition)
    print("composition.json créé")
    return composition


def write_month_files(scrutins):
    ensure_dir(MONTHS_DIR)

    for old_file in MONTHS_DIR.glob("*.json"):
        old_file.unlink()

    grouped = defaultdict(list)

    for scrutin in scrutins:
        month = clean(scrutin.get("date"))[:7]
        if month:
            grouped[month].append(scrutin)

    month_index = []

    for month, items in grouped.items():
        items.sort(key=lambda row: row["date"], reverse=True)

        write_json(
            MONTHS_DIR / f"{month}.json",
            {
                "month": month,
                "year": int(month[:4]),
                "scrutins": items,
            },
        )

        month_index.append({
            "month": month,
            "file": f"data/current/months/{month}.json",
            "scrutins": len(items),
        })

    month_index.sort(key=lambda row: row["month"], reverse=True)
    return month_index


def build_groupes_file(scrutins, composition):
    data = {}

    for scrutin in scrutins:
        year = int(scrutin["year"])

        for summary in scrutin.get("groupes_summary", []):
            group = normalize_group(summary.get("groupe"))

            if not group or group == "Inconnu":
                continue

            key = (year, group)

            if key not in data:
                data[key] = {
                    "year": year,
                    "groupe": group,
                    "sigle": group_sigle(group),
                    "scrutins_count": 0,
                    "votes": {
                        "pour": 0,
                        "contre": 0,
                        "abstention": 0,
                        "non_votant": 0,
                    },
                    "_themes": defaultdict(int),
                    "scrutins": [],
                }

            entry = data[key]
            entry["scrutins_count"] += 1

            for field in ("pour", "contre", "abstention", "non_votant"):
                entry["votes"][field] += summary.get(field, 0)

            theme = clean(scrutin.get("theme")) or "Autres"
            entry["_themes"][theme] += 1

            entry["scrutins"].append({
                "uid": scrutin["uid"],
                "date": scrutin["date"],
                "sujet": scrutin["sujet"],
                "titre": scrutin["titre"],
                "titre_officiel": scrutin["titre_officiel"],
                "description": scrutin["description"],
                "theme": theme,
                "position": summary["position"],
                "cohesion_pct": summary["cohesion_pct"],
                "pour": summary["pour"],
                "contre": summary["contre"],
                "abstention": summary["abstention"],
                "non_votant": summary["non_votant"],
                "total": summary["total"],
            })

    current_counts = {
        normalize_group(row["groupe"]): row["count"]
        for row in composition.get("groupes", [])
    }

    result = []

    for entry in data.values():
        entry["themes"] = [
            {"theme": theme, "scrutins": count}
            for theme, count in sorted(
                entry["_themes"].items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]

        del entry["_themes"]

        entry["scrutins"].sort(
            key=lambda row: row["date"],
            reverse=True,
        )

        entry["deputes_actuels"] = current_counts.get(
            normalize_group(entry["groupe"]),
            0,
        )

        result.append(entry)

    result.sort(key=lambda row: (-row["year"], row["groupe"]))

    write_json(
        BASE_DIR / "groupes.json",
        {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "groupes": result,
        },
    )

    print("groupes.json :", len(result), "fiches groupe/année")


def build_search_file(deputes, composition, scrutins):
    departments = sorted({
        clean(d.get("departement"))
        for d in deputes
        if clean(d.get("departement"))
    })

    constituencies = sorted({
        clean(d.get("circonscription"))
        for d in deputes
        if clean(d.get("circonscription"))
    })

    themes = sorted({
        clean(s.get("theme"))
        for s in scrutins
        if clean(s.get("theme"))
    })

    groups = [
        {
            "groupe": row["groupe"],
            "sigle": row.get("sigle", "") or group_sigle(row["groupe"]),
            "count": row["count"],
        }
        for row in composition.get("groupes", [])
    ]

    write_json(
        BASE_DIR / "search.json",
        {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "deputes": [
                {
                    "uid": d["uid"],
                    "nom": d["nom"],
                    "groupe": d["groupe"],
                    "groupe_sigle": d.get("groupe_sigle", ""),
                    "departement": d["departement"],
                    "num_departement": d["num_departement"],
                    "num_circonscription": d["num_circonscription"],
                    "circonscription": d["circonscription"],
                }
                for d in deputes
            ],
            "groupes": groups,
            "departements": departments,
            "circonscriptions": constituencies,
            "themes": themes,
        },
    )

    print("search.json créé")


def build_years_data(scrutins, month_index):
    years = sorted({int(s["year"]) for s in scrutins})
    result = {}

    for year in years:
        year_scrutins = [s for s in scrutins if int(s["year"]) == year]
        months = [
            m
            for m in month_index
            if int(m["month"][:4]) == year
        ]

        votes_count = sum(
            int(s.get("stats", {}).get("total_votes", 0))
            for s in year_scrutins
        )

        groups = {
            normalize_group(summary.get("groupe"))
            for s in year_scrutins
            for summary in s.get("groupes_summary", [])
            if normalize_group(summary.get("groupe"))
            not in {"", "Inconnu"}
        }

        result[str(year)] = {
            "counts": {
                "scrutins": len(year_scrutins),
                "votes": votes_count,
                "groupes": len(groups),
            },
            "months": months,
        }

    return result


def build_index_file(scrutins, month_index, composition):
    years_data = build_years_data(scrutins, month_index)
    available_years = sorted(
        [int(year) for year in years_data],
        reverse=True,
    )

    if CURRENT_YEAR in available_years:
        default_year = CURRENT_YEAR
    elif available_years:
        default_year = available_years[0]
    else:
        default_year = CURRENT_YEAR

    default_data = years_data.get(
        str(default_year),
        {
            "counts": {
                "scrutins": 0,
                "votes": 0,
                "groupes": 0,
            },
            "months": [],
        },
    )

    write_json(
        BASE_DIR / "index.json",
        {
            "version": "GROUP_FIRST_V3_OFFICIAL_GROUP_LIST",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "legislature": int(LEGISLATURE),
            "available_years": available_years,
            "default_year": default_year,
            "counts": default_data["counts"],
            "months": default_data["months"],
            "years": years_data,
            "composition": {
                "total": composition["total"],
                "sieges_theoriques": composition["sieges_theoriques"],
                "sieges_vacants": composition["sieges_vacants"],
                "is_valid": composition["is_valid"],
            },
        },
    )

    print("index.json créé")


# ============================================================
# MAIN
# ============================================================

def main():
    print("")
    print("======================================================")
    print(" BUILD DATA — GROUP FIRST V3 / OFFICIAL GROUP LIST")
    print("======================================================")
    print("")

    ensure_dir(BASE_DIR)
    ensure_dir(MONTHS_DIR)

    current_deputies, organes, group_ref_to_label = load_current_deputies()

    scrutins = load_scrutins(
        current_deputies,
        organes,
        group_ref_to_label,
    )

    deputes = build_deputes_file(
        current_deputies,
        scrutins,
    )

    composition = build_composition_file(deputes)
    month_index = write_month_files(scrutins)

    build_groupes_file(
        scrutins,
        composition,
    )

    build_search_file(
        deputes,
        composition,
        scrutins,
    )

    build_index_file(
        scrutins,
        month_index,
        composition,
    )

    print("")
    print("======================================================")
    print(" BUILD TERMINÉ")
    print("======================================================")
    print("Députés actuels :", len(deputes))
    print("Scrutins :", len(scrutins))
    print("Années :", sorted({s["year"] for s in scrutins}))
    print("")
    print("Fichiers créés :")
    print(" data/current/index.json")
    print(" data/current/search.json")
    print(" data/current/composition.json")
    print(" data/current/deputes.json")
    print(" data/current/groupes.json")
    print(" data/current/months/YYYY-MM.json")


if __name__ == "__main__":
    main()

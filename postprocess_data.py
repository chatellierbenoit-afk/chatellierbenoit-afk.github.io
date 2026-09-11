from pathlib import Path
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone

BASE_DIR = Path("data/current")
MONTHS_DIR = BASE_DIR / "months"
GROUPS_DIR = BASE_DIR / "groupes"
VERSION = "GROUP_FIRST_V5_1_AUDITED_DATA"


def clean(value):
    if value is None:
        return ""
    return " ".join(str(value).replace("\u00a0", " ").split()).strip()


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def normalize_text(value):
    value = clean(value).lower()
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.replace("’", "'")
    value = re.sub(r"[^a-z0-9' -]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def has_term(text, term):
    text = normalize_text(text)
    term = normalize_text(term)
    if not text or not term:
        return False
    if " " in term or "'" in term or "-" in term:
        return term in text
    return re.search(
        rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])",
        text,
    ) is not None


SPECIAL_THEME_RULES = [
    (
        "Institutions",
        [
            "patrimoine immobilier de l'etat",
            "immobilier de l'etat",
            "domaine immobilier de l'etat",
            "biens immobiliers de l'etat",
        ],
    ),
    (
        "Culture / Médias",
        [
            "patrimoine culturel",
            "patrimoine historique",
            "monument historique",
            "monuments historiques",
        ],
    ),
    (
        "Travail / Retraites / Social",
        [
            "protection de l'enfance",
            "aide sociale a l'enfance",
        ],
    ),
]

THEME_RULES = [
    (
        "Budget / Fiscalité",
        [
            "budget", "finances", "fiscal", "fiscale", "fiscaux",
            "fiscales", "impot", "impots", "taxe", "taxes",
            "plf", "plfss", "deficit", "dette publique",
        ],
    ),
    (
        "Travail / Retraites / Social",
        [
            "travail", "emploi", "emplois", "retraite", "retraites",
            "salaire", "salaires", "chomage", "allocation",
            "allocations", "protection sociale", "securite sociale",
            "solidarite", "handicap", "enfance", "mineurs",
        ],
    ),
    (
        "Santé",
        [
            "sante", "hopital", "hopitaux", "medecin", "medecins",
            "medical", "medicaux", "soin", "soins", "medicament",
            "medicaments", "psychiatrie",
        ],
    ),
    (
        "Éducation",
        [
            "education", "enseignement", "ecole", "ecoles",
            "universite", "universites", "etudiant", "etudiants",
            "scolaire", "lycee", "college",
        ],
    ),
    (
        "Écologie / Énergie",
        [
            "ecologie", "environnement", "climat", "energie",
            "energies", "nucleaire", "biodiversite", "renouvelable",
            "renouvelables", "pollution", "decarbonation", "carbone",
        ],
    ),
    (
        "Immigration / Asile",
        [
            "immigration", "immigre", "immigres", "asile",
            "etranger", "etrangers", "titre de sejour",
            "titres de sejour", "migrant", "migrants",
        ],
    ),
    (
        "Justice / Sécurité",
        [
            "justice", "securite", "police", "gendarmerie", "prison",
            "penal", "penale", "criminalite", "delit", "delits",
            "violence", "violences", "terrorisme",
        ],
    ),
    (
        "Agriculture / Alimentation",
        [
            "agriculture", "agricole", "agricoles", "agriculteur",
            "agriculteurs", "alimentation", "alimentaire", "elevage",
            "peche", "viticulture",
        ],
    ),
    (
        "Logement / Transports",
        [
            "logement", "logements", "habitat", "transport",
            "transports", "mobilite", "ferroviaire", "route", "routes",
            "autoroute", "autoroutes", "sncf", "loyer", "loyers",
        ],
    ),
    (
        "Défense / International",
        [
            "defense", "armee", "militaire", "militaires",
            "international", "ukraine", "europe", "europeen",
            "europeenne", "diplomatie", "otan",
            "aide au developpement",
        ],
    ),
    (
        "Institutions",
        [
            "constitution", "motion de censure", "censure",
            "assemblee nationale", "institution", "institutions",
            "collectivites territoriales", "decentralisation",
            "fonction publique", "administration de l'etat",
            "domaine public", "propriete publique", "service public",
        ],
    ),
    (
        "Culture / Médias",
        [
            "culture", "culturel", "culturelle", "audiovisuel",
            "presse", "media", "medias", "reseaux sociaux",
            "reseau social", "plateforme numerique",
            "plateformes numeriques", "internet",
            "information en ligne",
        ],
    ),
]


def guess_theme(text):
    normalized = normalize_text(text)

    for theme, terms in SPECIAL_THEME_RULES:
        if any(has_term(normalized, term) for term in terms):
            return theme

    scores = Counter()

    for theme, terms in THEME_RULES:
        for term in terms:
            normalized_term = normalize_text(term)
            if not normalized_term:
                continue

            if has_term(normalized, normalized_term):
                if " " in normalized_term or "'" in normalized_term or "-" in normalized_term:
                    scores[theme] += 3
                else:
                    scores[theme] += 1

    if not scores:
        return "Autres"

    best_score = max(scores.values())

    for theme, _terms in THEME_RULES:
        if scores[theme] == best_score:
            return theme

    return "Autres"


def strip_scrutin_boilerplate(text):
    value = clean(text)
    value = re.sub(
        r"^\s*scrutin public(?:\s+n[°º]?\s*\d+)?\s+sur\s+",
        "",
        value,
        flags=re.I,
    )
    value = re.sub(
        r"^\s*vote\s+sur\s+",
        "",
        value,
        flags=re.I,
    )
    return value.strip(" .")


def extract_goal(text):
    value = strip_scrutin_boilerplate(text)

    patterns = [
        r"\bvisant\s+à\s+(.+?)(?:\s*\([^)]*\)\s*$|$)",
        r"\bvisant\s+au\s+(.+?)(?:\s*\([^)]*\)\s*$|$)",
        r"\brelati(?:f|ve|fs|ves)\s+à\s+(.+?)(?:\s*\([^)]*\)\s*$|$)",
        r"\brelati(?:f|ve|fs|ves)\s+au\s+(.+?)(?:\s*\([^)]*\)\s*$|$)",
        r"\brelati(?:f|ve|fs|ves)\s+aux\s+(.+?)(?:\s*\([^)]*\)\s*$|$)",
        r"\bportant\s+(.+?)(?:\s*\([^)]*\)\s*$|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, value, flags=re.I)
        if match:
            goal = clean(match.group(1)).strip(" .")
            if goal:
                return goal

    return ""


def fix_french_elision(text):
    value = clean(text)
    return re.sub(
        r"\bde\s+([aeiouyhàâäéèêëîïôöùûü])",
        r"d’\1",
        value,
        flags=re.I,
    )


def detect_whole_text(text):
    readable = strip_scrutin_boilerplate(text)
    match = re.search(
        r"(?:sur\s+)?l['’]ensemble\s+"
        r"(?:de\s+la\s+|de\s+l['’]|du\s+|des\s+|de\s+|d['’])"
        r"(.+)",
        readable,
        flags=re.I,
    )
    if not match:
        return ""
    return clean(match.group(1)).strip(" .")


def make_whole_text_explanation(source):
    readable = strip_scrutin_boilerplate(source)
    lower = normalize_text(readable)
    subject = detect_whole_text(readable)
    goal = extract_goal(readable)

    sentences = [
        "Il s'agit d'un vote sur l'ensemble du texte : les députés "
        "ne se prononcent donc pas sur une seule disposition isolée."
    ]

    if goal:
        sentences.append(
            f"D'après son intitulé officiel, son objet est : {goal}."
        )
    elif subject:
        sentences.append(
            f"Le texte soumis au vote est : {subject}."
        )

    if "commission mixte paritaire" in lower:
        sentences.append(
            "La version soumise au vote est celle issue de la commission "
            "mixte paritaire, c'est-à-dire du texte élaboré après recherche "
            "d'un accord entre députés et sénateurs."
        )
    elif "nouvelle lecture" in lower:
        sentences.append(
            "Le vote intervient en nouvelle lecture, après une étape "
            "précédente de la navette parlementaire."
        )
    elif "lecture definitive" in lower:
        sentences.append(
            "Il s'agit d'une lecture définitive : l'Assemblée nationale "
            "se prononce sur la version finale du texte à ce stade de la procédure."
        )

    en_clair = fix_french_elision(" ".join(sentences))
    ce_vote = (
        "Un vote Pour approuve cette version du texte dans son ensemble. "
        "Un vote Contre la rejette. "
        "Une abstention signifie que le député ne choisit ni l'adoption ni le rejet."
    )
    return en_clair, ce_vote


def improve_explanation(scrutin):
    official_title = clean(
        scrutin.get("titre_officiel")
        or scrutin.get("titre")
        or scrutin.get("description")
        or scrutin.get("sujet")
    )
    description = clean(scrutin.get("description"))
    source = description or official_title

    current_en_clair = clean(scrutin.get("en_clair"))
    current_vote_meaning = clean(scrutin.get("ce_qui_etait_vote"))

    if detect_whole_text(source):
        en_clair, ce_vote = make_whole_text_explanation(source)
        scrutin["en_clair"] = en_clair
        scrutin["ce_qui_etait_vote"] = ce_vote
        return

    if current_en_clair:
        scrutin["en_clair"] = fix_french_elision(current_en_clair)

    if current_vote_meaning:
        scrutin["ce_qui_etait_vote"] = fix_french_elision(current_vote_meaning)


def correct_stats(scrutin):
    stats = scrutin.get("stats")
    if not isinstance(stats, dict):
        stats = {}

    pour = int(stats.get("pour") or 0)
    contre = int(stats.get("contre") or 0)
    abstention = int(stats.get("abstention") or 0)
    non_votant = int(stats.get("non_votant") or 0)

    votants = pour + contre + abstention
    suffrages_exprimes = pour + contre
    total_recenses = votants + non_votant

    stats.update(
        {
            "pour": pour,
            "contre": contre,
            "abstention": abstention,
            "non_votant": non_votant,
            "total_votes": votants,
            "votants": votants,
            "suffrages_exprimes": suffrages_exprimes,
            "total_recenses": total_recenses,
        }
    )

    scrutin["stats"] = stats


def searchable_text(scrutin):
    return " ".join(
        [
            clean(scrutin.get("titre_officiel")),
            clean(scrutin.get("titre")),
            clean(scrutin.get("titre_court")),
            clean(scrutin.get("sujet")),
            clean(scrutin.get("description")),
            clean(scrutin.get("en_clair")),
        ]
    )


def process_month_files():
    uid_map = {}
    year_vote_counts = Counter()
    changed = 0

    for path in sorted(MONTHS_DIR.glob("*.json")):
        payload = load_json(path)
        scrutins = payload.get("scrutins", [])

        if not isinstance(scrutins, list):
            continue

        for scrutin in scrutins:
            if not isinstance(scrutin, dict):
                continue

            previous_theme = clean(scrutin.get("theme"))

            improve_explanation(scrutin)
            correct_stats(scrutin)

            new_theme = guess_theme(searchable_text(scrutin))
            scrutin["theme"] = new_theme

            uid = clean(scrutin.get("uid"))
            if uid:
                uid_map[uid] = scrutin

            try:
                year = int(scrutin.get("year") or clean(scrutin.get("date"))[:4])
            except Exception:
                year = 0

            if year:
                year_vote_counts[year] += int(
                    scrutin.get("stats", {}).get("total_votes", 0)
                )

            if previous_theme != new_theme:
                changed += 1

        write_json(path, payload)

    return uid_map, year_vote_counts, changed


def update_group_detail_files(uid_map):
    updated_files = 0

    if not GROUPS_DIR.exists():
        return updated_files

    for path in sorted(GROUPS_DIR.rglob("*.json")):
        payload = load_json(path)

        if not isinstance(payload, dict):
            continue

        scrutins = payload.get("scrutins", [])
        if not isinstance(scrutins, list):
            continue

        theme_counts = Counter()

        for row in scrutins:
            if not isinstance(row, dict):
                continue

            uid = clean(row.get("uid"))
            summary = uid_map.get(uid, {})

            if summary:
                row["theme"] = (
                    summary.get("theme")
                    or row.get("theme")
                    or "Autres"
                )
                row["en_clair"] = summary.get("en_clair") or ""
                row["ce_qui_etait_vote"] = (
                    summary.get("ce_qui_etait_vote") or ""
                )

            theme = clean(row.get("theme")) or "Autres"
            theme_counts[theme] += 1

        payload["themes"] = [
            {"theme": theme, "scrutins": count}
            for theme, count in sorted(
                theme_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]

        write_json(path, payload)
        updated_files += 1

    return updated_files


def update_group_index():
    path = BASE_DIR / "groupes.json"
    if not path.exists():
        return

    payload = load_json(path)
    entries = payload.get("groupes", [])

    if not isinstance(entries, list):
        return

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        relative = clean(entry.get("file"))
        if not relative:
            continue

        detail_path = Path(relative)
        if not detail_path.exists():
            continue

        detail = load_json(detail_path)
        entry["themes"] = detail.get(
            "themes",
            entry.get("themes", []),
        )

    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json(path, payload)


def update_search_file(uid_map):
    path = BASE_DIR / "search.json"
    if not path.exists():
        return

    payload = load_json(path)
    payload["themes"] = sorted(
        {
            clean(scrutin.get("theme"))
            for scrutin in uid_map.values()
            if clean(scrutin.get("theme"))
        }
    )
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json(path, payload)


def update_index(year_vote_counts):
    path = BASE_DIR / "index.json"
    if not path.exists():
        return

    payload = load_json(path)
    years = payload.get("years", {})

    if isinstance(years, dict):
        for year_key, year_data in years.items():
            if not isinstance(year_data, dict):
                continue

            try:
                year = int(year_key)
            except Exception:
                continue

            counts = year_data.setdefault("counts", {})
            counts["votes"] = int(year_vote_counts.get(year, 0))

    default_year = str(payload.get("default_year") or "")

    if default_year and isinstance(years, dict):
        default_data = years.get(default_year, {})
        if isinstance(default_data, dict):
            payload["counts"] = default_data.get(
                "counts",
                payload.get("counts", {}),
            )

    payload["version"] = VERSION
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json(path, payload)


def print_audit(uid_map):
    sample = uid_map.get("VTANR5L17V8434")

    print("")
    print("======================================================")
    print(" POSTPROCESS DATA — V5.1 AUDITED")
    print("======================================================")
    print("")
    print("Scrutins corrigés / indexés :", len(uid_map))

    if sample:
        stats = sample.get("stats", {})
        print("")
        print("Contrôle scrutin 8434 :")
        print(" - thème :", sample.get("theme"))
        print(" - votants :", stats.get("votants"))
        print(" - suffrages exprimés :", stats.get("suffrages_exprimes"))
        print(" - députés recensés :", stats.get("total_recenses"))
        print(" - en clair :", sample.get("en_clair"))

    print("")


def main():
    if not BASE_DIR.exists():
        raise RuntimeError(
            "data/current est introuvable. "
            "Exécutez build_data.py avant postprocess_data.py."
        )

    uid_map, year_vote_counts, theme_changes = process_month_files()

    group_files = update_group_detail_files(uid_map)
    update_group_index()
    update_search_file(uid_map)
    update_index(year_vote_counts)

    print_audit(uid_map)

    print("Thèmes modifiés :", theme_changes)
    print("Fichiers groupe mis à jour :", group_files)
    print("Version publiée :", VERSION)
    print("Post-traitement terminé.")


if __name__ == "__main__":
    main()

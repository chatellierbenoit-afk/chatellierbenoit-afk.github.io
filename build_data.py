import json
import re
import ssl
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional


SCRUTINS_URL = "https://data.assemblee-nationale.fr/static/openData/repository/17/loi/scrutins/Scrutins.json.zip"
DEPUTES_URL = "https://data.assemblee-nationale.fr/static/openData/repository/17/amo/deputes_actifs_mandats_actifs_organes/AMO10_deputes_actifs_mandats_actifs_organes.json.zip"

SSL_CONTEXT = ssl.create_default_context()


@dataclass
class Config:
    year: int
    legislature: int
    data_dir: Path
    archives_dir: Path
    min_scrutins: int = 1
    min_deputes: int = 50
    min_groupes: int = 3

    @property
    def current_dir(self) -> Path:
        return self.data_dir / "current"

    @property
    def index_path(self) -> Path:
        return self.current_dir / "index.json"

    @property
    def scrutins_path(self) -> Path:
        return self.current_dir / "scrutins.json"

    @property
    def deputes_path(self) -> Path:
        return self.current_dir / "deputes.json"

    @property
    def groupes_path(self) -> Path:
        return self.current_dir / "groupes.json"

    @property
    def departements_path(self) -> Path:
        return self.current_dir / "departements.json"


def load_config() -> Config:
    root = Path(__file__).resolve().parent.parent
    data_dir = root / "data"
    archives_dir = data_dir / "archives"

    return Config(
        year=datetime.now().year,
        legislature=17,
        data_dir=data_dir,
        archives_dir=archives_dir,
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def slugify(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def download_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(request, context=SSL_CONTEXT, timeout=120) as response:
        return response.read()


def open_first_json_from_zip(zip_bytes: bytes) -> Dict[str, Any]:
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name.lower().endswith(".json"):
                return json.loads(zf.read(name).decode("utf-8"))
    raise RuntimeError("Aucun fichier JSON trouvé dans l’archive zip.")


def normalize_vote_label(value: str) -> str:
    raw = (value or "").strip().lower()

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

    return mapping.get(raw, value or "Inconnu")


def normalize_groupe(value: str) -> str:
    value = clean_text(value)

    aliases = {
        "lfi": "LFI-NFP",
        "lfi-nupes": "LFI-NFP",
        "la france insoumise": "LFI-NFP",
        "rn": "RN",
        "renaissance": "Renaissance",
        "lr": "LR",
        "modem": "MoDem",
    }

    key = value.lower()
    return aliases.get(key, value or "Inconnu")


def normalize_departement(value: str) -> str:
    return clean_text(value)


def guess_theme_from_text(text: str) -> str:
    t = (text or "").lower()

    rules = [
        ("Budget / Finances", ["budget", "finance", "fiscal", "plf", "plfr", "plfss", "taxe", "impôt"]),
        ("Santé", ["santé", "hôpital", "médical", "soin"]),
        ("Éducation", ["éducation", "école", "université", "enseignement"]),
        ("Écologie / Énergie", ["écologie", "climat", "énergie", "environnement"]),
        ("Travail / Social", ["travail", "emploi", "retraite", "social", "salaires", "chômage"]),
        ("Justice / Sécurité", ["justice", "sécurité", "police", "prison", "pénal"]),
        ("Immigration", ["immigration", "asile", "étranger"]),
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


def fetch_all_sources(config: Config) -> Dict[str, Any]:
    print("Téléchargement des scrutins officiels Assemblée…")
    scrutins_payload = open_first_json_from_zip(download_bytes(SCRUTINS_URL))

    print("Téléchargement des députés actifs Assemblée…")
    deputes_payload = open_first_json_from_zip(download_bytes(DEPUTES_URL))

    return {
        "scrutins_payload": scrutins_payload,
        "deputes_payload": deputes_payload,
        "civix_payload": {},
    }


def extract_all_deputes(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    export = payload.get("export", payload)
    acteurs_block = export.get("acteurs", {})
    acteurs = acteurs_block.get("acteur", acteurs_block)
    return ensure_list(acteurs)


def extract_all_scrutins(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    root = payload.get("scrutins", payload)
    scrutins = root.get("scrutin", root)
    return ensure_list(scrutins)


def extract_depute_uid(acteur: Dict[str, Any]) -> str:
    return clean_text(str(acteur.get("uid", "")))


def extract_prenom(acteur: Dict[str, Any]) -> str:
    etat_civil = acteur.get("etatCivil", {})
    ident = etat_civil.get("ident", {})
    return clean_text(
        str(
            ident.get("prenom")
            or ident.get("prenomUsuel")
            or ""
        )
    )


def extract_nom_famille(acteur: Dict[str, Any]) -> str:
    etat_civil = acteur.get("etatCivil", {})
    ident = etat_civil.get("ident", {})
    return clean_text(
        str(
            ident.get("nom")
            or ident.get("nomFamille")
            or ""
        )
    )


def extract_nom_complet(acteur: Dict[str, Any]) -> str:
    return clean_text(f"{extract_prenom(acteur)} {extract_nom_famille(acteur)}")


def extract_groupe(acteur: Dict[str, Any]) -> str:
    return ""


def extract_departement(acteur: Dict[str, Any]) -> str:
    # Le format AMO n’expose pas toujours le département de façon simple.
    # On tente plusieurs endroits courants.
    adresses = ensure_list((acteur.get("adresses") or {}).get("adresse"))

    for adr in adresses:
        if not isinstance(adr, dict):
            continue

        type_adr = clean_text(str(adr.get("type", ""))).lower()
        texte = clean_text(str(adr.get("texte", "")))

        if ("departement" in type_adr or "département" in type_adr) and texte:
            return texte

    mandats = ensure_list((acteur.get("mandats") or {}).get("mandat"))
    for mandat in mandats:
        if not isinstance(mandat, dict):
            continue

        election = mandat.get("election", {})
        lieu = election.get("lieu", {}) if isinstance(election, dict) else {}

        departement = clean_text(str(lieu.get("departement", "")))
        if departement:
            return departement

    return ""


def extract_circonscription(acteur: Dict[str, Any]) -> str:
    adresses = ensure_list((acteur.get("adresses") or {}).get("adresse"))

    for adr in adresses:
        if not isinstance(adr, dict):
            continue

        type_adr = clean_text(str(adr.get("type", ""))).lower()
        texte = clean_text(str(adr.get("texte", "")))

        if "circonscription" in type_adr and texte:
            return texte

    mandats = ensure_list((acteur.get("mandats") or {}).get("mandat"))
    for mandat in mandats:
        if not isinstance(mandat, dict):
            continue

        election = mandat.get("election", {})
        lieu = election.get("lieu", {}) if isinstance(election, dict) else {}

        circo = clean_text(str(lieu.get("numCirco", "")))
        if circo:
            return circo

    return ""


def extract_scrutin_uid(scrutin: Dict[str, Any]) -> str:
    return clean_text(str(scrutin.get("uid", scrutin.get("numero", ""))))


def extract_scrutin_numero(scrutin: Dict[str, Any]) -> Optional[int]:
    raw = scrutin.get("numero")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def extract_scrutin_date(scrutin: Dict[str, Any]) -> str:
    return clean_text(str(scrutin.get("dateScrutin", "")))


def extract_scrutin_titre(scrutin: Dict[str, Any]) -> str:
    titre = scrutin.get("titre")
    if titre:
        return clean_text(str(titre))

    numero = scrutin.get("numero")
    if numero:
        return f"Scrutin n°{numero}"

    return "Scrutin sans titre"


def extract_scrutin_description(scrutin: Dict[str, Any]) -> str:
    objet = scrutin.get("objet", {})
    if isinstance(objet, dict):
        return clean_text(str(objet.get("libelle", "") or objet.get("titre", "")))
    return ""


def extract_votants_from_bucket(node: Any) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []

    if isinstance(node, dict):
        if "votant" in node:
            votants = node["votant"]
            result.extend(ensure_list(votants))
        elif "acteurRef" in node:
            result.append(node)
        else:
            for value in node.values():
                result.extend(extract_votants_from_bucket(value))

    elif isinstance(node, list):
        for item in node:
            result.extend(extract_votants_from_bucket(item))

    return result


def extract_votes_nominatifs(scrutin: Dict[str, Any]) -> List[Dict[str, Any]]:
    votes_raw: List[Dict[str, Any]] = []

    ventilation = scrutin.get("ventilationVotes", {})
    organe = ventilation.get("organe", {})
    groupes = ensure_list((organe.get("groupes") or {}).get("groupe"))

    for groupe in groupes:
        groupe_label = clean_text(
            str(
                groupe.get("libelle")
                or groupe.get("nom")
                or groupe.get("organeRef")
                or "Groupe inconnu"
            )
        )

        decompte = (groupe.get("vote") or {}).get("decompteNominatif", {})

        buckets = [
            ("pours", "Pour"),
            ("contres", "Contre"),
            ("abstentions", "Abstention"),
            ("nonVotants", "Non-votant"),
        ]

        for bucket_key, vote_label in buckets:
            bucket = decompte.get(bucket_key)
            for votant in extract_votants_from_bucket(bucket):
                votes_raw.append({
                    "depute_uid": clean_text(str(votant.get("acteurRef", ""))),
                    "vote": vote_label,
                    "groupe": groupe_label,
                })

    return votes_raw


def extract_vote_depute_uid(vote_raw: Dict[str, Any]) -> str:
    return clean_text(str(vote_raw.get("depute_uid", "")))


def extract_vote_label(vote_raw: Dict[str, Any]) -> str:
    return clean_text(str(vote_raw.get("vote", "")))


def build_deputes_index(raw_sources: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    deputes_payload = raw_sources["deputes_payload"]
    deputes_index: Dict[str, Dict[str, Any]] = {}

    for acteur in extract_all_deputes(deputes_payload):
        uid = extract_depute_uid(acteur)
        if not uid:
            continue

        groupe = normalize_groupe(extract_groupe(acteur))
        departement = normalize_departement(extract_departement(acteur))

        deputes_index[uid] = {
            "uid": uid,
            "nom": extract_nom_complet(acteur),
            "prenom": extract_prenom(acteur),
            "nom_famille": extract_nom_famille(acteur),
            "groupe": groupe,
            "departement": departement,
            "circonscription": extract_circonscription(acteur),
        }

    return deputes_index


def parse_scrutins_source(raw_sources: Dict[str, Any], year: int) -> List[Dict[str, Any]]:
    scrutins_payload = raw_sources["scrutins_payload"]
    scrutins: List[Dict[str, Any]] = []

    for scrutin in extract_all_scrutins(scrutins_payload):
        date = extract_scrutin_date(scrutin)
        if not date.startswith(str(year)):
            continue

        scrutins.append({
            "uid": extract_scrutin_uid(scrutin),
            "numero": extract_scrutin_numero(scrutin),
            "date": date,
            "titre": extract_scrutin_titre(scrutin),
            "description": extract_scrutin_description(scrutin),
            "votes_raw": extract_votes_nominatifs(scrutin),
        })

    return scrutins


def compute_scrutin_stats(votes: List[Dict[str, Any]]) -> Dict[str, int]:
    pour = sum(1 for v in votes if v["vote"] == "Pour")
    contre = sum(1 for v in votes if v["vote"] == "Contre")
    abstention = sum(1 for v in votes if v["vote"] == "Abstention")
    non_votant = sum(1 for v in votes if v["vote"] == "Non-votant")

    return {
        "pour": pour,
        "contre": contre,
        "abstention": abstention,
        "non_votant": non_votant,
        "total_exprimes": pour + contre + abstention,
        "total_votes": pour + contre + abstention + non_votant,
    }


def compute_scrutin_groupes_summary(votes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    for vote in votes:
        grouped.setdefault(vote["groupe"], []).append(vote)

    result = []
    for groupe, groupe_votes in sorted(grouped.items(), key=lambda item: item[0]):
        stats = compute_scrutin_stats(groupe_votes)
        result.append({
            "groupe": groupe,
            "pour": stats["pour"],
            "contre": stats["contre"],
            "abstention": stats["abstention"],
            "non_votant": stats["non_votant"],
            "total": stats["total_votes"],
        })

    return result


def compute_scrutin_departements_summary(votes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    for vote in votes:
        departement = vote.get("departement", "")
        if not departement:
            continue
        grouped.setdefault(departement, []).append(vote)

    result = []
    for departement, dep_votes in sorted(grouped.items(), key=lambda item: item[0]):
        stats = compute_scrutin_stats(dep_votes)
        result.append({
            "departement": departement,
            "pour": stats["pour"],
            "contre": stats["contre"],
            "abstention": stats["abstention"],
            "non_votant": stats["non_votant"],
            "total": stats["total_votes"],
        })

    return result


def sort_votes(votes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(votes, key=lambda v: (v.get("groupe", ""), v.get("nom", "")))


def enrich_scrutins(scrutins_raw: List[Dict[str, Any]], deputes_index: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    output = []

    for scrutin in scrutins_raw:
        votes = []

        for vote_raw in scrutin["votes_raw"]:
            depute_uid = extract_vote_depute_uid(vote_raw)
            vote_label = normalize_vote_label(extract_vote_label(vote_raw))

            depute = deputes_index.get(depute_uid, {})
            groupe_vote = normalize_groupe(vote_raw.get("groupe", ""))
            groupe_final = groupe_vote or depute.get("groupe", "Inconnu")

            votes.append({
                "depute_uid": depute_uid,
                "nom": depute.get("nom", "Inconnu"),
                "groupe": groupe_final,
                "vote": vote_label,
                "departement": depute.get("departement", ""),
            })

        titre = clean_text(scrutin["titre"])
        description = clean_text(scrutin["description"])
        theme = guess_theme_from_text(f"{titre} {description}".strip())

        output.append({
            "uid": scrutin["uid"],
            "numero": scrutin["numero"],
            "date": scrutin["date"],
            "titre": titre,
            "description": description,
            "theme": theme,
            "theme_slug": slugify(theme),
            "stats": compute_scrutin_stats(votes),
            "groupes_summary": compute_scrutin_groupes_summary(votes),
            "departements_summary": compute_scrutin_departements_summary(votes),
            "votes": sort_votes(votes),
        })

    output.sort(key=lambda s: s.get("date", ""), reverse=True)
    return output


def increment_vote_counter(target: Dict[str, Any], vote_label: str) -> None:
    if vote_label == "Pour":
        target["votes_pour"] += 1
    elif vote_label == "Contre":
        target["votes_contre"] += 1
    elif vote_label == "Abstention":
        target["votes_abstention"] += 1
    elif vote_label == "Non-votant":
        target["votes_non_votant"] += 1


def build_deputes_summary(scrutins: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_depute: Dict[str, Dict[str, Any]] = {}

    for scrutin in scrutins:
        for vote in scrutin["votes"]:
            uid = vote["depute_uid"] or f"unknown::{vote['nom']}"

            if uid not in by_depute:
                by_depute[uid] = {
                    "uid": uid,
                    "nom": vote["nom"],
                    "prenom": "",
                    "nom_famille": "",
                    "groupe": vote["groupe"],
                    "departement": vote["departement"],
                    "circonscription": "",
                    "active": True,
                    "votes_count": 0,
                    "votes_pour": 0,
                    "votes_contre": 0,
                    "votes_abstention": 0,
                    "votes_non_votant": 0,
                }

            by_depute[uid]["votes_count"] += 1
            increment_vote_counter(by_depute[uid], vote["vote"])

    return sorted(by_depute.values(), key=lambda d: d["nom"])


def build_groupes_summary(scrutins: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_group: Dict[str, Dict[str, Any]] = {}

    for scrutin in scrutins:
        for vote in scrutin["votes"]:
            groupe = vote["groupe"]

            if groupe not in by_group:
                by_group[groupe] = {
                    "nom": groupe,
                    "slug": slugify(groupe),
                    "deputes_set": set(),
                    "votes_count": 0,
                    "votes_pour": 0,
                    "votes_contre": 0,
                    "votes_abstention": 0,
                    "votes_non_votant": 0,
                }

            by_group[groupe]["deputes_set"].add(vote["depute_uid"] or vote["nom"])
            by_group[groupe]["votes_count"] += 1
            increment_vote_counter(by_group[groupe], vote["vote"])

    result = []
    for data in sorted(by_group.values(), key=lambda g: g["nom"]):
        result.append({
            "nom": data["nom"],
            "slug": data["slug"],
            "deputes_count": len(data["deputes_set"]),
            "votes_count": data["votes_count"],
            "votes_pour": data["votes_pour"],
            "votes_contre": data["votes_contre"],
            "votes_abstention": data["votes_abstention"],
            "votes_non_votant": data["votes_non_votant"],
        })

    return result


def build_departements_summary(scrutins: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_dep: Dict[str, Dict[str, Any]] = {}

    for scrutin in scrutins:
        for vote in scrutin["votes"]:
            departement = vote.get("departement", "")
            if not departement:
                continue

            if departement not in by_dep:
                by_dep[departement] = {
                    "nom": departement,
                    "slug": slugify(departement),
                    "deputes_set": set(),
                    "votes_count": 0,
                    "groupes_set": set(),
                }

            by_dep[departement]["deputes_set"].add(vote["depute_uid"] or vote["nom"])
            by_dep[departement]["groupes_set"].add(vote["groupe"])
            by_dep[departement]["votes_count"] += 1

    result = []
    for data in sorted(by_dep.values(), key=lambda d: d["nom"]):
        result.append({
            "nom": data["nom"],
            "slug": data["slug"],
            "deputes_count": len(data["deputes_set"]),
            "votes_count": data["votes_count"],
            "groupes": sorted(data["groupes_set"]),
        })

    return result


def validate_output(
    config: Config,
    scrutins: List[Dict[str, Any]],
    deputes: List[Dict[str, Any]],
    groupes: List[Dict[str, Any]],
    departements: List[Dict[str, Any]],
) -> None:
    if len(scrutins) < config.min_scrutins:
        raise RuntimeError(f"Nombre de scrutins trop faible : {len(scrutins)}")

    if len(deputes) < config.min_deputes:
        raise RuntimeError(f"Nombre de députés trop faible : {len(deputes)}")

    if len(groupes) < config.min_groupes:
        raise RuntimeError(f"Nombre de groupes trop faible : {len(groupes)}")

    invalid_votes = []
    allowed_votes = {"Pour", "Contre", "Abstention", "Non-votant"}

    for scrutin in scrutins:
        if not scrutin.get("titre"):
            raise RuntimeError(f"Scrutin sans titre : {scrutin.get('uid')}")

        for vote in scrutin.get("votes", []):
            if vote["vote"] not in allowed_votes:
                invalid_votes.append(vote["vote"])

    if invalid_votes:
        raise RuntimeError(f"Libellés de vote invalides : {sorted(set(invalid_votes))}")


def write_output_files(
    config: Config,
    scrutins: List[Dict[str, Any]],
    deputes: List[Dict[str, Any]],
    groupes: List[Dict[str, Any]],
    departements: List[Dict[str, Any]],
) -> None:
    updated_at = now_iso()
    total_votes = sum(scrutin["stats"]["total_votes"] for scrutin in scrutins)

    index_json = {
        "version": "2.0",
        "legislature": config.legislature,
        "year": config.year,
        "updated_at": updated_at,
        "counts": {
            "scrutins": len(scrutins),
            "deputes": len(deputes),
            "groupes": len(groupes),
            "departements": len(departements),
            "votes": total_votes,
        },
        "sources": {
            "scrutins": "Assemblée nationale",
            "deputes": "Assemblée nationale",
        },
        "files": {
            "scrutins": "data/current/scrutins.json",
            "deputes": "data/current/deputes.json",
            "groupes": "data/current/groupes.json",
            "departements": "data/current/departements.json",
        },
    }

    scrutins_json = {
        "year": config.year,
        "updated_at": updated_at,
        "scrutins": scrutins,
    }

    deputes_json = {
        "updated_at": updated_at,
        "deputes": deputes,
    }

    groupes_json = {
        "updated_at": updated_at,
        "groupes": groupes,
    }

    departements_json = {
        "updated_at": updated_at,
        "departements": departements,
    }

    write_json(config.index_path, index_json)
    write_json(config.scrutins_path, scrutins_json)
    write_json(config.deputes_path, deputes_json)
    write_json(config.groupes_path, groupes_json)
    write_json(config.departements_path, departements_json)


def archive_snapshot(config: Config, scrutins: List[Dict[str, Any]]) -> None:
    archived_at = now_iso()
    date_str = datetime.now().strftime("%Y-%m-%d")
    year_dir = config.archives_dir / str(config.year)
    archive_path = year_dir / f"{date_str}.json"

    archive_json = {
        "year": config.year,
        "archived_at": archived_at,
        "scrutins": scrutins,
    }

    write_json(archive_path, archive_json)


def print_final_report(
    scrutins: List[Dict[str, Any]],
    deputes: List[Dict[str, Any]],
    groupes: List[Dict[str, Any]],
    departements: List[Dict[str, Any]],
) -> None:
    total_votes = sum(scrutin["stats"]["total_votes"] for scrutin in scrutins)

    print("Mise à jour terminée")
    print(f"Scrutins : {len(scrutins)}")
    print(f"Députés : {len(deputes)}")
    print(f"Groupes : {len(groupes)}")
    print(f"Départements : {len(departements)}")
    print(f"Votes : {total_votes}")


def main() -> None:
    config = load_config()
    raw_sources = fetch_all_sources(config)

    deputes_index = build_deputes_index(raw_sources)
    scrutins_raw = parse_scrutins_source(raw_sources, config.year)

    scrutins = enrich_scrutins(scrutins_raw, deputes_index)
    deputes = build_deputes_summary(scrutins)
    groupes = build_groupes_summary(scrutins)
    departements = build_departements_summary(scrutins)

    validate_output(config, scrutins, deputes, groupes, departements)
    write_output_files(config, scrutins, deputes, groupes, departements)
    archive_snapshot(config, scrutins)
    print_final_report(scrutins, deputes, groupes, departements)


if __name__ == "__main__":
    main()

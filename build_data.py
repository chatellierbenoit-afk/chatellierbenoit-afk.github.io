import json
import ssl
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

OUTPUT_FILE = Path("data.json")

SCRUTINS_URL = "http://data.assemblee-nationale.fr/static/openData/repository/17/loi/scrutins/Scrutins.json.zip"
AMO50_URL = "http://data.assemblee-nationale.fr/static/openData/repository/17/amo/acteurs_mandats_organes_divises/AMO50_acteurs_mandats_organes_divises.json.zip"

SSL_CONTEXT = ssl.create_default_context()


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


def get_nested_uid(value):
    if isinstance(value, dict):
        return clean_text(value.get("#text") or value.get("text") or value.get("uid") or "")
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

    acteurs = {}
    organes = {}
    actor_meta = {}

    # 1) Acteurs : noms des députés
    for name in zf.namelist():
        if not (name.startswith("acteur/") and name.endswith(".json")):
            continue

        data = json.loads(zf.read(name).decode("utf-8"))
        acteur = data.get("acteur", {})
        uid = get_nested_uid(acteur.get("uid"))

        etat_civil = acteur.get("etatCivil", {})
        ident = etat_civil.get("ident", {})
        prenom = clean_text(ident.get("prenom") or ident.get("prenomUsuel") or "")
        nom = clean_text(ident.get("nom") or ident.get("nomFamille") or "")
        nom_complet = clean_text(f"{prenom} {nom}")

        if uid:
            acteurs[uid] = nom_complet or uid
            actor_meta[uid] = {
                "nom": nom_complet or uid,
                "groupe": "",
                "departement": "",
                "circonscription": "",
            }

    print("Acteurs chargés :", len(acteurs))

    # 2) Organes : groupes et circonscriptions
    for name in zf.namelist():
        if not (name.startswith("organe/") and name.endswith(".json")):
            continue

        data = json.loads(zf.read(name).decode("utf-8"))
        organe = data.get("organe", {})
        uid = clean_text(organe.get("uid"))
        code_type = clean_text(organe.get("codeType"))
        libelle = clean_text(organe.get("libelle"))
        libelle_abrev = clean_text(organe.get("libelleAbrev"))
        libelle_abrege = clean_text(organe.get("libelleAbrege"))

        departement = ""
        region = ""

        lieu = organe.get("lieu", {})
        if isinstance(lieu, dict):
            dep = lieu.get("departement", {})
            reg = lieu.get("region", {})
            if isinstance(dep, dict):
                departement = clean_text(dep.get("libelle"))
            if isinstance(reg, dict):
                region = clean_text(reg.get("libelle"))

        organes[uid] = {
            "uid": uid,
            "codeType": code_type,
            "libelle": libelle,
            "libelleAbrev": libelle_abrev,
            "libelleAbrege": libelle_abrege,
            "departement": departement,
            "region": region,
        }

    print("Organes chargés :", len(organes))

    # 3) Mandats : relier acteurs -> groupe + département/circonscription
    for name in zf.namelist():
        if not (name.startswith("mandat/") and name.endswith(".json")):
            continue

        data = json.loads(zf.read(name).decode("utf-8"))
        mandat = data.get("mandat", {})

        acteur_ref = clean_text(mandat.get("acteurRef"))
        legislature = clean_text(mandat.get("legislature"))
        type_organe = clean_text(mandat.get("typeOrgane"))
        date_fin = clean_text(mandat.get("dateFin"))

        organe_ref = ""
        organes_block = mandat.get("organes", {})
        if isinstance(organes_block, dict):
            organe_ref = clean_text(organes_block.get("organeRef"))

        if not acteur_ref or acteur_ref not in actor_meta:
            continue

        # On privilégie la législature 17
        if legislature and legislature != "17":
            continue

        organe_info = organes.get(organe_ref, {})
        code_type = organe_info.get("codeType", "")

        # Groupe politique courant
        if type_organe == "GP" or code_type == "GP":
            label = (
                organe_info.get("libelleAbrev")
                or organe_info.get("libelleAbrege")
                or organe_info.get("libelle")
                or organe_ref
            )
            if label:
                actor_meta[acteur_ref]["groupe"] = label

        # Circonscription / département
        if code_type == "CIRCONSCRIPTION":
            actor_meta[acteur_ref]["circonscription"] = organe_info.get("libelle", "")
            actor_meta[acteur_ref]["departement"] = organe_info.get("departement", "")

        # Fallback : parfois l'élection contient un lieu
        election = mandat.get("election", {})
        if isinstance(election, dict):
            lieu = election.get("lieu", {})
            if isinstance(lieu, dict):
                dep = clean_text(lieu.get("numDepartement") or lieu.get("departement"))
                if dep and not actor_meta[acteur_ref]["departement"]:
                    actor_meta[acteur_ref]["departement"] = dep

    deputes_detectes = sum(1 for v in actor_meta.values() if v["nom"])
    groupes_detectes = sum(1 for v in actor_meta.values() if v["groupe"])
    dep_detectes = sum(1 for v in actor_meta.values() if v["departement"])

    print("Députés enrichis :", deputes_detectes)
    print("Avec groupe :", groupes_detectes)
    print("Avec département :", dep_detectes)

    return actor_meta, organes


def load_scrutins(actor_meta, organes):
    print("Chargement scrutins…")
    raw = download(SCRUTINS_URL)
    zf = zipfile.ZipFile(BytesIO(raw))

    scrutins = []

    json_files = [n for n in zf.namelist() if n.endswith(".json")]
    print("Fichiers scrutins :", len(json_files))

    for name in json_files:
        data = json.loads(zf.read(name).decode("utf-8"))

        # certains fichiers sont {"scrutin": {...}}
        scrutin = data.get("scrutin", data)

        uid = clean_text(scrutin.get("uid"))
        numero = scrutin.get("numero")
        date = clean_text(scrutin.get("dateScrutin"))
        titre = clean_text(scrutin.get("titre"))

        objet = scrutin.get("objet", {})
        description = ""
        if isinstance(objet, dict):
            description = clean_text(objet.get("libelle") or objet.get("titre") or "")

        votes = []

        ventilation = scrutin.get("ventilationVotes", {})
        organe = ventilation.get("organe", {})
        groupes = ensure_list((organe.get("groupes") or {}).get("groupe"))

        for groupe in groupes:
            groupe_uid = clean_text(
                groupe.get("organeRef")
                or groupe.get("uid")
                or ""
            )

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

            buckets = [
                ("pours", "Pour"),
                ("contres", "Contre"),
                ("abstentions", "Abstention"),
                ("nonVotants", "Non-votant"),
            ]

            for bucket_key, vote_label in buckets:
                bucket = decompte.get(bucket_key)
                votants = extract_votants_from_bucket(bucket)

                for v in votants:
                    acteur_ref = clean_text(v.get("acteurRef"))
                    depute = actor_meta.get(acteur_ref, {})

                    votes.append({
                        "nom": depute.get("nom") or acteur_ref or "Inconnu",
                        "groupe": depute.get("groupe") or groupe_nom or "Inconnu",
                        "vote": vote_label,
                        "origine": depute.get("departement", ""),
                        "departement": depute.get("departement", "")
                    })

        if votes:
            full_text = f"{titre} {description}".strip()
            scrutins.append({
                "id": uid or str(numero or ""),
                "uid": uid or str(numero or ""),
                "numero": numero,
                "titre": titre or f"Scrutin n°{numero}",
                "description": description,
                "date": date,
                "theme": guess_theme(full_text),
                "votes": votes
            })

    scrutins.sort(key=lambda s: s.get("date", ""), reverse=True)
    return scrutins


def main():
    actor_meta, organes = load_amo50()
    scrutins = load_scrutins(actor_meta, organes)

    deputes = sorted({v["nom"] for s in scrutins for v in s["votes"] if v["nom"]})
    groupes = sorted({v["groupe"] for s in scrutins for v in s["votes"] if v["groupe"]})

    output = {
        "meta": {
            "source_votes": "Assemblée nationale open data - Scrutins.json.zip",
            "source_deputes": "Assemblée nationale open data - AMO50 acteurs/mandats/organes divisés",
            "nombre_scrutins": len(scrutins),
            "nombre_deputes_detectes": len(deputes),
            "nombre_groupes_detectes": len(groupes)
        },
        "scrutins": scrutins
    }

    OUTPUT_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("Scrutins :", len(scrutins))
    print("Députés :", len(deputes))
    print("Groupes :", len(groupes))
    print(f"Fichier écrit : {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

import json
import ssl
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

OUTPUT_FILE = Path("data.json")

SCRUTINS_URL = "https://data.assemblee-nationale.fr/static/openData/repository/17/loi/scrutins/Scrutins.json.zip"
AMO_URL = "https://data.assemblee-nationale.fr/static/openData/repository/17/amo/deputes_actifs_mandats_actifs_organes/AMO10_deputes_actifs_mandats_actifs_organes.json.zip"

ssl_context = ssl.create_default_context()

def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=ssl_context, timeout=120) as response:
        return response.read()

def ensure_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]

def open_json_from_zip(zip_bytes: bytes):
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name.lower().endswith(".json"):
                return json.loads(zf.read(name).decode("utf-8"))
    raise RuntimeError("Aucun JSON trouvé dans l’archive zip.")

def normalize_vote_label(raw):
    value = (raw or "").strip().lower()
    mapping = {
        "pour": "Pour",
        "pours": "Pour",
        "contre": "Contre",
        "contres": "Contre",
        "abstention": "Abstention",
        "abstentions": "Abstention",
        "nonvotant": "Non-votant",
        "nonvotants": "Non-votant",
        "non-votant": "Non-votant",
        "non-votants": "Non-votant",
    }
    return mapping.get(value, raw or "Inconnu")

def guess_theme(text: str) -> str:
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
        ("Culture / Médias", ["culture", "audiovisuel", "presse", "patrimoine", "culturels"]),
        ("Défense / International", ["défense", "armée", "europe", "international"]),
        ("Logement / Transports", ["logement", "transport", "mobilité", "ferroviaire"]),
    ]
    for theme, keywords in rules:
        if any(k in t for k in keywords):
            return theme
    return "Autres"

def extract_votants(node):
    out = []

    if isinstance(node, dict):
        if "votant" in node:
            votants = node["votant"]
            if isinstance(votants, list):
                out.extend(votants)
            else:
                out.append(votants)
        elif "acteurRef" in node:
            out.append(node)
        else:
            for value in node.values():
                out.extend(extract_votants(value))

    elif isinstance(node, list):
        for item in node:
            out.extend(extract_votants(item))

    return out

def extract_deputes_from_amo(payload):
    """
    Construit un index par uid acteur :
    {
      "PA720606": {"nom": "...", "origine": "..."}
    }
    """
    index = {}

    export = payload.get("export") or payload

    acteurs_block = export.get("acteurs") or export.get("acteur") or {}
    acteurs = acteurs_block.get("acteur") if isinstance(acteurs_block, dict) else acteurs_block
    acteurs = ensure_list(acteurs)

    for acteur in acteurs:
        uid = acteur.get("uid", "")

        etat_civil = acteur.get("etatCivil", {})
        ident = etat_civil.get("ident", {})

        prenom = ident.get("prenom", "") or ident.get("prenomUsuel", "")
        nom = ident.get("nom", "") or ident.get("nomFamille", "")
        nom_complet = f"{prenom} {nom}".strip()

        adresses = ensure_list(acteur.get("adresses", {}).get("adresse"))
        circo = ""
        departement = ""

        for adr in adresses:
            if not isinstance(adr, dict):
                continue
            type_adr = (adr.get("type") or "").lower()
            texte = (adr.get("texte") or "").strip()
            if not texte:
                continue
            if "circonscription" in type_adr and not circo:
                circo = texte
            if ("departement" in type_adr or "département" in type_adr) and not departement:
                departement = texte

        origine_parts = [x for x in [circo, departement] if x]
        origine = " · ".join(origine_parts)

        if uid:
            index[uid] = {
                "nom": nom_complet or uid,
                "origine": origine
            }

    return index

def extract_scrutins(payload, deputes_index):
    root = payload.get("scrutins") or payload
    raw_scrutins = root.get("scrutin") if isinstance(root, dict) else root
    raw_scrutins = ensure_list(raw_scrutins)

    scrutins = []

    for scrutin in raw_scrutins:
        uid = str(scrutin.get("uid") or scrutin.get("numero") or "")
        numero = str(scrutin.get("numero") or "")
        date = scrutin.get("dateScrutin", "")

        titre = (
            scrutin.get("titre")
            or scrutin.get("intitule")
            or f"Scrutin n°{numero}" if numero else f"Scrutin {uid}"
        )

        description = ""
        if isinstance(scrutin.get("objet"), dict):
            description = scrutin["objet"].get("libelle", "") or scrutin["objet"].get("titre", "")

        full_text = f"{titre} {description}".strip()
        theme = guess_theme(full_text)

        votes = []

        ventilation = scrutin.get("ventilationVotes", {})
        organe = ventilation.get("organe", {})
        groupes = ensure_list((organe.get("groupes") or {}).get("groupe"))

        for groupe in groupes:
            groupe_label = (
                groupe.get("libelle")
                or groupe.get("nom")
                or groupe.get("organeRef")
                or "Groupe inconnu"
            )

            decompte = (groupe.get("vote") or {}).get("decompteNominatif", {})

            for bucket_name in ["pours", "contres", "abstentions", "nonVotants"]:
                bucket = decompte.get(bucket_name)
                votants = extract_votants(bucket)

                for votant in votants:
                    acteur_ref = (votant.get("acteurRef") or "").strip()
                    depute_info = deputes_index.get(acteur_ref, {})
                    nom = depute_info.get("nom") or acteur_ref or "Inconnu"
                    origine = depute_info.get("origine", "")

                    votes.append({
                        "nom": nom,
                        "groupe": groupe_label,
                        "vote": normalize_vote_label(bucket_name),
                        "origine": origine
                    })

        if votes:
            scrutins.append({
                "id": uid or numero,
                "uid": uid or numero,
                "titre": titre,
                "description": description,
                "date": date,
                "theme": theme,
                "votes": votes
            })

    scrutins.sort(key=lambda s: s.get("date", ""), reverse=True)
    return scrutins

def main():
    print("Téléchargement des scrutins officiels…")
    scrutins_payload = open_json_from_zip(fetch_bytes(SCRUTINS_URL))

    print("Téléchargement des députés actifs…")
    amo_payload = open_json_from_zip(fetch_bytes(AMO_URL))

    deputes_index = extract_deputes_from_amo(amo_payload)
    scrutins = extract_scrutins(scrutins_payload, deputes_index)

    deputes = sorted({v["nom"] for s in scrutins for v in s["votes"]})
    groupes = sorted({v["groupe"] for s in scrutins for v in s["votes"]})

    output = {
        "meta": {
            "source_votes": "Assemblée nationale open data - Scrutins.json.zip",
            "source_deputes": "Assemblée nationale open data - AMO10 députés actifs",
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

    print("OK")
    print(f"Scrutins : {len(scrutins)}")
    print(f"Députés : {len(deputes)}")
    print(f"Groupes : {len(groupes)}")

if __name__ == "__main__":
    main()

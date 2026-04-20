import json
import ssl
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

OUTPUT_FILE = Path("data.json")

SCRUTINS_URL = "http://data.assemblee-nationale.fr/static/openData/repository/17/votes/Scrutins.json.zip"
AMO_URL = "http://data.assemblee-nationale.fr/static/openData/repository/17/amo/acteurs_mandats_organes_divises/AMO50_acteurs_mandats_organes_divises.json.zip"

SSL_CONTEXT = ssl.create_default_context()

def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=SSL_CONTEXT) as r:
        return r.read()

def load_zip_json(url):
    raw = download(url)
    z = zipfile.ZipFile(BytesIO(raw))
    return z

def main():
    print("Chargement AMO50...")
    z = load_zip_json(AMO_URL)

    acteurs = {}
    groupes = {}
    mandats = {}

    for name in z.namelist():
        if name.startswith("acteur/"):
            data = json.loads(z.read(name).decode("utf-8"))
            uid = data.get("uid")
            prenom = data.get("etatCivil", {}).get("ident", {}).get("prenom", "")
            nom = data.get("etatCivil", {}).get("ident", {}).get("nom", "")
            acteurs[uid] = f"{prenom} {nom}".strip()

        elif name.startswith("organe/"):
            data = json.loads(z.read(name).decode("utf-8"))
            uid = data.get("uid")
            libelle = data.get("libelleAbrev") or data.get("libelle")
            groupes[uid] = libelle

        elif name.startswith("mandat/"):
            data = json.loads(z.read(name).decode("utf-8"))
            acteur_ref = data.get("acteurRef")
            organe_ref = data.get("organes", {}).get("organeRef")
            circo = data.get("election", {}).get("lieu", {}).get("numDepartement")

            if acteur_ref:
                mandats[acteur_ref] = {
                    "groupe": organe_ref,
                    "departement": circo
                }

    print("Acteurs:", len(acteurs))
    print("Groupes:", len(groupes))
    print("Mandats:", len(mandats))

    print("Chargement scrutins...")
    raw = download(SCRUTINS_URL)
    z2 = zipfile.ZipFile(BytesIO(raw))

    data = json.loads(z2.read(z2.namelist()[0]).decode("utf-8"))

    scrutins = []

    for s in data["scrutins"]["scrutin"]:

        uid = s["uid"]
        titre = s.get("titre", "")
        date = s.get("dateScrutin", "")

        votes = []

        groupes_votes = s.get("ventilationVotes", {}).get("organe", [])

        for g in groupes_votes:
            groupe_uid = g.get("organeRef")

            for pos in ["pour", "contre", "abstention", "nonVotant"]:
                bloc = g.get("vote", {}).get(pos, {})
                votants = bloc.get("votant", [])

                if isinstance(votants, dict):
                    votants = [votants]

                for v in votants:
                    acteur = v.get("acteurRef")
                    nom = acteurs.get(acteur, acteur)

                    mandat = mandats.get(acteur, {})
                    groupe_nom = groupes.get(mandat.get("groupe"), "Inconnu")
                    departement = mandat.get("departement", "")

                    votes.append({
                        "nom": nom,
                        "groupe": groupe_nom,
                        "vote": pos,
                        "origine": departement
                    })

        scrutins.append({
            "id": uid,
            "titre": titre,
            "date": date,
            "votes": votes
        })

    OUTPUT_FILE.write_text(json.dumps({
        "meta": {
            "nombre_scrutins": len(scrutins)
        },
        "scrutins": scrutins
    }, indent=2, ensure_ascii=False))

    print("Scrutins:", len(scrutins))

if __name__ == "__main__":
    main()

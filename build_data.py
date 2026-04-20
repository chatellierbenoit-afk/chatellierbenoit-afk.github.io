import json
import requests
from pathlib import Path

OUTPUT_FILE = Path("data.json")

URL = "https://www.data.gouv.fr/fr/datasets/r/3b2e4c74-4e5f-4f69-bc8d-2e4e6a5b0e2b"

def main():
    print("Téléchargement des données...")

    response = requests.get(URL)
    data = response.json()

    scrutins = []

    for item in data[:200]:  # limite pour éviter trop lourd
        scrutin_id = str(item.get("scrutin_numero", ""))
        titre = item.get("scrutin_titre", "")
        date = item.get("scrutin_date", "")

        votes = []

        votes.append({
            "nom": item.get("depute_nom", "Inconnu"),
            "groupe": item.get("groupe_sigle", "Inconnu"),
            "vote": item.get("vote_position", "Inconnu")
        })

        scrutins.append({
            "id": scrutin_id,
            "uid": scrutin_id,
            "titre": titre,
            "date": date,
            "theme": "Politique",
            "votes": votes
        })

    deputes = set()
    groupes = set()

    for s in scrutins:
        for v in s["votes"]:
            deputes.add(v["nom"])
            groupes.add(v["groupe"])

    output = {
        "meta": {
            "source_votes": "data.gouv.fr",
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
    print(f"Scrutins: {len(scrutins)}")
    print(f"Députés: {len(deputes)}")

if __name__ == "__main__":
    main()

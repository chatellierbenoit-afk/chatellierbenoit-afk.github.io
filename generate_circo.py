import requests
import json
import time

result = {}

print("Récupération des communes...")

communes = requests.get(
    "https://geo.api.gouv.fr/communes?fields=code,nom,codePostal,departement&format=json"
).json()

print("Total communes:", len(communes))

for c in communes:

    cp_list = c.get("codePostal")

    if not cp_list:
        continue

    cp = cp_list if isinstance(cp_list, str) else cp_list[0]

    departement = c.get("departement", {}).get("nom", "")

    # ⚠️ approximation initiale (on améliorera après)
    result[cp] = {
        "departement": departement,
        "circo": ""
    }

# sauvegarde
with open("data/circonscriptions.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("Fichier généré !")

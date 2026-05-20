import requests
import json
import time

result = {}

print("Récupération des communes...")

communes = requests.get(
    "https://geo.api.gouv.fr/communes?fields=code,codePostal,departement,nom&format=json"
).json()

print(f"Total communes : {len(communes)}")

for c in communes:
    cp_list = c.get("codePostal", [])

    if not cp_list:
        continue

    cp = cp_list[0]
    departement = c.get("departement", {}).get("nom", "")

    # ⚠️ ici on ne connait PAS la vraie circo → placeholder
    result[str(cp)] = {
        "departement": departement,
        "circo": ""  # on remplira plus tard
    }

# sauvegarde
with open("circonscriptions.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("Fichier complet généré !")

# Consulter les statistiques du site

Ouvrir https://analytics.google.com/ et choisir la propriété « Que vote mon député ? ».
L’identifiant de mesure installé est `G-BYF49HVYSN`.

## Visiteurs et pages

Dans les rapports, « Temps réel » permet de vérifier une visite récente.
Les rapports sur le trafic indiquent le nombre d’utilisateurs et les sources des visites.
Le rapport « Pages et écrans » indique les pages consultées ; utiliser le titre de page
pour distinguer les députés, les groupes et les sujets des scrutins.

## Mots recherchés sur le site

Dans Explorer, créer une exploration libre avec la dimension « Terme de recherche »
en lignes et « Nombre d’événements » en valeurs. Ajouter un filtre sur
« Nom de l’événement » égal à `view_search_results`.

L’événement complémentaire `search_no_results` compte les recherches sans résultat.
Pour analyser leur texte séparément, créer une dimension personnalisée de portée
Événement sur le paramètre `search_term`, puis filtrer sur `search_no_results`.

Deux autres paramètres sont disponibles pour des dimensions ou métriques personnalisées :
`search_area` (accueil, depute, groupe, scrutin ou circonscriptions) et `results_count`
(nombre de résultats proposés, limité à 40 sur l’accueil).

Les recherches sont envoyées après 1,5 seconde sans nouvelle saisie, ou lors de
la validation. La saisie puis le clic sur Rechercher ne comptent pas deux fois
une même recherche. Les coordonnées détectées ne sont pas envoyées.

## Vérifier l’installation

Ouvrir le site, accepter les statistiques, consulter une fiche et effectuer une
recherche. Vérifier ensuite le rapport Temps réel dans Analytics. La réception
effective doit être vérifiée dans le compte : les tests du code n’envoient aucune
fausse visite à Google. Un bloqueur de publicité peut empêcher la collecte.

La collecte commence à l’installation, sans historique rétroactif. Elle concerne
les visiteurs qui acceptent le suivi ; elle ne représente donc pas toutes les visites.
Le choix est modifiable avec « Choix des cookies » en bas de chaque page.
Les recherches sur Google sont distinctes : leur analyse nécessite Search Console.

Documentation Google :
https://support.google.com/analytics/table/13948007
https://developers.google.com/tag-platform/security/concepts/consent-mode

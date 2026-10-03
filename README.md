# WELTO — Caisse et gestion de boutique

Application web de point de vente pensée pour les boutiques de Guinée et de Gambie : très légère pour les connexions lentes, une vente en quelques gestes, et des calculs d'argent et de stock vérifiés à chaque étape.

Développée par Aliou Diallo.

## Ce que fait l'application

- **Caisse sur une seule page** : scanner ou rechercher un produit, ajuster les quantités (saisie directe ou `12*` avant le nom/scan), choisir Espèces / Mobile Money / Carte / Crédit, valider. La monnaie à rendre est calculée, le ticket s'imprime sur imprimante thermique.
- **Clients et crédits** : client optionnel ; obligatoire et proposé automatiquement pour une vente à crédit ou un paiement partiel. Suivi des dettes et encaissement des remboursements.
- **Approvisionnement par scan**, sur le modèle de la caisse : on scanne les produits reçus, on ajuste quantité, prix d'achat et prix de vente ; un produit inconnu se crée sur place (ou son code-barres s'associe à un produit existant). Une validation = stock à jour + une dépense pour le bon.
- **Produits et stock** : code-barres, prix promo, pertes, inventaire. Chaque mouvement est tracé avec le stock avant/après.
- **Pilotage** : tableau de bord, rapports (chiffre d'affaires, marge sur prix d'achat réel, encaissements par mode pour la caisse du soir, dépenses, bénéfice net), factures PDF.
- **Rôles** : employé (caisse, ventes, clients) et manager (tout le reste).

## Rigueur des calculs

- Montants en `Decimal` côté serveur et en centimes entiers côté navigateur : jamais de nombre à virgule flottante.
- Le serveur recalcule chaque vente à partir des prix en base. Si le total affiché à la caisse ne correspond plus (prix modifié entre-temps), la vente est refusée et la caisse se met à jour.
- Encaissement dans une transaction unique avec verrouillage des produits : pas de survente, tout ou rien.
- Une vente renvoyée deux fois (réseau coupé, double appui) n'est enregistrée qu'une fois.
- Contraintes dans PostgreSQL : total = sous-total − remise, payé ≤ total, statut « payée » cohérent, stock jamais négatif, journal de stock cohérent.
- Ventes, paiements et journal de stock en lecture seule dans l'admin Django.
- 62 tests automatisés (`python manage.py test`).

## Légèreté

Premier chargement de la caisse : environ 20 Ko compressés (CSS Tailwind 7,5 Ko, JavaScript sans dépendance 9 Ko), contre environ 1,5 Mo pour l'ancienne interface. Le catalogue est gardé dans le navigateur et ne se retélécharge que s'il a changé. La recherche et le scan restent donc instantanés même avec une connexion très lente.

## Technique

- Django 5.2, PostgreSQL (SQLite en développement), uvicorn
- Tailwind CSS 4 (binaire autonome, sans Node.js), JavaScript natif
- Docker, déployé avec Coolify derrière Cloudflare

## Structure

```
Dockerfile, docker-compose.yml   image de production / environnement local complet
DEPLOY.md                        déploiement Coolify + Cloudflare, développement local
blog_pos/
  blog_pos/      réglages Django, URLs
  core/          gabarits de base, CSS/JS, icônes, utilitaires
  order/         caisse, ventes, paiements (order/services.py = moteur de vente)
  product/       produits, catégories, stock
  aprovision/    mouvements de stock, dépenses, rapports (aprovision/services.py = stock)
  client/        clients et crédits
  users/         comptes, rôles, paramètres, mot de passe oublié
  assets/app.css source Tailwind
```

Voir [DEPLOY.md](DEPLOY.md) pour l'installation.

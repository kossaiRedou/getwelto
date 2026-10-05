# Déployer WELTO sur un VPS Hostinger avec Coolify et Cloudflare

Ce guide suppose que Coolify est déjà installé sur le VPS et que le domaine est géré par Cloudflare.
Une boutique = une application Coolify + une base PostgreSQL. Pour un nouveau client, on refait les étapes 1 à 5 avec un autre sous-domaine.

## 1. Créer la base PostgreSQL

Dans Coolify : **Project → + New → Database → PostgreSQL 16**.

- Laisser Coolify générer l'utilisateur et le mot de passe.
- Ne pas rendre la base publique.
- Une fois démarrée, copier l'**URL interne** (« Postgres URL (internal) »), de la forme `postgres://utilisateur:motdepasse@nom-interne:5432/postgres`.
- Onglet **Backups** : activer une sauvegarde planifiée (par exemple chaque jour à 2 h, conserver 14 sauvegardes). Si possible, ajouter une destination S3 (Backblaze, Cloudflare R2…) pour avoir une copie hors du VPS.

## 2. Créer l'application

**Project → + New → Application → dépôt Git** (le nouveau dépôt WELTO).

- **Build Pack** : `Dockerfile` (le fichier est à la racine du dépôt).
- **Port** : `8000`.
- **Health check** : chemin `/healthz` (déjà déclaré dans le Dockerfile).
- **Domaine** : `https://caisse.maboutique.com`.

## 3. Variables d'environnement

Onglet **Environment Variables** :

| Variable | Valeur | |
|---|---|---|
| `DATABASE_URL` | l'URL interne copiée à l'étape 1 | obligatoire |
| `SECRET_KEY` | 50 caractères aléatoires : `python -c "import secrets; print(secrets.token_urlsafe(50))"` | obligatoire (40 car. min.) |
| `ALLOWED_HOSTS` | `caisse.maboutique.com` | obligatoire |
| `CSRF_TRUSTED_ORIGINS` | `https://caisse.maboutique.com` | obligatoire |
| `TIME_ZONE` | `Africa/Conakry` (Guinée) ou `Africa/Banjul` (Gambie) | recommandé |
| `WEB_CONCURRENCY` | `2` (défaut) : suffisant pour une boutique ; augmenter seulement si le VPS a de la mémoire libre | facultatif |
| `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | envoi des emails (mot de passe oublié, alerte d'inscription) : voir « Emails avec Resend » ci-dessous | recommandé |
| `SAAS_ADMIN_EMAILS` | votre email : vous êtes prévenu à chaque nouvelle inscription (plusieurs : séparés par des virgules) | recommandé |
| `SAAS_CONTACT` | ce que voient vos clients bloqués ou en fin d'abonnement, ex. `WhatsApp +224 620 00 00 00` | recommandé |

L'image fonctionne d'office en mode production : `DEBUG` désactivé, HTTPS (cookies sécurisés, HSTS), fichier `.env` ignoré.
**Si une variable obligatoire manque, l'application refuse de démarrer** et le journal du conteneur indique laquelle — c'est voulu, pour ne jamais tourner avec une configuration incomplète (par exemple sans PostgreSQL).

Ne changez jamais `SECRET_KEY` après la mise en service : toutes les sessions seraient déconnectées.

### Emails avec Resend

Les emails (lien « mot de passe oublié », alerte de nouvelle inscription) partent par le serveur SMTP de
[Resend](https://resend.com), sans aucune bibliothèque à installer.

1. Sur resend.com : **Domains → Add domain** (ex. `maboutique.com`), puis ajouter dans Cloudflare les
   enregistrements DNS indiqués par Resend (en **DNS only**) et attendre que le domaine soit « Verified ».
2. **API Keys → Create API Key** (permission *Sending access*).
3. Variables dans Coolify :

| Variable | Valeur |
|---|---|
| `EMAIL_HOST` | `smtp.resend.com` |
| `EMAIL_PORT` | `587` |
| `EMAIL_HOST_USER` | `resend` |
| `EMAIL_HOST_PASSWORD` | la clé API `re_…` |
| `EMAIL_USE_TLS` | `True` |
| `DEFAULT_FROM_EMAIL` | `WELTO <no-reply@maboutique.com>` (adresse du domaine vérifié) |

Le lien reçu est valable 1 heure et ne sert qu'une fois. Sans email sur son compte, un employé demande à son
gérant (Utilisateurs → icône clé) ; un gérant sans email passe par vous (admin → Utilisateurs → mot de passe).

## 4. Stockage persistant

Onglet **Persistent Storage → + Add** : un volume monté sur **`/data`**.
Il contient le logo, la signature, le cachet et les journaux. Les ventes, elles, sont dans PostgreSQL.

## 5. Déployer

Cliquer **Deploy**. Le premier build prend 2 à 4 minutes. Il installe Python, compile le CSS Tailwind et prépare les fichiers statiques compressés.
Les migrations de la base s'appliquent automatiquement à chaque démarrage.

Créer ensuite **votre** compte de propriétaire du SaaS (une seule fois) : dans Coolify, onglet **Terminal** du conteneur :

```
python manage.py createsuperuser
```

Ce compte n'appartient à aucun client : il ouvre directement l'admin (`https://caisse.maboutique.com/admin/`).

### Installation déjà déployée avant le SaaS : base à vider

Les migrations repartent de zéro pour la version SaaS (`0001_initial`). Une base PostgreSQL qui contient
déjà les tables de l'ancienne version doit être **vidée avant le déploiement**, sinon l'application démarre sur un
schéma qui ne correspond plus. Dans Coolify : supprimer puis recréer la base PostgreSQL (ou, dans son terminal,
`DROP SCHEMA public CASCADE; CREATE SCHEMA public;`), puis redéployer et recréer le compte propriétaire.

## Gérer les comptes clients (admin Django)

- Un client s'inscrit sur `/inscription/` (lien sous la page de connexion). Son compte reste **en attente** : il ne peut pas se connecter.
- **Comptes clients** → filtre *statut* « En attente » → cocher le compte → action **Activer / prolonger de 1, 3, 6 ou 12 mois**.
  Un compte encore actif est prolongé à partir de sa date de fin, sans perdre de jours.
- La date de fin (« Actif jusqu'au », dernier jour inclus) et le **nombre de boutiques autorisées** se modifient aussi directement dans la liste.
- 7 jours avant la fin, le gérant voit un rappel en haut de ses pages. Le lendemain de la date de fin, plus personne du compte ne peut se connecter ; les données restent intactes et reviennent dès que vous prolongez.
- **Suspendre** bloque l'accès immédiatement, sans rien supprimer.
- Un compte = un pays = une devise. Le même client dans deux pays = deux comptes.

## 6. Cloudflare

1. **DNS** : un enregistrement `A` `caisse` → IP du VPS.
   Le laisser d'abord en **DNS only** (nuage gris) le temps que Coolify obtienne le certificat Let's Encrypt (1 à 2 minutes après le déploiement), puis passer en **Proxied** (nuage orange).
2. **SSL/TLS → Overview** : mode **Full (strict)**.
3. **SSL/TLS → Edge Certificates** : activer **Always Use HTTPS**.
4. **Speed → Optimization** : laisser Brotli actif. Ne pas activer Rocket Loader : il retarde le JavaScript de la caisse.
5. **Caching** : rien à configurer. Les fichiers `/static/` ont des noms uniques et un cache d'un an : Cloudflare les sert depuis l'Afrique de l'Ouest sans repasser par le VPS.

## 7. Vérifications après la mise en ligne

1. `https://caisse.maboutique.com/healthz` affiche `ok`.
2. Créer un compte client de test sur `/inscription/`, l'activer dans l'admin, puis s'y connecter.
3. Créer 2 ou 3 produits, faire une vente test puis l'**annuler** (Ventes → la vente → Annuler) : le stock revient à sa valeur.
4. Sur la tablette : ouvrir la caisse, tester la douchette et le bouton appareil photo (le navigateur demande l'autorisation la première fois).
5. Dans la base PostgreSQL de Coolify, lancer une première sauvegarde manuelle (**Backup now**).

## Sécurité en place

- Connexion bloquée 15 minutes après 5 mots de passe faux sur un même identifiant (ou 20 depuis une même adresse), y compris sur `/admin/`. Le gérant peut réinitialiser le mot de passe d'un employé dans **Utilisateurs**.
- Une session reste ouverte 7 jours sans activité ; penser à se déconnecter d'une tablette partagée ou perdue.
- Pages d'erreur et « page expirée » en français, sans détail technique.

## Mises à jour

Un `git push` sur la branche suivie puis **Redeploy** (ou activer le déploiement automatique). Les migrations s'appliquent seules.

## Sauvegarde et restauration

- Les sauvegardes PostgreSQL sont gérées par Coolify (étape 1). Pour restaurer : onglet **Backups** de la base, choisir une sauvegarde, puis **Restore**.
- Avant une grosse mise à jour, lancer une sauvegarde manuelle (**Backup now**).

## Développement en local

```bash
cd blog_pos
cp .env.example .env            # DEBUG=True, base SQLite
python -m venv venv && venv/Scripts/activate   # Windows (Linux/Mac : source venv/bin/activate)
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Le CSS compilé (`core/static/css/app.css`) est inclus dans le dépôt. Après une modification de classes Tailwind dans les templates, recompiler avec le [binaire Tailwind autonome](https://github.com/tailwindlabs/tailwindcss/releases) :

```bash
tailwindcss -i assets/app.css -o core/static/css/app.css --minify --watch
```

Tests : `python manage.py test`.

Pour tester l'image de production avec PostgreSQL : `docker compose up --build` à la racine, puis ouvrir http://localhost:8000.

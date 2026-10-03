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
| `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | pour le mot de passe oublié | facultatif |

L'image fonctionne d'office en mode production : `DEBUG` désactivé, HTTPS (cookies sécurisés, HSTS), fichier `.env` ignoré.
**Si une variable obligatoire manque, l'application refuse de démarrer** et le journal du conteneur indique laquelle — c'est voulu, pour ne jamais tourner avec une configuration incomplète (par exemple sans PostgreSQL).

Ne changez jamais `SECRET_KEY` après la mise en service : toutes les sessions seraient déconnectées.

## 4. Stockage persistant

Onglet **Persistent Storage → + Add** : un volume monté sur **`/data`**.
Il contient le logo, la signature, le cachet et les journaux. Les ventes, elles, sont dans PostgreSQL.

## 5. Déployer

Cliquer **Deploy**. Le premier build prend 2 à 4 minutes. Il installe Python, compile le CSS Tailwind et prépare les fichiers statiques compressés.
Les migrations de la base s'appliquent automatiquement à chaque démarrage.

Ouvrir `https://caisse.maboutique.com` : la page **Bienvenue** demande le nom de la boutique, la devise et crée le compte du gérant.

## 6. Cloudflare

1. **DNS** : un enregistrement `A` `caisse` → IP du VPS.
   Le laisser d'abord en **DNS only** (nuage gris) le temps que Coolify obtienne le certificat Let's Encrypt (1 à 2 minutes après le déploiement), puis passer en **Proxied** (nuage orange).
2. **SSL/TLS → Overview** : mode **Full (strict)**.
3. **SSL/TLS → Edge Certificates** : activer **Always Use HTTPS**.
4. **Speed → Optimization** : laisser Brotli actif. Ne pas activer Rocket Loader : il retarde le JavaScript de la caisse.
5. **Caching** : rien à configurer. Les fichiers `/static/` ont des noms uniques et un cache d'un an : Cloudflare les sert depuis l'Afrique de l'Ouest sans repasser par le VPS.

## 7. Vérifications après la mise en ligne

1. `https://caisse.maboutique.com/healthz` affiche `ok`.
2. La page **Bienvenue** s'affiche : créer la boutique et le compte du gérant.
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

# GML-SHIELD

GML-SHIELD aide les équipes logistiques à gérer les missions, leurs preuves et les échanges avec les chauffeurs. Le MVP comprend une API FastAPI, un client TypeScript/Vite et une base PostgreSQL.

## Technologies et organisation

- **Serveur :** Python 3.12, FastAPI, SQLAlchemy asynchrone, PostgreSQL, Alembic.
- **Client :** TypeScript, Vite.
- **Services :** PostgreSQL et ClamAV, lancés avec Docker Compose.
- `app/` contient la configuration, les modèles, la sécurité, les dépendances et les routeurs.
- `frontend/src/` contient le client API et les vues chauffeur, répartiteur et administration.
- `migrations/` contient les versions Alembic ; `tests/` contient les tests serveur et client.

## Prérequis et configuration

Installer Docker Compose, Python 3.12 et Node.js 22+. Copier le modèle de variables puis remplacer les secrets :

```bash
cp .env.example .env
python3 -c 'import base64,secrets; print("POSTGRES_PASSWORD="+secrets.token_urlsafe(32)); print("GML_JWT_SECRET="+secrets.token_urlsafe(48)); print("GML_AES_KEY_B64="+base64.b64encode(secrets.token_bytes(32)).decode())'
```

Reporter les valeurs produites dans `.env`. Pour un déploiement, `GML_ALLOWED_ORIGIN` doit être l’origine HTTPS exacte de l’application et `GML_COOKIE_SECURE=true`. Le secret JWT doit faire au moins 32 caractères et la clé AES doit encoder 32 octets. Le fichier `.env` est ignoré par Git et ne doit jamais être publié.

## Démarrage local

Le fichier Compose local publie uniquement l’application sur `127.0.0.1:8000` et configure les cookies pour HTTP local :

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build -d
curl http://localhost:8000/health
```

Les migrations s’appliquent au démarrage du conteneur. Pour créer un chauffeur, saisir son mot de passe sans l’inscrire dans le dépôt ou dans l’historique du shell, puis lancer :

```bash
read -s GML_NEW_USER_PASSWORD
export GML_NEW_USER_PASSWORD
docker compose exec -e GML_NEW_USER_EMAIL=chauffeur@example.test -e GML_NEW_USER_ROLE=DRIVER -e GML_NEW_USER_PASSWORD app python create_user.py
unset GML_NEW_USER_PASSWORD
```

Aucun compte ni mot de passe de démonstration n’est livré avec le projet. Transmettre tout mot de passe de démonstration au correcteur par le canal privé prévu par l’établissement.

## Tests et qualité

Les tests serveur exigent une base PostgreSQL dédiée. Le Compose de test démarre une instance locale sur le port 5433, sans volume persistant :

```bash
docker compose -f docker-compose.test.yml up -d --wait
export GML_TEST_DATABASE_URL=postgresql+asyncpg://gml_test:test-only-password@localhost:5433/gml_shield_test
export DATABASE_URL="$GML_TEST_DATABASE_URL"
export GML_JWT_SECRET=test-only-jwt-secret-never-use-in-production
export GML_AES_KEY_B64=VFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFQ=
export GML_ALLOWED_ORIGIN=https://testserver
export GML_COOKIE_SECURE=true
python -m alembic upgrade head
python -m pytest
ruff check .
ruff format --check .
```

La suite refuse toute URL autre que la base locale `gml_shield_test` avec l’utilisateur `gml_test`. Elle ne doit jamais viser une base de production. Pour arrêter le service de test :

```bash
docker compose -f docker-compose.test.yml down
```

Vérifier le client :

```bash
cd frontend
npm ci
npm run typecheck
npm test
npm run build
```

Le build exécute le contrôle TypeScript avant Vite. Le lockfile versionné rend `npm ci` reproductible.

## Protections principales

- Mots de passe hachés avec Argon2id ; JWT HS256 limité à 15 minutes et contrôlé avec une session serveur révocable.
- Cookie d’accès `HttpOnly`, `SameSite=Strict`, `Secure` en production ; les mutations vérifient CSRF et l’origine autorisée.
- Les messages appartiennent au chauffeur authentifié ; la requête de lecture filtre sur son identifiant. SQLAlchemy lie les valeurs au lieu de construire du SQL par concaténation.
- Le client ajoute les données utilisateur au DOM avec `textContent` et des propriétés DOM, pas dans une chaîne `innerHTML`.
- Les documents restent dans un volume privé et sont analysés par ClamAV.

## Déploiement et démonstration

Application : [GML-SHIELD](https://fysnej9mo041xdwkmgwyovj5.solutioncloud.app/). Les contrôles sans authentification et la procédure de vérification fonctionnelle sont décrits dans [`docs/verification-deploiement.md`](docs/verification-deploiement.md). La correspondance entre la consigne B5Q3 et les preuves techniques est dans [`docs/B5Q3-preuves-conformite.md`](docs/B5Q3-preuves-conformite.md).

Le mot de passe du compte de démonstration, s’il est créé, n’est jamais conservé dans ce dépôt. Le MVP n’a pas encore fait l’objet d’un audit de sécurité indépendant.

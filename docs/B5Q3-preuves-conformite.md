# Preuves de conformité — B5Q3

| Exigence de l’examen | Implémentation | Fichiers concernés | Tests associés | Vérification manuelle |
|---|---|---|---|---|
| Dépôt serveur et client | API FastAPI et client TypeScript assemblé par Docker | `app/`, `frontend/`, `Dockerfile` | Build Docker CI | Vérifier l’URL déployée |
| Authentification du chauffeur | Route login, compte actif, erreurs génériques | `app/routers/authentication.py`, `app/security.py` | `tests/test_authentication.py` | Connexion avec un compte autorisé |
| Argon2id | Hachage et vérification via `PasswordHasher` | `app/security.py`, `create_user.py` | Connexion valide/invalide | Aucun mot de passe brut en base ou dans le dépôt |
| JWT | HS256, `sub`, `sid`, `iat`, `exp`, `iss`, `aud`, expiration à 15 min | `app/security.py`, `app/dependencies.py` | Jeton expiré, signature, audience et émetteur invalides | Vérifier le cookie d’accès dans les outils réseau |
| Session côté serveur | La session existe, correspond à l’utilisateur, n’est ni expirée ni révoquée | `app/dependencies.py`, `app/models.py` | Session absente, révoquée ou appartenant à un autre utilisateur ; déconnexion | Après déconnexion, `/api/auth/me` refuse la session |
| Cookie HttpOnly | Cookie d’accès HttpOnly, Secure en production, SameSite Strict, Path `/`, durée 900 s | `app/routers/authentication.py` | Attributs du cookie | Contrôler `Set-Cookie` dans le navigateur |
| Protection CSRF | Cookie lié à la session, en-tête correspondant, comparaison constante et contrôle d’origine | `app/dependencies.py` | Absence, mauvais jeton et origine non autorisée | Répéter une mutation sans jeton CSRF et constater le refus |
| Enregistrement d’un message | Le rôle DRIVER est exigé et le propriétaire vient de la session | `app/routers/driver_messages.py`, `app/schemas.py` | Création 201, validation, rôle et refus de `driver_id` client | Envoyer un message depuis un compte chauffeur |
| Lecture des propres messages | Filtre SQLAlchemy par utilisateur connecté, tri explicite et limite de 100 | `app/routers/driver_messages.py` | Lecture et isolation entre deux chauffeurs | Se connecter à deux comptes et vérifier l’absence de partage |
| Isolation entre chauffeurs | Aucune route n’accepte l’identifiant du propriétaire depuis le corps ou la query de lecture | `app/routers/driver_messages.py` | `test_driver_can_create_and_read_only_their_own_messages` | Vérifier les réponses de deux comptes distincts |
| Protection contre l’injection SQL | Requêtes SQLAlchemy à paramètres liés ; les chaînes d’attaque restent du texte | `app/routers/authentication.py`, `app/routers/driver_messages.py` | Tentative de login SQLi et contenus `OR 1=1` / `DROP TABLE` | Vérifier que l’API refuse le login et relit le contenu littéral |
| Protection du rendu HTML | Messages, codes et erreurs passent par `textContent`/`dataset` | `frontend/src/dom-utils.ts`, `frontend/src/driver-messages.ts` | `frontend/src/dom-utils.test.ts` | Vérifier le rendu d’une chaîne `<script>` comme texte |
| Noms explicites | Fonctions et variables décrivent les actions et données métier | `app/`, `frontend/src/` | Typecheck et lint | Revue du diff |
| Organisation du code | Configuration, base, modèles, sécurité et routeurs séparés | `app/config.py`, `app/database.py`, `app/models.py`, `app/security.py`, `app/routers/` | Tests importent les modules séparés | Revue des fichiers concernés |
| Migrations | Alembic conserve les migrations publiées et démarre sur `0002_driver_messages` | `migrations/` | `alembic upgrade head` dans CI | Contrôler la révision après migration |
| Tests reproductibles | PostgreSQL de test dédié et client DOM léger | `tests/`, `frontend/src/dom-utils.test.ts`, `docker-compose.test.yml` | Pytest et Vitest | Commandes du README |
| Construction du projet | Lockfile npm, `npm ci`, typecheck et build client | `frontend/package-lock.json`, `Dockerfile` | CI | `docker build .` |
| Intégration continue | PostgreSQL, migration, lint, formatage, tests et build | `.github/workflows/quality.yml` | Exécutions GitHub Actions de la PR | Vérifier le statut de la PR |
| Déploiement accessible | URL HTTPS publique documentée | `README.md` | Contrôles anonymes avant fusion | `/health`, redirection HTTPS et routes protégées |

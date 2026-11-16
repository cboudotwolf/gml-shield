# GML-SHIELD

Application de gestion de missions pour chauffeurs et répartiteurs. API FastAPI, PostgreSQL et interface web TypeScript.

## Fonctionnalités du MVP

- Connexion Argon2id, session JWT de 15 minutes en cookie HttpOnly et protection CSRF.
- Accès aux missions limité par rôle et affectation. Codes d’entrepôt chiffrés avec AES-256-GCM.
- Statuts, notifications WebSocket, preuves privées JPEG/PNG/PDF et journal d’audit.
- PostgreSQL, migrations Alembic, ClamAV et Docker Compose.

## Démarrage local

Copier `.env.example` en `.env`, remplacer les secrets, puis lancer :

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build -d
```

L’interface est sur `http://localhost:8000`. Créer les comptes avec `create_user.py` ; aucun mot de passe par défaut n’est fourni. En production, utiliser HTTPS, des secrets séparés et un compte créé après le déploiement.

Les preuves sont conservées dans un volume privé. Le code entrepôt est masqué dans l’interface jusqu’au clic du chauffeur, mais l’API le lui retourne selon le contrat d’accès retenu. MVP pédagogique, non audité pour des données réelles.

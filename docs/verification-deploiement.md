# Vérification du déploiement

Définissez l’URL de l’instance à vérifier dans `GML_APP_URL` avant d’exécuter les commandes ci-dessous.

Ne placez aucun mot de passe, cookie ou jeton dans ce document. Aucun compte de démonstration n’est créé automatiquement. Créez-le uniquement avec un accès autorisé, puis transmettez son mot de passe par le canal privé de l’établissement.

## Contrôles sans authentification

```bash
export GML_APP_URL="https://votre-domaine.example"
curl -i "${GML_APP_URL%/}/health"
curl -I "${GML_APP_URL%/}/"
curl -i "${GML_APP_URL%/}/api/auth/me"
curl -i "${GML_APP_URL%/}/api/messages"
```

Résultats attendus : `/health` renvoie HTTP 200, HTTP redirige vers HTTPS, et les routes protégées refusent un appel non authentifié.

## Parcours authentifié après déploiement

Avec un compte chauffeur autorisé, dans un profil de navigateur de démonstration :

1. Se connecter depuis l’interface et contrôler dans l’onglet Réseau la réponse de login ; ne pas copier ni partager la valeur du cookie.
2. Vérifier que le cookie `gml_access` est marqué `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/` et `Max-Age=900`.
3. Enregistrer un message puis vérifier qu’il apparaît dans la liste après rechargement.
4. Réaliser le même parcours avec un second chauffeur dans un profil distinct ; chacun ne doit voir que ses propres messages.
5. Se déconnecter. L’accès à `/api/auth/me` doit être refusé. La révocation de l’ancien jeton est également vérifiée par les tests automatisés.
6. Ne pas effectuer de test d’injection destructif sur la production ; ces essais appartiennent uniquement à la base PostgreSQL de test isolée.

Si aucun identifiant autorisé n’est disponible, ne pas réaliser ni déclarer les vérifications authentifiées. Le correcteur peut recevoir le mot de passe séparément par le canal privé prévu par l’établissement.

## État de vérification

Les contrôles de cette procédure doivent être exécutés après fusion et redéploiement. Les résultats observés doivent être ajoutés au compte rendu de soutenance ; ce fichier décrit la procédure et ne constitue pas, à lui seul, une preuve d’exécution.

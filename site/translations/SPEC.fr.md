<!--
Traduction française informative de SPEC.md (site/README.md, CONTRIBUTING.md).
Seul le texte anglais fait foi. Pour la mettre à jour : traduire ce qui a
changé dans SPEC.md depuis `commit`, puis donner ici le nouveau commit et la
somme SHA-256 de SPEC.md à ce commit (sha256sum SPEC.md).
language: fr
commit: ca10e3146a6300cc99814e2290de5da97c735965
sha256: ea82945a9f07fa5e75114a2062e5edfcba5c7432e0d42c5640e899a11e61898c
banner: Traduction informative ; seul le texte anglais fait foi.
english: Lire le texte anglais, qui fait référence
source: SPEC.fr.md sur GitHub
-->
# Lantern — un protocole ouvert pour les serveurs de bibliothèques de jeux

Brouillon 0.5, 2026-10-30. Statut : **brouillon**, susceptible de changer jusqu'à la 1.0.
Ce texte est publié sous licence [CC BY 4.0](LICENSES/CC-BY-4.0.txt).

**Traduction informative.** Ce texte traduit en français le brouillon 0.5
de la spécification. Seul le texte anglais fait foi : en cas de doute ou
d'écart, c'est lui qui s'applique. Les identifiants d'exigence
(`[L-5.2-3]`), le code, les noms de champs, les documents JSON et les mots
clés ci-dessous sont laissés tels qu'en anglais.

Lantern permet à un client (un homebrew sur une console, ou une application
sur un téléphone, un ordinateur ou dans un navigateur) de parcourir un
serveur de bibliothèque que l'utilisateur fait tourner pour ses propres
jeux, d'y télécharger jeux et homebrews avec contrôle d'intégrité, de lire
ce que le serveur sait de chaque jeu, et d'y conserver des sauvegardes et
des codes de triche. C'est un petit contrat REST/JSON, versionné pour qu'un
client et un serveur d'âges différents continuent de fonctionner ensemble.
Ses routes de lecture fonctionnent aussi sous forme de simples fichiers
(§ 21), chez un hébergeur web ou sur une clé USB. C'est un protocole à part
entière : il ne doit rien aux protocoles utilisés avant lui et ne garde rien
pour eux.

Son cœur ne connaît aucune plateforme : le listage, les téléchargements,
l'appairage et les erreurs fonctionnent de la même façon pour une Nintendo
Switch, un téléphone ou un ordinateur. Ce qui change d'une plateforme à
l'autre (la forme de l'identifiant d'un jeu, ses formats de paquet,
l'emplacement des codes de triche, des sauvegardes et des homebrews) figure
dans le profil de cette plateforme, à l'annexe A.

Les mots clés MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT et MAY
s'entendent au sens de la RFC 2119 et de la RFC 8174 (BCP 14), uniquement
lorsqu'ils sont écrits en capitales. Cette traduction les laisse en
anglais, pour qu'une exigence se lise de la même façon dans les deux
langues : MUST (et REQUIRED) marque une obligation absolue, MUST NOT une
interdiction absolue ; SHOULD une recommandation, dont on ne s'écarte qu'en
connaissance de cause et pour une raison valable, SHOULD NOT l'inverse ; MAY
une possibilité laissée au choix de l'implémentation. Chaque exigence porte
un identifiant stable, écrit à côté d'elle entre crochets, comme
`[L-5.2-3]` : le § 3.5 dit comment les identifiants sont tenus, et la suite
de conformité (§ 17) nomme ceux que couvre chacun de ses contrôles.
L'annexe B donne des conseils aux auteurs de clients, sans exigences.

## 1. Principes

1. **Petit et figé.** Peu de routes, des formes fixes, aucun langage de
   requête. Un serveur s'écrit en un week-end ; un client en quelques
   centaines de lignes de C++.
2. **Versionné deux fois.** Une version majeure du protocole dans le chemin
   (`/v1/`) pour les ruptures ; un entier `schema` dans chaque document pour
   le reste (§ 3).
3. **Déclaré, jamais deviné.** Le serveur dit ce qu'il propose (`features`)
   et pour quelles plateformes ; le client dit qui il est (`User-Agent`) et
   sur quelle plateforme il tourne (`Lantern-Platform`). Aucune déduction à
   partir des en-têtes.
4. **Un cœur neutre, un profil par plateforme.** Chaque app indique sa
   `platform` ; ses identifiants, versions et formats suivent le profil de
   cette plateforme (annexe A). Rien d'autre dans le cœur ne dépend d'une
   plateforme.
5. **Une identité structurée, un contenu vérifié.** Chaque paquet a son
   identifiant de titre, son identifiant d'app, son type, sa version
   entière, sa taille, son format et son SHA-256, et chaque téléchargement
   est vérifié par rapport à eux. Les noms de fichiers ne portent aucun sens.
6. **Sûr par défaut.** HTTPS partout, une clé épinglée à l'appairage sur le
   réseau local, un jeton révocable par appareil, lié à une clé que
   l'appareil a créée. Aucun mot de passe ne transite jamais par l'appareil.
   Un homebrew n'écrit que là où son manifeste le dit et où l'utilisateur
   l'autorise.
7. **HTTP tel qu'il est.** De vrais codes d'état, des erreurs
   `application/problem+json`, les plages, `ETag`, `Repr-Digest`,
   `Content-Digest`, les signatures de messages HTTP.
8. **Rien de caché, rien d'intrusif.** Aucun identifiant matériel, aucun
   chiffrement propriétaire, aucune modification des réglages du client
   décidée par le serveur.

## 2. Transport

- HTTPS. Un client MUST vérifier le certificat auprès de son magasin
  d'autorités de certification, ou par rapport à la clé qu'il a épinglée à
  l'appairage (§ 5.3). [L-2-1]
- HTTP en clair n'est permis que sur les adresses de bouclage
  (`127.0.0.0/8`, `::1`), pour les tests. Un client MUST NOT parler HTTP en
  clair à une autre adresse, sauf pour récupérer un fichier par son SHA-256
  auprès d'un miroir ou d'un pair sur un réseau privé, comme le permet le
  § 19. [L-2-2] Un serveur MUST NOT servir Lantern en HTTP en clair sur une
  telle adresse. [L-2-3]
- Toutes les routes vivent sous un chemin de base que le serveur choisit
  (par défaut `/api/lantern`), annoncé par la découverte (§ 4.1) et la
  poignée de main (§ 4.2). Plus bas, les chemins sont relatifs à `<base>`.
- Les corps JSON MUST être en UTF-8, envoyés avec
  `Content-Type: application/json` (erreurs : `application/problem+json`,
  § 12). [L-2-4]
- Le client MUST envoyer `User-Agent: <Name>/<version>`. [L-2-5] Il SHOULD
  envoyer `Accept-Language` (§ 2.2). [L-2-6] Il SHOULD envoyer
  `Lantern-Platform` (§ 4.3). [L-2-7]
- Un client MUST n'envoyer son jeton (§ 5) et ses signatures qu'à l'origine
  du serveur (schéma, hôte, port), jamais à un autre hôte vers lequel pointe
  un document. [L-2-8]

### 2.1 Compression et versions de HTTP

- Un serveur SHOULD proposer un `Content-Encoding` sur ses réponses JSON,
  selon ce que demande l'`Accept-Encoding` du client : `zstd` (RFC 8878) ou
  `br` (RFC 7932), et `gzip`. [L-2.1-1] Un client MAY les demander ; celui
  qui ne les demande pas reçoit le JSON tel quel.
- Un serveur MUST NOT appliquer de `Content-Encoding` à une réponse de
  fichier (§ 6.6), quoi que dise `Accept-Encoding` : les paquets sont déjà
  compressés par leurs propres formats, et les plages comme `Repr-Digest`
  portent sur les octets tels qu'ils sont stockés. [L-2.1-2]
- Une réponse qu'un serveur compresse MUST porter `Vary: Accept-Encoding`,
  et un `ETag` différent de celui de la version non compressée (RFC 9110
  § 8.8.3). [L-2.1-3]
- Un client envoie ses corps de requête sans `Content-Encoding`. Les limites
  du § 13 s'appliquent à un document une fois décompressé.
- Lantern fonctionne de la même façon en HTTP/1.1 et en HTTP/2 (RFC 9113) ;
  rien n'y dépend de la version. Un serveur MAY proposer HTTP/2 par ALPN et
  un client MAY l'utiliser : une seule connexion porte alors à la fois une
  page, ses titres et leurs images, et la compression des en-têtes rend peu
  coûteux ceux que répète chaque requête (`Authorization`,
  `Signature-Input`, `Lantern-Platform`). Une signature couvre
  `@target-uri` (§ 5.4), que les pseudo-en-têtes de HTTP/2 donnent comme le
  fait la ligne de requête de HTTP/1.1.

### 2.2 Langues

L'`Accept-Language` du client (RFC 9110 § 12.5.4) choisit la langue des
textes qu'un serveur écrit pour des personnes : le `summary`, la
`description` et les `hint` d'un titre et d'un homebrew (§ 7.1, § 8), le
`title` et le `detail` d'une erreur (§ 12), et le `motd` de la poignée de
main (§ 4.2).

- Un serveur SHOULD répondre dans la meilleure langue dont il dispose pour
  `Accept-Language`, et en anglais quand il n'en a aucune. [L-2.2-1]
- Un document qui contient de tels textes MUST indiquer leur langue dans son
  `language` (celui d'un titre, d'un homebrew, d'un problème, de la poignée
  de main). [L-2.2-2] Sa réponse SHOULD aussi porter `Content-Language`.
  [L-2.2-3]
- Les codes, les noms de champs et les valeurs énumérées (`code`, `kind`,
  `genres`, `state`) ne changent jamais avec la langue.

## 3. Versions

### 3.1 Version du protocole

La version majeure figure dans le chemin : `<base>/v1/…`. Elle ne change que
pour une rupture que `schema` ne peut pas exprimer. Un serveur liste les
versions qu'il sert (`versions` au § 4.2) et SHOULD conserver une ancienne
version majeure tant que des clients l'appellent. [L-3.1-1]

### 3.2 Schéma des documents

Tout document JSON qu'un serveur renvoie, et tout document qu'un client
envoie, MUST avoir un entier `schema` à sa racine. [L-3.2-1]

- Ajouter un champ conserve `schema`. Un champ qui change de sens, d'unité
  ou de type, ou qui disparaît, le fait monter.
- Un lecteur MUST ignorer les champs qu'il ne connaît pas. [L-3.2-2]
- Un lecteur qui reçoit un `schema` plus élevé que ceux qu'il connaît MUST
  traiter le document comme absent (la fonctionnalité est indisponible), et
  non comme une erreur. [L-3.2-3] Il MUST NOT le réécrire. [L-3.2-4]
- Chaque document a un JSON Schema dans `schemas/v1/` (2020-12), avec un
  exemple dans `examples/v1/`. Les schémas décrivent le schema 1 et
  acceptent les champs qu'ils ne listent pas, comme doit le faire un
  lecteur. Les documents d'un serveur MUST être valides selon eux.
  [L-3.2-5]
- Un serveur MUST répondre à un document de requête d'un `schema` qu'il ne
  sait pas lire par `422` `unsupported_schema` (§ 12). [L-3.2-6]
- `features` (§ 4.2) donne, par famille, le `schema` qu'écrit le serveur ;
  un client MAY envoyer `Accept-Schema: <family>=<n>, …` pour en demander un
  plus ancien, ce qu'un serveur SHOULD honorer tant qu'il sait encore
  l'écrire. [L-3.2-7]

### 3.3 Extensions

Les champs et routes propres à un éditeur commencent par `x-<vendor>-`
(champ) ou vivent sous `<base>/x/<vendor>/` (routes). Les clients les
ignorent, sauf s'ils les connaissent.

### 3.4 Dépréciation et fin de service

Une route, un paramètre de requête ou un ancien `schema` d'une famille
appelé à disparaître est annoncé sur les réponses qui l'utilisent, par deux
en-têtes :

```http
Deprecation: @1793318400
Sunset: Sun, 01 Aug 2027 00:00:00 GMT
Link: <https://lantern.boreale.dev/spec/#34-deprecation-and-sunset>; rel="deprecation"
```

- `Deprecation` (RFC 9745) : depuis quand l'élément est déprécié, une date
  au format Structured Fields (`@` suivi de secondes Unix). Un serveur MUST
  l'envoyer sur chaque réponse d'une route, ou dans un schéma, qu'il a
  dépréciés. [L-3.4-1]
- `Sunset` (RFC 8594) : la date HTTP après laquelle il peut cesser de
  répondre. Un serveur SHOULD l'envoyer dès qu'il connaît cette date.
  [L-3.4-2] Il MUST NOT arrêter une route ou un schéma dépréciés avant leur
  `Sunset`. [L-3.4-3]
- Un ancien schéma reste servi tant que des clients le lisent : un serveur
  MUST continuer de l'écrire pour les clients qui le demandent par
  `Accept-Schema` (§ 3.2) au moins jusqu'à son `Sunset`. [L-3.4-4]
- Un `Link` avec `rel="deprecation"` MAY pointer vers une page qui dit ce
  qui le remplace.
- Un client SHOULD consigner un `Deprecation` qu'il reçoit là où ses
  développeurs le verront (un journal, un rapport), et passer à ce qui le
  remplace avant le `Sunset`. [L-3.4-5]

### 3.5 Évolutions et propositions

Comment le texte évolue :

1. Une évolution commence par un ticket ouvert avec le modèle **Proposal**
   du dépôt : le problème, avec un cas réel ; l'évolution (routes, champs,
   codes, sections touchées) ; son effet sur `schema` ; comment la suite de
   conformité la vérifie ; et ce que fait un client ou un serveur qui
   l'ignore.
2. Une fois qu'elle est acceptée, une seule pull request modifie ensemble
   SPEC.md, les schémas et leurs exemples, `openapi.yaml`, les vecteurs de
   test (§ 17), la suite et le serveur de référence, pour que la suite ne
   soit jamais en retard sur le texte. La version et la date du texte
   montent, et sa section « Modifications » dit ce qui a changé.
3. Son effet sur les versions :
   - un ajout (un champ, une route, un code, une valeur d'une liste qu'un
     lecteur est invité à tolérer, comme un `kind` ou un genre) conserve
     `schema` et `/v1/` ;
   - un champ qui change de sens, d'unité ou de type, ou qui disparaît, fait
     monter le `schema` du document : le serveur écrit le nouveau, et
     l'ancien, marqué comme déprécié (§ 3.4), pour les clients qui le
     demandent ;
   - une rupture que `schema` ne peut pas exprimer (le sens d'une route,
     l'authentification) est une nouvelle version majeure, `/v2/`, servie à
     côté de `/v1/` (§ 3.1).
4. Identifiants d'exigence : `L-<section>-<n>`, attribués une seule fois.
   Une exigence garde son identifiant quand sa formulation ou sa place
   changent ; une nouvelle prend le prochain numéro libre de sa section ;
   l'identifiant d'une exigence supprimée n'est jamais réattribué.

Jusqu'à la 1.0, les brouillons gardent `/v1/` et le `schema` 1 : un
brouillon peut encore changer une forme qu'un autre brouillon a écrite, et
sa section « Modifications » le dit.

## 4. Découverte, poignée de main et plateformes

### 4.1 Sur le réseau local

Lantern a sa propre découverte, sur le port UDP **47115** :

- Le client envoie le datagramme `{"schema":1,"lantern":"discover"}` au port
  47115 en diffusion dirigée (l'adresse de diffusion du sous-réseau, comme
  `192.168.1.255` : certaines consoles ignorent `255.255.255.255`).
- Un serveur répond en unicast, à la source du datagramme, avec :

  ```json
  {"schema": 1, "lantern": "server", "uid": "6f1c2a8e-…",
   "name": "Living room shelf", "port": 443, "base": "/api/lantern",
   "versions": [1]}
  ```

- L'adresse du serveur est l'adresse source de la réponse ; `port` est son
  port HTTPS, `base` et `versions` comme dans la poignée de main (§ 4.2).
  La réponse d'un serveur MUST donner les `uid`, `base` et `versions` de sa
  poignée de main, et le port sur lequel il répond en HTTPS. [L-4.1-1]
- Chaque datagramme est du JSON UTF-8 d'au plus 1200 octets. Un serveur ne
  répond qu'à une requête qu'il sait lire (§ 3.2) et se tait sinon. Il
  SHOULD ne répondre qu'aux adresses de ses propres réseaux. [L-4.1-2] Il
  SHOULD ne répondre que quelques fois par seconde à une même adresse.
  [L-4.1-3]
- Un serveur SHOULD aussi s'annoncer par DNS-SD (RFC 6763) sur DNS
  multicast (RFC 6762) sous `_lantern._tcp`, avec les clés TXT `uid=<uid>`,
  `path=<base>` et `v=1` (les versions, séparées par des virgules).
  [L-4.1-4] Le serveur de référence le fait, avec la seule bibliothèque
  standard ; un client qui ne sait pas lire le DNS multicast utilise le
  datagramme.
- Un datagramme avec `"peers": true` interroge aussi les consoles qui
  partagent des fichiers (§ 19.5) ; un serveur y répond comme à tout autre.
- La découverte n'est qu'une indication : elle trouve une adresse et un nom,
  rien de plus. Une réponse ne prouve rien, et un client MUST n'accorder sa
  confiance à un serveur qu'au travers de TLS et de l'appairage (§ 5).
  [L-4.1-5]

### 4.2 Poignée de main

`GET /.well-known/lantern` (à la racine de l'origine) et `GET <base>/v1/`
MUST renvoyer le même document, avec ou sans jeton. [L-4.2-1]

```json
{"schema": 1,
 "uid": "6f1c2a8e-…",
 "name": "Living room shelf",
 "software": {"name": "ExampleShelf", "version": "2.7.0"},
 "base": "/api/lantern",
 "versions": [1],
 "platforms": ["switch", "android"],
 "motd": "New this week: two co-op games.", "language": "en",
 "account": {"name": "lea", "state": "active", "scopes": ["library", "saves"],
             "bound": true, "rating_cap": {"age": 12}},
 "features": {"library": 1, "titles": 1, "changes": 1, "sections": 1,
              "homebrew": 1, "saves": 1, "cheats": 1, "requests": 0,
              "pairing": 1, "signatures": 1, "admin": 0, "events": 1,
              "peers": 1, "sync": 0, "encrypted_saves": 1},
 "auth": {"bearer_only": true, "skew": 300},
 "peers": {"key": "<base64 of 32 bytes>", "grant_lifetime": 600},
 "limits": {"page_size": 500, "save_body": 8388608,
            "save_size": 1073741824, "saves_kept_per_title": 10,
            "heartbeat": 15, "event_streams": 2, "wait": 60}}
```

- `uid` : un UUID qui ne change jamais pour ce serveur. Un client s'en sert
  pour reconnaître le même serveur sur le réseau local et sur internet, et
  pour retrouver la clé qu'il a épinglée (§ 5.3).
- `platforms` : les plateformes pour lesquelles le serveur a quelque chose
  (§ 4.3). Il MUST lister toutes les plateformes des apps, homebrews ou lots
  de codes de triche qu'il sert, et être le même pour chaque appelant.
  [L-4.2-2]
- `motd`, facultatif : un message pour les personnes, dans la langue
  `language` (§ 2.2).
- `account.state` : `anonymous` (pas de jeton), `active`, ou `frozen` (le
  compte existe mais ne peut rien faire ; `motd` dit pourquoi). Sans jeton,
  la poignée de main MUST répondre `200` avec `account.state` `anonymous`.
  [L-4.2-3]
- `account.scopes` : ce que cet appelant peut faire : `library`, `saves`,
  `cheats`, `cheats.write`, `requests`, `admin`, `sync.read`, `sync.write`.
  `library` couvre toutes les lectures du catalogue : apps, titres et
  homebrews.
- `account.bound` : si le jeton de l'appelant est lié à une clé d'appareil
  (§ 5.4) ; `account.rating_cap` : le plafond de classification que porte
  son jeton, s'il y en a un (§ 5.6).
- `features.<family>` : le `schema` qu'écrit le serveur pour cette famille,
  ou `0` quand il ne la propose pas **à cet appelant**. [L-4.2-4] `pairing`
  et `signatures` MUST être les mêmes pour chaque appelant, anonyme
  compris : quiconque peut joindre le serveur peut demander un appairage.
  [L-4.2-5]
- `auth` (§ 5.4) : `bearer_only`, si le serveur émet et accepte encore des
  jetons qu'aucune clé ne lie ; `skew`, de combien de secondes le `created`
  d'une signature peut différer de l'horloge du serveur.
- `limits` : `page_size`, le nombre maximal d'éléments sur une page
  (§ 6.2) ; avec `saves`, `save_body`, la plus grande sauvegarde qu'accepte
  une seule requête (§ 9.2), `save_size`, la plus grande sauvegarde tout
  court (§ 9.3), et `saves_kept_per_title`, le nombre de sauvegardes que le
  serveur garde par titre, plateforme et compte avant de supprimer la plus
  ancienne (§ 9.1) ; avec `events`, `heartbeat`, `event_streams` et `wait`
  (§ 18.4) ; avec `sync`, `sync_items` (§ 20.5).
- `peers`, avec la famille `peers` : la clé publique des autorisations
  (grants) du serveur et leur durée de vie (§ 19.3). `static`, dans la
  poignée de main d'une bibliothèque statique uniquement (§ 21.2).
- Un appel sans jeton à un serveur privé renvoie le document avec
  `account.state` `anonymous` et toutes les fonctionnalités à 0 sauf
  `pairing` et `signatures`, pour qu'un client puisse afficher le nom du
  serveur et s'appairer. La poignée de main d'un compte gelé a toutes les
  fonctionnalités à 0 sauf ces deux-là. Un jeton erroné MUST donner `401`
  ici comme ailleurs (§ 5.1) : seule son absence donne ce document.
  [L-4.2-6]
- Une route d'une famille à 0 MUST répondre `404` (le serveur ne la propose
  pas) ou `401`/`403` (pas à cet appelant), jamais `2xx`. [L-4.2-7] Une
  route d'une famille au-dessus de 0 MUST répondre comme le dit ce texte.
  [L-4.2-8]

### 4.3 Plateformes

Une plateforme est un nom en minuscules : 1 à 32 lettres, chiffres et `-`,
commençant par une lettre ou un chiffre. Les noms sont ceux
d'[Atlas](https://github.com/JigSawFr/Atlas) lorsqu'Atlas en a un
(`switch`, `steam`, `gog`, `xbox`) ; pour les autres, ce texte ajoute `3ds`
(la New Nintendo 3DS et la famille 3DS), `vita` (PlayStation Vita), `ps4`,
`android`, `ios` (iOS, iPadOS et tvOS), `windows`, `macos`, `linux` (tout
système Linux, ordinateur ou console portable, quelle que soit sa
distribution : il n'y a pas de nom par distribution) et `web` (une
application exécutée dans un navigateur). Une version ultérieure ajoute des
noms à cette liste ; ceux propres à un éditeur commencent par `x-<vendor>-`.

- Chaque app (§ 6.1), titre (§ 7), homebrew (§ 8), sauvegarde (§ 9) et lot
  de codes de triche (§ 10) porte sa `platform`.
- Un client indique sa propre plateforme par l'en-tête
  `Lantern-Platform: <name>` à chaque appel.
- Avec cet en-tête, un serveur MUST répondre pour cette plateforme
  seulement : le listage des apps, ce qui manque (§ 6.3), les changements
  (§ 6.4), les sections, les titres, les homebrews, les sauvegardes et les
  codes de triche ne listent et ne lisent que ce qui relève de cette
  plateforme ; tout le reste est `404`. [L-4.3-1] Une plateforme que le
  serveur ne sert pas MUST donner des listes vides, pas une erreur.
  [L-4.3-2] Un nom qui n'est pas un nom de plateforme MUST donner `400`.
  [L-4.3-3]
- Sans l'en-tête, un serveur répond pour toutes les plateformes, sauf là où
  une route en exige une : `POST <base>/v1/apps/missing` (§ 6.3),
  `POST <base>/v1/homebrew/updates` (§ 8.5) et les routes qui écrivent une
  sauvegarde (§ 9) MUST donner `400` sans plateforme. [L-4.3-4] Une route
  qui nomme un `title_id` ou un `id` de homebrew connu sur plusieurs
  plateformes donne aussi `400`, jusqu'à ce que le client nomme la
  plateforme.
- `?platform=<name>` sur un listage (ou sur une route qui exige une
  plateforme) MUST l'emporter sur l'en-tête. [L-4.3-5]
- Les réponses qui dépendent de la plateforme SHOULD porter
  `Vary: Lantern-Platform` (§ 14). [L-4.3-6]
- Le profil d'une plateforme (annexe A) dit ce que le cœur laisse ouvert.
  Sur une plateforme qui n'a pas encore de profil (annexe A.7), un serveur
  MAY servir des apps et des homebrews selon les seules règles du cœur ; un
  client MUST NOT installer quoi que ce soit d'une plateforme pour laquelle
  il n'a pas de profil. [L-4.3-7] Il en va de même pour ce qu'un profil
  laisse de côté : celui de Linux n'a pas encore d'apps (annexe A.6), donc
  un client n'en installe aucune.

## 5. Authentification et accès

### 5.1 Jetons

- Chaque appel authentifié envoie `Authorization: Bearer <token>` (RFC 6750),
  signé quand le jeton est lié à une clé (§ 5.4). Il n'existe pas d'autre
  schéma : un serveur MUST refuser un mot de passe et l'authentification
  HTTP Basic, sur toute route, et ne jamais les demander. [L-5.1-1]
- Un jeton est opaque pour le client et a au moins 128 bits d'entropie.
  [L-5.1-2] Le serveur MUST n'en conserver qu'une empreinte (hash).
  [L-5.1-3] Il en délivre un par appareil, avec les portées (scopes) que
  l'utilisateur a approuvées (§ 5.2), et MUST permettre à l'utilisateur de
  les lister et de les révoquer. [L-5.1-4] Un jeton MAY expirer.
- Un jeton manquant là où il en faut un, ou un jeton inconnu, révoqué ou
  expiré, MUST donner `401` avec `WWW-Authenticate: Bearer` (et
  `error="invalid_token"` quand un jeton a été envoyé). De même pour un
  `Authorization` d'un autre schéma. [L-5.1-5] Un jeton valide sans la
  portée requise MUST donner `403` `forbidden` ; celui d'un compte gelé,
  `403` `account_frozen`. [L-5.1-6]
- Un jeton ne détient jamais une portée que son compte ne détient pas :
  quand les portées d'un compte sont réduites, celles de ses jetons le sont
  aussi.
- Un serveur public répond aux appels sans jeton, au titre du compte
  `anonymous` (§ 4.2), pour les portées qu'il accorde à tous.

### 5.2 Appairage (fonctionnalité `pairing`)

La façon dont un appareil obtient son jeton, sur le modèle du flux
d'autorisation des appareils d'OAuth (RFC 8628), sans les autres parties
d'OAuth. Un serveur privé MUST le proposer. [L-5.2-1] Un serveur public
MAY le proposer, pour ce qu'il accorde au-delà des appels anonymes.

1. `POST <base>/v1/pairing` `{"schema":1, "device":"Lea's Switch",
   "scopes":["library","saves"], "key":{"alg":"ed25519",
   "public_key":"<base64>"}}`, sans jeton → `200` `{"schema":1,
   "code":"KQ4M-7TXD", "verify":"https://shelf.example.org/pair",
   "verify_complete":"https://shelf.example.org/pair?code=KQ4M-7TXD",
   "poll":"<base>/v1/pairing/p_…", "interval":5, "expires":600}`. `key`
   est la clé publique de l'appareil (§ 5.4) ; `invitation`, le code d'une
   invitation (§ 5.5).
2. L'appareil affiche le code, l'adresse `verify` et l'empreinte courte de
   la clé du serveur (§ 5.3). L'utilisateur ouvre `verify` sur un autre
   appareil, s'y connecte par les moyens propres du serveur, saisit le code,
   compare l'empreinte, puis approuve l'appareil et ses portées.
   L'approbation se fait uniquement du côté du serveur : sur sa page web, ou
   depuis l'appareil d'un administrateur par le § 5.7. Elle MUST NOT se
   faire depuis l'appareil qui s'appaire : aucun mot de passe n'y transite.
   [L-5.2-2]
3. L'appareil interroge `GET poll` toutes les `interval` secondes. Le
   serveur MUST répondre `202` pendant l'attente, puis `200` `{"schema":1,
   "token":"et_…", "scopes":[…], "bound":true}` une seule fois, et `410`
   en cas de refus, d'expiration, de jeton déjà récupéré ou d'appairage
   inconnu. [L-5.2-3] Les portées MUST être celles approuvées, au plus
   celles demandées et celles du compte. [L-5.2-4] `expires`, quand il est
   présent, est la durée de vie du jeton en secondes ; `rating_cap`, le
   plafond que porte le jeton (§ 5.6). Un appairage qui a envoyé une `key`
   interroge avec des requêtes signées (§ 5.4).
4. Les appels suivants envoient `Authorization: Bearer et_…` (§ 5.1),
   signés (§ 5.4).

- Le code MUST utiliser l'alphabet `23456789ABCDEFGHJKLMNPQRSTUVWXYZ` (sans
  `0`, `O`, `1` ni `I`), avoir 8 à 32 symboles (au moins 40 bits), et être
  affiché par groupes de 4 reliés par `-`. [L-5.2-5] Le serveur ignore la
  casse, les espaces et les tirets quand l'utilisateur le saisit.
- Un code MUST expirer en 10 minutes au plus (`expires`, en secondes, au
  plus 600). [L-5.2-6] L'adresse d'interrogation MUST être impossible à
  deviner (au moins 128 bits) et ne donner le jeton qu'une fois. [L-5.2-7]
- Le serveur MUST limiter les demandes d'appairage par adresse et les
  tentatives sur un code : au-delà, il répond `429` `slow_down` avec
  `Retry-After`. [L-5.2-8] Il SHOULD répondre `429` `slow_down` aux
  interrogations plus fréquentes que `interval`. [L-5.2-9]

**Avec un QR code.** `verify_complete` est `verify` avec le code dans sa
requête (le `verification_uri_complete` de la RFC 8628), pour que
l'utilisateur n'ait pas à le saisir :

- Un serveur MUST donner `verify_complete`, sur son origine, avec le code.
  [L-5.2-10] L'ouvrir MUST NOT approuver quoi que ce soit à lui seul :
  l'utilisateur se connecte toujours, voit l'appareil, ses portées et
  l'empreinte, et approuve. [L-5.2-11]
- Un client SHOULD afficher `verify_complete` sous forme de QR code, qu'il
  dessine lui-même : le serveur ne sert aucune image. [L-5.2-12] Il MUST
  garder le code et l'empreinte courte du serveur affichés à côté du QR
  code. [L-5.2-13] L'utilisateur le scanne avec un téléphone, compare
  l'empreinte qu'affiche la page avec celle de la console, et approuve là.

### 5.3 Épinglage, à l'appairage

Un serveur dont le certificat est accepté par le magasin d'autorités du
client n'a besoin de rien de plus. Sinon (un serveur du réseau local avec
un certificat auto-signé) :

- L'empreinte est le SHA-256 de la clé publique du serveur, son
  `SubjectPublicKeyInfo` (SPKI) en DER. Sa forme courte, pour les
  personnes, est formée de ses 16 premiers chiffres hexadécimaux, en
  majuscules, par groupes de 4 : `3F9A 1C07 B2E4 55D0`. Vecteurs de test :
  `vectors/spki.json`.
- Pendant l'appairage, l'appareil MUST afficher la forme courte de la clé
  qu'il voit, à côté du code. [L-5.3-1] La page d'approbation du serveur
  MUST afficher la forme courte de la sienne. [L-5.3-2] L'utilisateur
  n'approuve que si elles concordent.
- Une fois appairé, le client MUST épingler le SHA-256 complet pour l'`uid`
  de ce serveur. [L-5.3-3] Il n'interroge et n'appelle que sur des
  connexions qui présentent cette clé : une clé qui a changé MUST échouer,
  quel que soit le certificat qui la porte, jusqu'à ce que l'utilisateur
  s'appaire de nouveau. [L-5.3-4]
- Avant l'appairage, un client peut lire la poignée de main et demander un
  code au travers d'un certificat qu'il n'a pas vérifié : il n'envoie alors
  rien de secret.
- Le lien d'une invitation (§ 5.5) porte l'empreinte complète : un client
  qui l'ouvre épingle celle-ci, sans demander à l'utilisateur de comparer.

### 5.4 Clés d'appareil et requêtes signées (fonctionnalité `signatures`)

Un jeton lié à une clé créée par l'appareil ne vaut rien sans cette clé :
copié depuis l'appareil, un journal ou une sauvegarde, il ne fonctionne pas
seul.

**À l'appairage.** L'appareil crée une paire de clés Ed25519 (RFC 8032) pour
ce serveur, conserve sa clé privée avec le jeton, et envoie la clé publique
avec sa demande d'appairage, `"key": {"alg": "ed25519", "public_key":
"<base64 of its 32 bytes>"}`. Le serveur lie à cette clé le jeton qu'il
délivre. Un appareil qui s'appaire de nouveau crée une nouvelle clé.

- Un serveur qui délivre des jetons MUST proposer cette fonctionnalité : il
  accepte `key` à l'appairage, y lie le jeton et vérifie les signatures
  ci-dessous ; son `features.signatures` vaut alors 1, pour chaque
  appelant. [L-5.4-1]
- Un client SHOULD envoyer une clé quand il s'appaire. [L-5.4-2] Un client
  qui s'est appairé avec une clé MUST signer chaque requête qui porte son
  jeton. [L-5.4-3] Il MUST NOT envoyer sa clé privée où que ce soit.
  [L-5.4-4] Il SHOULD la conserver là où son système protège les clés,
  quand il dispose d'un tel endroit. [L-5.4-5]
- Un jeton délivré sans clé est **porteur seul** (bearer-only). Un serveur
  MAY refuser d'en délivrer, avec `400` `key_required` à une demande
  d'appairage sans `key`, et MAY refuser les jetons porteurs seuls qu'il a
  délivrés auparavant, avec `401` `signature_required`.
  `auth.bearer_only` (§ 4.2) dit s'il en délivre et en accepte encore.

**Signer une requête** (RFC 9421, signatures de messages HTTP). Une requête
qui porte un jeton lié porte une signature de ces composants, dans cet
ordre :

| Composant | Contenu |
|---|---|
| `"@method"` | La méthode, en majuscules (`GET`). |
| `"@target-uri"` | L'URI absolue de la requête (RFC 9421 § 2.2.2) : le schéma, l'hôte tel que dans `Host`, en minuscules, son port seulement s'il n'est pas celui par défaut du schéma, puis le chemin et la requête exactement tels qu'envoyés, leur encodage pour-cent inchangé. |
| `"authorization"` | La valeur de l'en-tête `Authorization` telle qu'envoyée. |
| `"content-digest"` | Seulement quand la requête a un corps : l'en-tête `Content-Digest` (RFC 9530, `sha-256`), que la requête porte alors. |

et ces paramètres, dans cet ordre : `created`, l'heure du client en
secondes Unix ; `nonce`, 22 à 64 caractères de base64url (`A`–`Z`,
`a`–`z`, `0`–`9`, `-`, `_`) contenant au moins 128 bits aléatoires,
nouveau pour chaque requête ; `keyid`, l'empreinte de la clé, le base64url
du SHA-256 de ses 32 octets, sans remplissage ; et `alg`, `"ed25519"`.
L'étiquette de la signature est `lantern` :

```http
GET /api/lantern/v1/apps?page_size=50 HTTP/1.1
Host: shelf.example.org
Authorization: Bearer et_c8V1nQ0xYb
Signature-Input: lantern=("@method" "@target-uri" "authorization");created=1793345400;nonce="tQ0Vb3Yt7sXx2c1mZ8kq4A";keyid="Zp3pS0eHqf…";alg="ed25519"
Signature: lantern=:<base64 of the 64 bytes>:
```

La base de signature (RFC 9421 § 2.5) compte une ligne par composant, puis
les paramètres, reliés par un saut de ligne (`\n`), sans saut de ligne
final :

```text
"@method": GET
"@target-uri": https://shelf.example.org/api/lantern/v1/apps?page_size=50
"authorization": Bearer et_c8V1nQ0xYb
"@signature-params": ("@method" "@target-uri" "authorization");created=1793345400;nonce="tQ0Vb3Yt7sXx2c1mZ8kq4A";keyid="Zp3pS0eHqf…";alg="ed25519"
```

`@signature-params` est la valeur du membre `lantern` de
`Signature-Input`, exactement telle qu'envoyée. `Signature` est la
signature Ed25519 des octets UTF-8 de la base, en base64 (avec
remplissage) entre deux-points. Les deux en-têtes ne portent que le membre
`lantern`. Les octets sont détaillés, cas par cas, dans
`vectors/signatures.json`.

Un serveur MUST vérifier la signature de chaque requête qui porte un jeton
lié, dans cet ordre, et répondre `401` (avec `WWW-Authenticate: Bearer
realm="lantern", error="invalid_token"`) avec le code indiqué : [L-5.4-6]

1. pas de `Signature-Input` ou pas de `Signature` : `signature_required` ;
2. un `Signature-Input` qui n'a pas la forme ci-dessus (d'autres composants
   ou dans un autre ordre, un paramètre manquant, un autre `alg`), un
   `keyid` qui n'est pas la clé du jeton, un `Content-Digest` absent d'une
   requête avec corps, ou une signature qui ne se vérifie pas :
   `signature_invalid` ;
3. un `created` de plus de `auth.skew` secondes avant ou après l'horloge du
   serveur : `signature_expired` ;
4. un `nonce` que le serveur a déjà vu pour cette clé dans la fenêtre :
   `signature_replayed`.

Un corps qui ne correspond pas à son `Content-Digest` donne `422`
`digest_mismatch`, comme au § 9.2.

- **Horloge.** `auth.skew` vaut 300 secondes, sauf si un serveur en annonce
  une autre valeur, entre 60 et 900. Chaque réponse d'un serveur MUST porter
  `Date` (RFC 9110 § 6.6.1). [L-5.4-7] Un client dont la signature a été
  refusée comme `signature_expired` SHOULD calculer le décalage de son
  horloge par rapport à cette `Date` et signer de nouveau avec, une fois :
  l'horloge d'une console est souvent fausse. [L-5.4-8]
- **Rejeu.** Un serveur MUST conserver chaque nonce qu'il a accepté, par
  clé, pendant au moins deux fois `auth.skew`, et le refuser de nouveau
  pendant ce temps. [L-5.4-9] Une requête n'est ainsi acceptée qu'une fois,
  dans sa fenêtre, quoi que rejoue le réseau.
- Un `401` dû à une signature SHOULD porter `Accept-Signature` (RFC 9421
  § 5.1) avec les composants et paramètres attendus. [L-5.4-10]
- **Interroger avec une clé.** Un appairage qui a envoyé `key` interroge
  avec des requêtes signées par elle, sans `Authorization` : leurs
  composants sont `"@method"` et `"@target-uri"` seuls. Le serveur MUST ne
  donner le jeton qu'à une interrogation ainsi signée, et répondre `401`
  `signature_required` ou `signature_invalid` à toute autre. [L-5.4-11] Une
  adresse d'interrogation qui fuit ne donne rien.
- **Clés d'ordre faible.** Un serveur MUST refuser à l'appairage, avec
  `400`, une clé d'appareil qui ne se décode pas de façon canonique ou qui
  est l'un des 8 points d'ordre faible. [L-5.4-12] Il vérifie chaque
  signature d'une requête comme le dit le § 8.4 (`L-8.4-4`) : une clé ou un
  R d'ordre faible, ou un S supérieur ou égal à L, ne se vérifie jamais.
- Révoquer un appareil révoque son jeton et la liaison avec lui ; un
  appareil change de clé en s'appairant de nouveau.

### 5.5 Invitations

Une invitation permet à un appareil de s'appairer sans que personne ne se
connecte : un administrateur la crée (§ 5.7) et la transmet, sous forme de
lien ou de code.

```json
{"schema": 1, "id": "i_3VxQ", "code": "MZ7Q-4KHP-XW2N-8TRD",
 "link": "https://shelf.example.org/pair?invitation=MZ7Q-4KHP-XW2N-8TRD&spki=3f9a1c07…",
 "user": "sam", "scopes": ["library"], "expires": "2026-11-06T18:00:00Z",
 "devices": 2, "used": 0, "rating_cap": {"age": 12}, "note": "Sam's consoles",
 "created": "2026-10-30T18:00:00Z"}
```

- `code` : dans l'alphabet de l'appairage (§ 5.2), 16 à 32 symboles (au
  moins 80 bits), par groupes de 4. `link` : `verify` avec
  `invitation=<code>` dans sa requête et le `spki=<SHA-256 complet de sa
  clé, en hexadécimal minuscule>` du serveur (§ 5.3), toujours quand aucune
  autorité ne garantit son certificat.
- `user` : le compte que rejoignent les appareils ; `scopes` : ce qu'ils
  peuvent faire, un sous-ensemble des portées de ce compte ; `expires` :
  quand elle prend fin, 30 jours plus tard au plus ; `devices` : combien
  d'appareils peuvent l'utiliser, de 1 à 100 ; `used` : combien l'ont fait ;
  `rating_cap` (§ 5.6) et `note`, facultatifs.
- Un appareil l'utilise en s'appairant (§ 5.2) avec
  `"invitation": "<code>"`. L'appairage est approuvé aussitôt, pour le
  compte de l'invitation, avec celles des portées demandées que
  l'invitation détient, et son `rating_cap` : la première interrogation
  donne le jeton.
- Un serveur MUST NOT appairer un appareil avec une invitation inconnue,
  expirée, révoquée ou épuisée : il répond `410` `gone`. [L-5.5-1] Il MUST
  compter chaque appareil qu'il appaire avec une invitation, et s'arrêter à
  `devices`, même quand des appareils l'utilisent simultanément.
  [L-5.5-2] Il MUST limiter les tentatives sur les codes d'invitation par
  adresse comme il le fait pour les codes d'appairage (§ 5.2). [L-5.5-3]
- Un appareil appairé par une invitation garde son jeton quand
  l'invitation est révoquée ou expire : un administrateur révoque
  l'appareil lui-même (§ 5.7).
- Une invitation est un secret tant qu'elle peut être utilisée : elle est
  transmise par un canal auquel l'administrateur fait confiance, et
  quiconque la détient s'appaire.

### 5.6 Plafonds de classification

Un jeton MAY porter un plafond de classification par âge, fixé quand son
appareil est approuvé (sur la page du serveur, ou par le § 5.7) ou par son
invitation (§ 5.5), jamais par l'appareil lui-même : un contrôle parental
tenu sur le serveur, que la console d'un enfant ne peut pas assouplir.

```json
"rating_cap": {"age": 12, "unrated": "show"}
"rating_cap": {"system": "PEGI", "rating": "12", "unrated": "hide"}
```

Un plafond est un `age`, ou une classification d'un `system`, lue comme
l'âge que lui donne le tableau ci-dessous ; `unrated` dit ce que devient ce
qui n'a aucune classification que ce tableau sache lire : `show` (en
l'absence du champ) ou `hide`.

| `system` | `rating` → âge |
|---|---|
| `PEGI` | `3` 3, `7` 7, `12` 12, `16` 16, `18` 18 |
| `ESRB` | `EC` 3, `E` 6, `E10+` 10, `T` 13, `M` 17, `AO` 18 |
| `CERO` | `A` 0, `B` 12, `C` 15, `D` 17, `Z` 18 |
| `USK` | `0` 0, `6` 6, `12` 12, `16` 16, `18` 18 |
| `ACB` | `G` 0, `PG` 8, `M` 15, `MA15+` 15, `R18+` 18, `X18+` 18 |
| `CLASSIND` | `L` 0, `10` 10, `12` 12, `14` 14, `16` 16, `18` 18 |
| `GRAC` | `ALL` 0, `12` 12, `15` 15, `18` 18 |

Une classification d'un autre système, ou une que sa ligne ne liste pas
(`RP`), est une classification que ce tableau ne sait pas lire. L'âge d'un
titre (§ 7.1), ou d'un homebrew qui a des `ratings` (§ 8.1), est, pour un
plafond exprimé dans un `system`, sa classification dans ce système quand
il en a une ; sinon, et pour un plafond exprimé en `age`, le plus élevé des
âges de ses classifications que le tableau sait lire : le plafond fixé par
un parent n'est jamais assoupli par l'organisme le plus indulgent. S'il
n'en a aucune, il est non classé. Il dépasse le plafond quand son âge est
supérieur à celui du plafond.

Un serveur MUST cacher à un jeton plafonné tout titre au-dessus de son
plafond (ou non classé, avec `unrated` `hide`), les apps d'un tel titre, et
chaque homebrew au-dessus de ce plafond, partout : [L-5.6-1]

- les listages, ce qui manque, les mises à jour et les changements
  (§ 6.2–6.4, § 8.5) les omettent ; le `total` d'une page ne compte que ce
  que voit le jeton ;
- `GET <base>/v1/titles/{title_id}`, `GET <base>/v1/homebrew/{id}`, le
  fichier d'une app ou d'un homebrew caché, et un lot de codes de triche
  d'un titre caché donnent `404`, comme si le serveur n'en avait pas ;
  `GET <base>/v1/titles?ids=` liste les identifiants cachés dans
  `unknown` ; les changements de titres (§ 7.3) les omettent.

- La poignée de main MUST montrer à son jeton son plafond dans
  `account.rating_cap`. [L-5.6-2] Aucune route ne permet à un appareil de
  le changer.
- Un plafond de classification est un filtre, pas un verrou : une app
  téléchargée auparavant, un jeu que la console a déjà, ou un autre
  serveur, sont hors de sa portée.

### 5.7 Administration (fonctionnalité `admin`)

Une petite API pour une application d'administration, sur un téléphone par
exemple : comptes, appareils, appairages en attente et invitations. Chaque
route ci-dessous exige la portée `admin` ; la famille est proposée
(`features.admin`) aux appelants qui la détiennent. Les listes sont des
pages, comme au § 6.2 : `{"schema":1, "items":[…], "total":3,
"next":null}`, avec `cursor` et `page_size`.

| Route | Rôle |
|---|---|
| `GET <base>/v1/admin/users` | Les comptes : `{"name":"lea", "state":"active", "scopes":["library","saves"], "devices":2, "created":"…"}`. |
| `POST <base>/v1/admin/users` | `{"schema":1, "name":"sam", "scopes":["library"]}` → `201` le compte ; `409` `conflict` quand le nom est pris. |
| `PATCH <base>/v1/admin/users/{name}` | `{"schema":1, "state":"frozen"}`, ou `"active"`, et `scopes` → `200` le compte. |
| `DELETE <base>/v1/admin/users/{name}?confirm=<name>` | Supprime le compte → `204` : ses appareils, invitations et appairages en attente, ses sauvegardes, ses demandes et ses données de synchronisation. |
| `GET <base>/v1/admin/devices?user=` | Les appareils, un jeton chacun : `{"id":"d_…", "user":"lea", "device":"Lea's Switch", "scopes":[…], "created":"…", "bound":true, "key":"<short fingerprint>", "rating_cap":{…}, "invitation":"i_…", "expires":"…"}`. |
| `DELETE <base>/v1/admin/devices/{id}` | Révoque le jeton de l'appareil → `204`. |
| `GET <base>/v1/admin/pairings` | Les appairages en attente d'approbation : `{"id":"pr_…", "code":"KQ4M-7TXD", "device":"Lea's Switch", "scopes":[…], "key":"<short fingerprint>", "created":"…", "expires":"…"}`. |
| `POST <base>/v1/admin/pairings/{id}` | `{"schema":1, "decision":"approve", "user":"lea", "scopes":["library"], "rating_cap":{"age":12}}` → `204` ; `"decision":"refuse"` → `204`, et l'interrogation de l'appareil reçoit `410`. |
| `GET <base>/v1/admin/invitations` | Les invitations encore utilisables (§ 5.5). |
| `POST <base>/v1/admin/invitations` | `{"schema":1, "user":"sam", "scopes":["library"], "expires":"2026-11-06T18:00:00Z", "devices":2, "rating_cap":{"age":12}, "note":"…"}` → `201` l'invitation, avec son `code` et son `link`. |
| `DELETE <base>/v1/admin/invitations/{id}` | La révoque → `204` : son code donne `410`. |

- Un serveur MUST répondre à chaque route de cette famille par `403`
  `forbidden` pour un jeton sans la portée `admin` (`401` sans jeton).
  [L-5.7-1]
- Un serveur MUST NOT renvoyer de jeton, d'empreinte de jeton, de mot de
  passe ni d'empreinte de mot de passe dans aucun document de cette
  famille. [L-5.7-2]
- Un appareil révoqué ou un compte gelé MUST perdre son accès
  immédiatement, dès sa requête suivante. [L-5.7-3]
- Une approbation MUST accorder au plus les portées que l'appareil a
  demandées et que son compte détient ; `user` est le compte de
  l'administrateur lui-même quand il est absent, et `scopes` les portées
  demandées. [L-5.7-4]
- Le `name` d'un compte compte 1 à 64 lettres, chiffres, `.`, `_` et `-`.
  Un compte créé ici n'a pas de mot de passe : ses appareils s'appairent
  par invitation, ou sont approuvés ici ; les moyens propres du serveur
  peuvent lui en donner un.
- Une application d'administration MUST afficher, à côté de chaque
  appairage en attente, son code et l'empreinte courte de la clé du serveur
  telle que l'application l'a épinglée, pour que son utilisateur les
  compare avec l'écran de la console comme sur la page du serveur (§ 5.3).
  [L-5.7-5]

**Supprimer un compte.** `confirm` répète le nom du compte, pour qu'un
geste malheureux ne supprime rien ; une application d'administration
demande à son utilisateur de le saisir.

- Un serveur MUST refuser une suppression dont le `confirm` n'est pas le
  nom du compte, avec `400`, et la suppression du propre compte de
  l'appelant, avec `409` `conflict`. [L-5.7-6] Il MAY refuser, avec `409`
  `conflict`, de supprimer un compte que sa propre configuration définit (un
  fichier de comptes qu'il ne fait que lire), et le dit dans `detail`.
- Une suppression MUST prendre effet immédiatement et en entier : les
  jetons du compte donnent `401` dès leur requête suivante, ses invitations
  `410`, ses appairages en attente sont refusés, et ses sauvegardes, ses
  demandes et ses données de synchronisation (§ 20) sont effacées ; le nom
  donne ensuite `404` sur les routes de cette famille. [L-5.7-7] Un compte
  créé plus tard sous le même nom n'en hérite rien.
- Une suppression ne peut pas être annulée : le protocole ne garde aucun
  compte dans une corbeille.

## 6. Bibliothèque (fonctionnalité `library`)

### 6.1 App

Une app est un paquet installable : un jeu de base, une mise à jour ou un
contenu additionnel.

```json
{"id": "a_9Qx2…",
 "platform": "switch",
 "title_id": "0100ABCD00010000",
 "app_id": "0100ABCD00010800",
 "type": "update",
 "version_code": 196608,
 "version_name": "1.3.0",
 "name": "Frostline Tales",
 "size": 734003200,
 "installed_size": 1073741824,
 "format": "nsz",
 "sha256": "3a7bd3e2…",
 "atlas": "Q900001",
 "added": "2026-10-28T19:02:11Z",
 "file": "<base>/v1/files/f_Zk…"}
```

- `id` : opaque, stable tant que le fichier ne change pas.
- `platform` : la plateforme à laquelle elle est destinée (§ 4.3).
- `title_id` : l'identifiant du jeu ; `app_id` : l'identifiant de ce
  paquet, le même que `title_id` là où la plateforme n'en a pas d'autre. Ce
  sont deux chaînes opaques de 1 à 128 lettres, chiffres, `.`, `_` et `-`,
  comparées à l'identique (casse comprise), dont le profil de la plateforme
  donne la forme (annexe A). Un identifiant n'est unique qu'au sein de sa
  plateforme. `changes` n'est jamais un identifiant de titre (§ 7.3).
- `type` : un mot en minuscules tiré de la liste du profil. `base` (un jeu),
  `update` (une version plus récente d'un jeu, dans un paquet à part) et
  `dlc` (un contenu additionnel) ont le même sens sur toutes les plateformes
  qui les connaissent.
- `version_code` : un entier, tel que le profil le dérive ; les clients
  comparent des entiers, jamais du texte. `version_name`, facultatif, est la
  version lisible par les personnes (`1.3.0`), jamais comparée. Vecteurs de
  test : `vectors/version-codes.json`.
- `size` : en octets, un entier sur 64 bits. `installed_size`, facultatif :
  les octets qu'occupe l'app une fois installée, quand le serveur les
  connaît (ceux d'un `nsz`, décompressé), qu'un client compare à son espace
  libre (§ 6.3).
- `format` : un mot en minuscules tiré de la liste des formats de paquet du
  profil.
- `sha256` : celui du fichier tel qu'il est servi, en hexadécimal
  minuscule. Un serveur MUST le donner, après avoir haché le fichier avant
  de le lister. [L-6.1-1]
- `atlas`, facultatif : l'identifiant du jeu dans
  [Atlas](https://atlas.boreale.dev/), les données ouvertes sur les jeux de
  Boréale : son élément Wikidata, `Q` suivi de chiffres (`Q900001`), la clé
  du `links.json` d'Atlas, qui relie entre eux les identifiants d'un jeu sur
  chaque plateforme (un identifiant de titre Switch, un identifiant d'app
  Steam…). Un client MAY lire les données d'Atlas grâce à lui (la notoriété
  d'un jeu, ses prix, des jeux similaires) ; les fichiers d'Atlas pour une
  plateforme sont indexés par les identifiants propres à cette plateforme,
  que donne `links.json`. C'est une indication sur le jeu, jamais son
  identité : un client MUST NOT installer ni apparier quoi que ce soit sur
  la seule foi d'`atlas`. [L-6.1-2] Atlas est une adresse externe (§ 7.1).
- `mirrors`, facultatif : d'autres adresses du même fichier, depuis
  lesquelles un client peut le lire (§ 19.2).

### 6.2 Listage

`GET <base>/v1/apps?platform=&type=&title_id=&q=&sort=&page_size=&cursor=` →

```json
{"schema": 1, "items": [App, …], "total": 4123, "next": "c_…"}
```

- `platform` l'emporte sur `Lantern-Platform` (§ 4.3) ; `type` et
  `title_id` MUST filtrer, et `q` cherche dans les noms. [L-6.2-1]
- `sort` : `name` (par défaut), `added` ou `release` (tous deux du plus
  récent au plus ancien) ; les ex aequo MUST être départagés par `id`, pour
  que l'ordre soit stable. [L-6.2-2]
- `cursor` est opaque ; `next` vaut `null` sur la dernière page. Lire avec
  un curseur pendant que la bibliothèque change MUST ne sauter ni répéter
  aucune app. [L-6.2-3]
- Un curseur MUST donner `410` quand il a expiré (le client relit alors la
  liste depuis le début), et `400` quand le serveur ne l'a jamais donné, ou
  l'a donné pour un autre listage (ou `410`, quand le serveur ne sait pas le
  distinguer d'un curseur expiré). [L-6.2-4]
- `page_size` vaut au plus `limits.page_size` ; une valeur plus grande MUST
  être ramenée à cette limite. [L-6.2-5]

### 6.3 Ce qui manque à l'appareil

`POST <base>/v1/apps/missing`, avec `Lantern-Platform` (ou `?platform=`) :
`400` sans.

```json
{"schema": 1,
 "installed": [{"app_id": "0100ABCD00010000", "version_code": 0},
               {"app_id": "0100ABCD00010800", "version_code": 131072}],
 "want": ["update", "dlc"]}
```

→ un listage (§ 6.2), pour cette plateforme, qui MUST contenir exactement :
[L-6.3-1]

- avec `update` dans `want` : pour chaque jeu installé, sa mise à jour la
  plus récente dont le `version_code` est supérieur au plus élevé des
  `version_code` installés de ce jeu. Une mise à jour est une app de type
  `update`, ou, sur une plateforme dont le profil dit qu'un paquet plus
  récent remplace le jeu de base, une app de type `base` du même `app_id` ;
- avec `dlc` : les contenus additionnels des jeux installés qui ne sont pas
  installés ;
- avec `base` : les jeux qui ne sont pas installés.

Un serveur connaît le jeu d'une app installée par sa bibliothèque, ou par
la règle du profil quand il en a une. Paginé avec `cursor` dans la requête.

**Espace libre.** C'est le client qui décide de ce qui tient, pas le
serveur : il compare son espace libre à l'`installed_size` de chaque app
(sa `size` quand il n'y en a pas), et dit lesquelles ne tiennent pas avant
de les télécharger. La requête ne porte pas l'espace libre de l'appareil.
Seul l'appareil connaît ses stockages (une carte, sa mémoire interne), ce
qu'une installation demande en plus du paquet, et ce que son utilisateur
s'apprête à supprimer ; et la réponse reste la même pour tous les
appareils d'une plateforme, ce qui la rend simple à calculer et à mettre
en cache.

### 6.4 Changements (fonctionnalité `changes`)

`GET <base>/v1/changes?since=<token>` → `{"schema":1, "added":[App…],
"removed":["a_…"], "since":"<next token>"}`, pour la plateforme que le
client a nommée, ou pour toutes les plateformes. Sans `since`, la route
MUST ne renvoyer aucune app, et le jeton courant. [L-6.4-1] Un jeton
`since` MUST donner `410` quand il est trop ancien pour le serveur (le
client relit alors toute la bibliothèque), et `400` quand le serveur ne l'a
jamais donné (ou `410`, comme pour un curseur, § 6.2). [L-6.4-2] Avec
`wait`, une requête attend que quelque chose change, et son document porte
les événements du § 18 (§ 18.3).

### 6.5 Sections (fonctionnalité `sections`)

`GET <base>/v1/sections` → `{"schema":1, "sections":[{"id":"new",
"title":"New", "apps":["a_…", …]}, …]}` : des rayons que le serveur
compose. Un client MAY les afficher à côté des siens.

### 6.6 Fichiers

`GET <file>` :

- MUST prendre en charge `Range` (`206` ; `416` avec
  `Content-Range: bytes */<size>`) et envoyer `Content-Length`,
  `Accept-Ranges: bytes` et un `ETag` fort. [L-6.6-1]
- MUST envoyer `Repr-Digest: sha-256=:<base64>:` (RFC 9530) sur chaque
  réponse, entière (`200`) ou partielle (`206`), et sur `HEAD` : l'empreinte
  du fichier entier, la même que le `sha256` de l'app. [L-6.6-2]
- Les octets servis MUST être ceux dont le document donne le SHA-256, de la
  taille qu'il donne, sans `Content-Encoding` (§ 2.1). [L-6.6-3]
- L'identifiant dans le chemin est opaque et non énumérable. Il MAY
  expirer : le client relit alors l'app. Un identifiant inconnu ou expiré
  MUST donner `404` ou `410`. [L-6.6-4]
- Un serveur MAY proposer une forme décompressée d'un fichier compressé
  sous une entrée d'app distincte (avec ses propres `format`, `size` et
  `sha256`), jamais en silence.
- Un client MUST vérifier le SHA-256 de ce qu'il a téléchargé par rapport
  au `sha256` de l'app avant de l'installer, et le refuser s'ils diffèrent.
  [L-6.6-5]

Il en va de même pour tout fichier vers lequel pointe le protocole : les
paquets de homebrews (§ 8), les sauvegardes (§ 9) et les lots de codes de
triche (§ 10).

## 7. Titres (fonctionnalité `titles`)

Ce que le serveur sait d'un jeu, sur une plateforme : la fiche qu'un client
affiche à côté de ses apps. Lue avec la portée `library`.

### 7.1 Un titre

`GET <base>/v1/titles/{title_id}` →

```json
{"schema": 1, "platform": "switch", "title_id": "0100ABCD00010000",
 "language": "en", "name": "Frostline Tales",
 "publisher": "Fjord Works", "developer": "Fjord Works",
 "release": "2025-03-14", "updated": "2026-10-28T19:02:11Z",
 "atlas": "Q900001",
 "genres": ["adventure", "puzzle"], "tags": ["co-op", "winter"],
 "players": {"min": 1, "max": 4, "online": true, "online_max": 8},
 "ratings": [{"system": "PEGI", "rating": "7"}, {"system": "ESRB", "rating": "E10+"}],
 "languages": ["en", "fr", "ja"],
 "summary": "Guide a lantern-bearer across a frozen archipelago.",
 "description": "…",
 "icon": {"url": "<base>/v1/media/9f2c….jpg", "width": 256, "sha256": "9f2c…"},
 "banner": {…}, "screenshots": [{…}],
 "video": {"url": "https://video.example.org/frostline", "external": true}}
```

- `platform` et `title_id` : comme pour une app (§ 6.1). Un titre est
  propre à une plateforme : le même jeu sur deux plateformes a deux titres.
  Un titre de la bibliothèque MUST être servi pour sa plateforme, et un
  titre inconnu donner `404`. [L-7.1-1]
- `language` dit dans quelle langue sont `summary` et `description`, la
  meilleure dont dispose le serveur pour `Accept-Language` (§ 2.2).
- `atlas`, facultatif : l'identifiant Atlas du jeu (§ 6.1).
- `genres` : zéro ou plusieurs genres d'une liste fixe, `action`,
  `adventure`, `rpg`, `strategy`, `simulation`, `sports`, `racing`,
  `puzzle`, `platformer`, `shooter`, `fighting`, `music`, `party`,
  `education` et `other`. Une version ultérieure peut ajouter des genres :
  un client affiche un genre qu'il ne connaît pas comme `other`. `tags` sont
  des mots libres (32 au plus, de 64 octets chacun).
- `players` : `min` et `max` sur un même appareil ; `online`, si le jeu se
  joue en ligne, et `online_max`, combien de joueurs au plus.
- `ratings` : les classifications par âge, chaque `system` étant le nom
  court d'un organisme (`PEGI`, `ESRB`, `CERO`, `USK`, `ACB`, `CLASSIND`,
  `GRAC`…) et `rating` sa classification telle que cet organisme l'écrit
  (`7`, `E10+`, `A`). Les plafonds de classification les lisent (§ 5.6).
- `release` : la date de sortie du jeu ; `updated` : la date du dernier
  changement de cette fiche.
- `icon`, `banner`, `screenshots` (16 au plus) : des images. Une image sur
  l'origine du serveur SHOULD être adressée par son contenu et servie avec
  une longue durée de cache. [L-7.1-2] Une image ailleurs MUST être marquée
  `"external": true`. [L-7.1-3]
- `video` : une page ou une vidéo ailleurs, toujours `external`.
- Un client MUST NOT envoyer de jeton, ni aucun identifiant de connexion, à
  une adresse `external`. [L-7.1-4] Il SHOULD n'ouvrir une `video` que si
  l'utilisateur le demande. [L-7.1-5]

### 7.2 Plusieurs titres à la fois

`GET <base>/v1/titles?ids=<id>,<id>,…` (100 au plus, séparés par des
virgules) → `{"schema":1, "titles":[Title…], "unknown":["…"]}` : les titres
que le serveur a parmi ces identifiants, pour la plateforme que le client a
nommée (ou pour chaque plateforme qui a l'identifiant), et les identifiants
qu'il ne connaît pas. Un serveur MUST placer chaque identifiant demandé
dans l'une des deux listes, et répondre `400` à plus de 100 identifiants.
[L-7.2-1]

### 7.3 Changements

`GET <base>/v1/titles/changes?since=<token>` → `{"schema":1,
"titles":[Title…], "removed":[{"platform":"switch","title_id":"…"}],
"since":"<next token>", "more":false}` : les titres ajoutés ou modifiés, et
ceux supprimés, depuis le jeton ; un serveur MUST suivre pour eux les
règles du § 6.4, et de même pour ses jetons. [L-7.3-1] Un serveur MAY n'en
donner qu'une partie : `more` vaut alors `true`, et le client redemande
avec le nouveau `since`.

## 8. Homebrews (fonctionnalité `homebrew`)

Les homebrews que propose un serveur : des applications, des jeux, des
portages et des outils faits par leurs auteurs, lus avec la portée
`library`. Les mods (des fichiers qui modifient un jeu) sont hors du champ
de cette version.

### 8.1 Une entrée

`GET <base>/v1/homebrew/{id}` →

```json
{"schema": 1,
 "id": "org.example.frostline", "platform": "switch",
 "kind": "app", "name": "Frostline", "author": "Noor",
 "tags": ["journal", "night mode"], "version": "1.4.0", "build": 10400,
 "license": "MIT", "source": "https://code.example.org/noor/frostline",
 "language": "en", "summary": "A pocket journal for long nights.",
 "description": "…",
 "icon": {"url": "https://media.example.org/frostline/icon.jpg", "external": true},
 "screenshots": [],
 "requires": {"text": "Atmosphère 1.7 or later", "min": {"atmosphere": "1.7.0"}},
 "updated": "2026-10-29T08:00:00Z",
 "package": {"format": "zip", "file": "<base>/v1/files/f_…",
             "size": 482113, "installed_size": 471136,
             "sha256": "…", "manifest_sha256": "…",
             "manifest": [{"path": "/switch/org.example.frostline/frostline.nro",
                           "size": 471040, "sha256": "…"},
                          {"path": "/config/org.example.frostline/settings.ini",
                           "size": 96, "sha256": "…"}]},
 "signature": {"alg": "ed25519", "public_key": "<base64>", "value": "<base64>"}}
```

- `id` : stable, sous forme de DNS inversé, en minuscules
  (`org.example.frostline`) : celui de l'auteur, le même pour toutes les
  versions. Les identifiants sous `local.` sont propres à un serveur, pour
  un homebrew dont l'auteur n'en a pas donné ; ils ne sont stables que sur
  ce serveur. Un identifiant est unique au sein de sa plateforme.
- `system_id` : l'identifiant que la plateforme elle-même donne au logiciel
  installé, là où elle en a un (annexe A : un identifiant de titre Vita ou
  PS4, un identifiant de titre 3DS, un nom de paquet Android).
- `kind` : ce que c'est : `app`, `game` (un jeu à part entière), `port` (un
  jeu porté sur la plateforme, § 8.6), `emulator`, `tool`, `overlay`
  (affiché par-dessus d'autres logiciels), `sysmodule` (tourne en arrière-
  plan avec le système) ou `theme`. Un lecteur MUST lire un `kind` qu'il ne
  connaît pas, ou son absence, comme `app`. [L-8.1-1]
- `genres`, facultatif : zéro ou plusieurs des genres d'un titre (§ 7.1),
  de la même liste fixe, lus de la même façon (un genre qu'un lecteur ne
  connaît pas est `other`). Ils sont faits pour un `game` ou un `port` ; un
  autre `kind` MAY en avoir.
- `tags`, facultatif : des mots libres pour le reste, comme `video player`
  ou `file manager` (le § 13 les borne, comme ceux d'un titre).
- Un client construit ses rayons à partir de `kind` (Jeux, Portages,
  Émulateurs, Outils, Superpositions…) et, à l'intérieur, des sous-rayons à
  partir de `genres`. Une entrée n'a pas d'autre champ de rayon : la
  `category` d'un brouillon antérieur a disparu, et un serveur MUST NOT
  l'écrire. [L-8.1-2]
- `name`, `author`, `summary` et `description` (localisés, `language` comme
  pour un titre, § 7.1), `icon` et `screenshots` (des images, § 7.1).
- `license` : une expression de licence SPDX ; `source` : l'endroit où se
  trouve son code. `assets_license`, facultatif : la licence des
  ressources libres ou de remplacement qu'il embarque, quand elle diffère
  (SPDX, `LicenseRef-` permis).
- `version` est destiné aux personnes ; `build` est un entier qui croît à
  chaque version, celui que compare un client.
- `requires`, facultatif : ce dont l'appareil a besoin (§ 8.7) : `text`
  pour les personnes, les conditions qu'un client vérifie avant de proposer
  le paquet (`min` et `gpu`), et `homebrew`, les homebrews dont il a besoin
  (un environnement d'exécution, un chargeur, un greffon), chacun
  `{"id":…, "min_build":…}` de la même plateforme, qu'un client installe
  d'abord, ou dont il signale l'absence.
- `ratings`, facultatif : des classifications par âge, comme celles d'un
  titre (§ 7.1) ; les plafonds de classification les lisent (§ 5.6).
- `atlas`, facultatif : pour un `game` ou un `port`, l'identifiant Atlas du
  jeu (§ 6.1).
- `updated` : la date du dernier changement de cette entrée.
- `package` : le paquet (§ 8.2) ; `packages`, facultatif, d'autres paquets
  du même build pour d'autres architectures (§ 8.2).
- `port`, pour un `kind` `port` seulement : ce que dit le § 8.6.
- Une entrée MUST être la même sur sa propre route que dans un listage, aux
  manifestes près, que le listage omet. [L-8.1-3] Un identifiant inconnu
  MUST donner `404`. [L-8.1-4]

### 8.2 Paquets et manifestes

Un paquet est un fichier, téléchargé comme celui d'une app (§ 6.6) :
`format`, `file`, `size`, `sha256` et `manifest_sha256` sont REQUIRED.
[L-8.2-1] `installed_size`, facultatif, est ce qu'il occupe une fois
installé (pour une archive, la somme des tailles de son manifeste). C'est
soit :

- **un fichier unique**, d'un des formats du profil : `path` dit où il va
  sur l'appareil (le profil dit où va un format) ; soit
- **une archive** (`zip`) avec un **manifeste** : chaque fichier qu'elle
  installe, son `path` sur l'appareil, sa `size` et son `sha256`, tous
  REQUIRED. [L-8.2-2] L'archive MUST contenir chacun d'eux sous son chemin
  sans le `/` initial, de cette taille et de ce SHA-256 ; tout le reste
  qu'elle contient est ignoré. [L-8.2-3]

Un fichier unique est un manifeste d'une seule entrée : son `path`, sa
`size` et son `sha256`. Là où le profil dit que l'installateur propre à la
plateforme installe un format, le paquet n'a pas de `path`, et son
manifeste est vide (`[]`).

Un `path` est absolu sur le stockage de l'appareil, tel que le profil le
fait correspondre : il commence par `/` ; ses parties sont séparées par
`/`, aucune n'est vide, `.` ou `..` ; il ne contient ni `\`, ni `:`, ni
`"`, ni caractère de contrôle, ni NUL ; une partie fait au plus 255
octets, le chemin 1024. Deux chemins d'un même manifeste ne sont jamais
identiques à la casse près. Un serveur MUST NOT servir un manifeste qui
enfreint ces règles, ou dont des chemins se trouvent hors des racines du
profil pour les homebrews (annexe A). [L-8.2-4] Vecteurs de test :
`vectors/paths.json`.

`manifest_sha256` est le SHA-256, en hexadécimal minuscule, de la forme
canonique du manifeste : le tableau JSON de ses entrées triées par `path`
(en octets UTF-8), chaque entrée `{"path":…,"sha256":…,"size":…}` avec ses
clés dans cet ordre, sans espace, et les caractères non ASCII écrits tels
quels, en UTF-8. Un serveur MUST donner l'empreinte du manifeste qu'il
sert. [L-8.2-5] Un listage (§ 8.5) omet `manifest` et garde
`manifest_sha256` ; la route propre de l'entrée a les deux.

Sur une plateforme à plusieurs architectures (annexe A), un paquet MAY
porter `arch`, la liste de celles sur lesquelles il tourne : `aarch64`,
`armhf` (ARM 32 bits, virgule flottante matérielle), `x86`, `x86_64` ou
`riscv64` (RISC-V 64 bits) ; une version ultérieure peut en ajouter
d'autres, de 1 à 32 lettres minuscules, chiffres et `_`. Un nom qui n'a
pas cette forme enfreint ce texte. Un lecteur MUST traiter un nom bien
formé qu'il ne connaît pas comme n'étant pas sa propre architecture : il
n'installe jamais un paquet sur la seule foi de ce nom. [L-8.2-6] Un paquet
sans `arch` tourne sur toutes les architectures de sa plateforme (un
paquet pour un environnement d'exécution, comme un script ou du bytecode,
n'en a pas). Chaque paquet de `packages` MUST avoir un `arch`, et une
`signature` quand l'entrée est signée (§ 8.4). [L-8.2-7] Un client prend
un paquet dont l'`arch` liste la sienne, ou à défaut un paquet sans
`arch` ; il MUST ignorer les autres, et ne rien installer quand aucun ne
convient. [L-8.2-8] Sur une plateforme à une seule architecture (l'annexe A
le dit), un paquet MUST NOT porter `arch`. [L-8.2-9]

Un paquet MAY porter `mirrors`, comme une app (§ 19.2).

Là où le profil le dit (Android), un paquet porte aussi `signer_sha256` :
le SHA-256, en hexadécimal minuscule, du certificat qu'utilise la
signature propre à la plateforme pour ce paquet.

### 8.3 Installation

Un client MUST :

- refuser un paquet dont le téléchargement ne correspond pas à son
  `sha256`, ou un fichier d'une archive qui ne correspond pas à son entrée
  du manifeste ; [L-8.3-1]
- refuser un manifeste qui contient un chemin enfreignant le § 8.2, ou situé
  hors des racines du profil pour les homebrews (annexe A), et n'en rien
  installer ; [L-8.3-2]
- n'écrire que les chemins du manifeste, et seulement des fichiers : ne
  jamais suivre un lien qui en sort ; [L-8.3-3]
- n'écrire sans demander que sous les racines du profil qui n'exigent pas
  de consentement ; pour tout chemin ailleurs, montrer chacun de ces
  chemins à l'utilisateur et n'installer que s'il est d'accord ; [L-8.3-4]
- refuser une entrée dont le `system_id` est celui d'un logiciel qu'un
  autre `id` a installé, et n'en rien installer ; [L-8.3-5]
- conserver chaque manifeste installé, et ne désinstaller que d'après lui :
  supprimer ses fichiers, puis les dossiers qu'il a créés et qui restent
  vides, rien d'autre. Une mise à jour supprime les fichiers de l'ancien
  manifeste que le nouveau n'a plus. [L-8.3-6]

Un serveur MUST NOT servir deux entrées d'une même plateforme ayant le même
`system_id`. [L-8.3-7]

### 8.4 Signature

Un auteur MAY signer ses paquets avec ed25519 (RFC 8032). L'entrée porte
alors `signature` : `alg` (`ed25519`), `public_key` (les 32 octets de la
clé, en base64) et `value` (les 64 octets de la signature, en base64).

Les octets signés sont les octets UTF-8 de l'objet JSON

```text
{"build":<build>,"id":"<id>","manifest_sha256":"<hex>","platform":"<platform>","purpose":"lantern-homebrew-1","sha256":"<hex>"}
```

avec ces clés dans cet ordre, sans espace, `build` en décimal, et les
valeurs de l'entrée, `sha256` et `manifest_sha256` étant celles de
`package`. La forme de chaque valeur (§ 8.1, § 8.2, § 4.3) ne laisse rien à
échapper, si bien que les octets sont les mêmes pour tous ceux qui les
écrivent. Un paquet de `packages` porte sa propre `signature`, par la même
clé, sur le même objet avec ses propres `sha256` et `manifest_sha256`.
Vecteurs de test : `vectors/homebrew-signatures.json`.

- Un serveur MAY servir une signature qu'on lui donne, telle qu'on la lui
  donne ; il ne signe pas à la place d'un auteur. Il SHOULD vérifier une
  signature avant de la servir. [L-8.4-1]
- Un client MUST vérifier la signature du paquet qu'il installe quand il y
  en a une, et refuser le paquet quand elle ne se vérifie pas. [L-8.4-2]
- Un vérificateur de signature Ed25519 (d'un homebrew ici, d'une requête au
  § 5.4) MUST d'abord décoder la clé publique et le R de la signature, et
  refuser la signature quand l'un d'eux ne se décode pas, n'est pas encodé
  de façon canonique (un y supérieur ou égal à p, ou x = 0 avec son bit de
  signe à 1), ou est l'un des 8 points d'ordre faible ([8]P est l'élément
  neutre), et quand S est supérieur ou égal à L ; alors seulement il
  vérifie l'équation. [L-8.4-4] Sans cela, une clé et un R d'ordre faible
  avec S = 0 passent l'équation sans cofacteur pour environ un message sur
  8, et n'importe qui peut contrefaire une signature. Vecteurs de test :
  `vectors/ed25519-refused.json`.
- À la première installation d'un `id`, le client épingle sa `public_key`
  (ou le fait qu'il n'en avait pas). Une version ultérieure signée par une
  autre clé, ou non signée après une version signée, MUST être refusée sauf
  si l'utilisateur accepte explicitement le changement, après que le client
  a affiché les empreintes courtes des deux clés (le SHA-256 des 32 octets,
  sous la forme du § 5.3). [L-8.4-3]
- Un serveur MUST NOT servir une signature que L-8.4-4 refuse. [L-8.4-5]

### 8.5 Routes

- `GET <base>/v1/homebrew?platform=&q=&kind=&genre=&page_size=&cursor=` →
  une page (§ 6.2) d'entrées, triées par nom : `{"schema":1,
  "items":[Entry…], "total":12, "next":null}`. `q` garde les entrées dont le
  nom le contient, sans tenir compte de la casse ; `kind`, celles de ce
  `kind` (tel qu'un lecteur le lit, § 8.1) ; `genre`, celles dont les
  `genres` le contiennent. Ces filtres MUST garder ces entrées et aucune
  autre. [L-8.5-1] Un `kind` ou un `genre` qui n'est pas un mot en
  minuscules (1 à 32 lettres, chiffres et `_`, commençant par une lettre)
  MUST donner `400` ; un que le serveur ne connaît pas, une page vide.
  [L-8.5-2]
- `GET <base>/v1/homebrew/{id}` → l'entrée (§ 8.1), avec ses manifestes.
- `POST <base>/v1/homebrew/updates`, avec une plateforme (§ 4.3) :
  `{"schema":1, "installed":[{"id":"org.example.frostline", "build":10300}]}`
  → une page qui MUST contenir les entrées de ces identifiants dont le
  `build` est supérieur à celui installé, et seulement celles-là, paginée
  avec `cursor` dans la requête, comme au § 6.3. [L-8.5-3]

### 8.6 Portages de jeux

Un portage (`kind` `port`) est un jeu porté sur la plateforme, comme un
portage du code source ou une recréation du moteur d'un jeu, qui peut
tourner sur les données de la copie que l'utilisateur possède du jeu
original. Un serveur MUST NOT servir ces données : le paquet d'un portage
contient le portage et, tout au plus, des ressources libres de diffusion,
et aucune route de cette famille ne sert un fichier que le portage
réclame à l'utilisateur. [L-8.6-1]

Une entrée de `kind` `port` a un objet `port` :

```json
"port": {
  "original": {"name": "Harbor Lights", "year": 1998, "developer": "Fjord Works",
               "stores": [{"store": "gog", "id": "1207658000",
                           "url": "https://store.example.org/harbor-lights"}]},
  "engine": {"name": "Lighthouse", "version": "2.1.0",
             "source": "https://code.example.org/lea/lighthouse"},
  "data_root": "/switch/harborlights/",
  "assets": "user_owned",
  "requires_data": [
    {"path": "data/HARBOR.PAK", "size": 214748364,
     "accept": [{"sha256": "…", "label": "1.0"}, {"sha256": "…", "md5": "…", "label": "1.1"}],
     "hint": "In the folder where the game is installed."},
    {"one_of": [[{"path": "music/THEME.OGG", "hint": "From the soundtrack edition."}],
                [{"path": "data/MUSIC.PAK", "hint": "Next to HARBOR.PAK."}]],
     "optional": true}]}
```

- `original` : le jeu qu'il porte : son `name` et, facultatifs, son `year`,
  son `developer`, les `stores` qui le vendent (chaque `store` un nom de
  boutique d'Atlas, son `id` dans celle-ci, et son `url`, externe : § 7.1)
  et son `title` (`{"platform", "title_id"}`) quand un serveur l'a sous
  forme d'app.
- `engine` : son `name` et, facultatifs, sa `version`, sa `source` et sa
  `license` quand elle diffère de celle de l'entrée.
- `assets` : d'où viennent les ressources du jeu : `included` (des
  ressources libres dans le paquet, sous `assets_license`), `demo_included`
  (les données d'une démo, libres de diffusion, dans le paquet),
  `free_external` (des données libres que l'utilisateur récupère ailleurs)
  ou `user_owned` (tirées de la propre copie de l'utilisateur). Un lecteur
  lit une valeur qu'il ne connaît pas comme `user_owned`.
- `data_root` : le dossier où le portage attend ses données, sous la forme
  d'un chemin absolu (§ 8.2) qui se termine par `/`. Il se trouve sous les
  zones du profil réservées aux données des portages (annexe A) ;
  l'utilisateur l'approuve une fois, à la première installation. Dès lors,
  le client peut y écrire les fichiers de données de l'utilisateur sans
  redemander ; les fichiers propres au portage suivent toujours les racines
  du manifeste (§ 8.3).
- `requires_data` : les fichiers que fournit l'utilisateur, chacun étant
  soit un fichier, soit un groupe :
  - un fichier : `path`, relatif à `data_root`, exact (casse comprise) :
    des parties séparées par `/`, comme le dit le § 8.2, mais sans le `/`
    initial, et sans lettre de lecteur ; `size`, facultatif, en octets ;
    `accept`, facultatif, les versions connues du fichier que le portage
    accepte, chacune avec un `label` et un ou plusieurs de `sha256`, `sha1`
    et `md5` (en hexadécimal minuscule) ; `hint`, que chaque fichier a, qui
    dit où l'utilisateur le trouve dans sa copie, localisé comme
    `description`, et qui ne pointe jamais vers un téléchargement du
    fichier ; et `optional`, `true` quand le portage tourne sans lui
    (`false` en son absence) ;
  - un groupe : `one_of`, deux listes de fichiers ou plus, dont une seule
    suffit, et `optional` comme pour un fichier.
- Un serveur MUST servir un objet de portage de ces formes, son
  `data_root` dans les zones du profil. [L-8.6-2]

Un client MUST :

- refuser un portage dont le `data_root` ou l'un des chemins de données
  enfreint ces règles, et n'en rien installer ; [L-8.6-3]
- avant de lancer le portage, vérifier que chaque fichier non facultatif
  est présent et, quand un `accept` les donne, que son SHA-256 est l'un
  d'eux (il MAY vérifier `sha1` et `md5` là où aucun `sha256` n'est donné) ;
  sinon, ne rien lancer, et montrer à l'utilisateur chaque fichier manquant
  ou inconnu avec son `hint` ; [L-8.6-4]
- ne jamais récupérer ces données sur le réseau : l'utilisateur les copie
  depuis sa propre copie, par les moyens dont dispose l'appareil. [L-8.6-5]

Les fichiers de données d'un portage ne figurent jamais dans son
manifeste : une mise à jour ou une désinstallation (§ 8.3) ne les supprime
ni ne les écrase jamais.

### 8.7 Exigences matérielles et logicielles

`requires` dit ce dont un appareil a besoin pour faire tourner une entrée :

```json
"requires": {"text": "glibc 2.30, OpenGL ES 2 or Vulkan, 1 GiB of memory, 640×480",
             "min": {"glibc": "2.30", "ram_mb": 1024, "screen": "640x480"},
             "gpu": ["gles2", "vulkan"],
             "homebrew": [{"id": "org.example.lanternlight-runtime", "min_build": 200}]}
```

- `text`, REQUIRED : les exigences, pour les personnes. [L-8.7-1]
- `min` : le minimum dont l'appareil doit disposer. Ses clés sont celles du
  profil (annexe A), comme `firmware`, sous forme de nombres pointés
  (`18.0.0`), et celles-ci, que tout profil peut utiliser :
  - `glibc` : la version de la bibliothèque C GNU, pointée (`2.30`) ;
  - `ram_mb` : la mémoire, un entier, en Mio (`1024`) ;
  - `screen` : la taille de l'écran en pixels, `<width>x<height>`
    (`640x480`) : la largeur et la hauteur de l'appareil sont chacune au
    moins celles-là.
- `gpu` : les interfaces graphiques que l'entrée sait utiliser, `gles2`,
  `gles3` (OpenGL ES 2 et 3), `gl` (OpenGL de bureau) et `vulkan` :
  l'appareil doit en proposer au moins une. Une version ultérieure peut
  ajouter des noms.
- `homebrew` : les homebrews dont elle a besoin (§ 8.1).

`min` et `gpu` sont des conditions. Un client MUST les vérifier avant de
proposer un paquet : [L-8.7-2]

- une condition qu'il sait lire et que l'appareil ne remplit pas : le
  client n'installe pas le paquet, et dit quelle condition échoue et
  pourquoi (`glibc 2.30 or later; this device has 2.28`) ;
- une condition qu'il ne sait pas lire (une clé ou un nom de `gpu` qu'il ne
  connaît pas, une valeur d'une autre forme, ou quelque chose qu'il ne peut
  pas apprendre de l'appareil) : le client propose quand même le paquet,
  avec un avertissement qui nomme la condition, et affiche `text` ;
- sinon il propose le paquet. Deux versions pointées se comparent partie
  par partie, comme des nombres, une partie absente valant `0`.

Vecteurs de test : `vectors/requires.json`. Une clé de `requires` que ce
texte ne liste pas est une condition qu'un client ne sait pas lire, sauf
celles propres à un éditeur (`x-<vendor>-`, § 3.3), qu'il ignore.

Un serveur ne fait que servir les conditions, telles que l'auteur de
l'entrée les a données : il MUST garder les clés qu'il ne connaît pas, et
ne jamais juger un appareil d'après elles ni filtrer un listage avec elles.
[L-8.7-3]

## 9. Sauvegardes (fonctionnalité `saves`, portée `saves`)

### 9.1 Les sauvegardes

`GET <base>/v1/saves?platform=&title_id=` → `{"schema":1,
"saves":[Save…]}`, qui MUST contenir les sauvegardes du compte lui-même, de
la plus récente à la plus ancienne pour chaque titre, une sauvegarde étant :
[L-9.1-1]

```json
{"platform": "switch", "title_id": "0100ABCD00010000", "save_id": "s_03",
 "created": "2026-10-30T09:12:00Z", "size": 1052672, "sha256": "…",
 "kind": "account", "game_version_code": 196608, "profile": "Lea",
 "note": "Chapter 4", "device": "Lea's Switch"}
```

- `slot`, facultatif : lequel des dossiers de sauvegarde du titre il
  s'agit, quand un titre en a plusieurs (annexe A), tel que la plateforme
  le nomme (1 à 64 lettres, chiffres, `.`, `_` et `-`).
- `kind` : `account` (la sauvegarde d'un utilisateur), `device` (celle de
  l'appareil, partagée par ses utilisateurs), `bcat` (des données que le
  système a téléchargées pour le jeu), `cache`, ou `other`, selon la façon
  dont le profil fait correspondre les types propres à la plateforme.
- `game_version_code` : le `version_code` du jeu (§ 6.1) au moment de la
  sauvegarde, pour qu'un client SHOULD avertir avant de restaurer une
  sauvegarde sur un jeu plus ancien. [L-9.1-2]
- `profile` : le nom que l'utilisateur a donné au profil auquel appartient
  la sauvegarde, tel que l'appareil l'affiche. Jamais un identifiant
  matériel ou de compte.
- `device` : le nom de l'appareil appairé qui l'a envoyée (§ 5.2).
- `encryption`, seulement pour une sauvegarde chiffrée sur l'appareil : son
  schéma de chiffrement et son identifiant de clé (§ 9.4).
- L'archive est un zip dont le profil donne le contenu (annexe A) ; les
  octets d'une sauvegarde chiffrée sont ce zip, chiffré (§ 9.4).
- Le serveur garde au plus `limits.saves_kept_per_title` sauvegardes par
  titre, plateforme et compte, et supprime les plus anciennes au-delà.
- `GET` et `DELETE <base>/v1/saves/{title_id}/{save_id}` : l'archive, sous
  forme de fichier (§ 6.6), et sa suppression, qui MUST répondre `204`, la
  sauvegarde donnant ensuite `404`. [L-9.1-3]

Toute route qui écrit une sauvegarde exige une plateforme (§ 4.3).

### 9.2 En une seule requête

Pour une sauvegarde d'au plus `limits.save_body` octets :
`POST <base>/v1/saves/{title_id}`, l'archive zip comme corps
(`Content-Type: application/zip`), avec :

- `Content-Digest: sha-256=:<base64>:` (RFC 9530) : le serveur MUST
  répondre `400` sans lui, et `422` `digest_mismatch` quand le corps ne lui
  correspond pas. [L-9.2-1]
- `Lantern-Save-Kind`, `Lantern-Save-Slot` et `Lantern-Game-Version`
  (l'entier `game_version_code`), en ASCII tels quels ; `Lantern-Profile`
  et `Lantern-Note` (UTF-8, encodés en pour-cent) ; tous dans les limites
  du § 13.

→ `201` avec l'entrée de la sauvegarde. Un corps plus grand donne `413`.

### 9.3 Envoi reprenable

Pour toute sauvegarde jusqu'à `limits.save_size` octets, envoyée par
morceaux qui survivent à une connexion perdue :

1. `POST <base>/v1/saves/{title_id}/uploads` `{"schema":1,
   "size":5242880, "sha256":"…", "kind":"account",
   "game_version_code":196608, "profile":"Lea", "note":"Chapter 4"}` →
   `201` `{"schema":1, "upload":"<base>/v1/uploads/u_…",
   "chunk_size":1048576, "offset":0, "expires":"2026-10-31T09:12:00Z"}`. Une
   `size` supérieure à `limits.save_size` MUST donner `413`. [L-9.3-1]
2. `PATCH <upload>` avec `Upload-Offset: <n>` et un morceau d'au plus
   `chunk_size` octets comme corps (`Content-Type:
   application/offset+octet-stream`) → `204` avec le nouvel
   `Upload-Offset`. Un décalage différent de celui du serveur MUST donner
   `409` `conflict` avec l'`Upload-Offset` du serveur ; un morceau plus
   grand, `413`. [L-9.3-2] Un morceau MAY porter son propre
   `Content-Digest`, que le serveur vérifie alors (`422`
   `digest_mismatch`).
3. `HEAD <upload>` MUST répondre `204` avec `Upload-Offset` et
   `Upload-Length` : où reprendre après une interruption. [L-9.3-3] Un
   serveur ne garde que des morceaux entiers, ou dit dans `Upload-Offset`
   combien il a gardé d'un morceau coupé.
4. Le morceau qui atteint `size` termine l'envoi : le serveur MUST vérifier
   le SHA-256 de l'archive entière, puis répondre `201` avec l'entrée de la
   sauvegarde, ou `422` `digest_mismatch` et la jeter. [L-9.3-4]

`DELETE <upload>` abandonne un envoi (`204`). Un envoi non terminé à
`expires` disparaît (`404` ou `410`). Seul le compte qui a ouvert un envoi
le voit.

### 9.4 Chiffrement de bout en bout (fonctionnalité `encrypted_saves`)

Un client MAY chiffrer une sauvegarde avant de l'envoyer, avec une clé que
seuls les appareils de son utilisateur détiennent : le serveur conserve
alors des octets qu'il ne peut pas lire. Un serveur qui propose cette
famille conserve ces sauvegardes telles qu'elles arrivent, avec les
métadonnées qui restent en clair.

**La clé de sauvegarde.** 32 octets aléatoires, créés une fois, à partir de
la source d'aléa sûre de son système, par le premier appareil de
l'utilisateur qui chiffre, et transportés par l'utilisateur vers ses autres
appareils (ci-dessous). Elle ne va jamais à un serveur. Deux valeurs en
sont tirées par HKDF-SHA-256 (RFC 5869), avec un sel vide :

- l'**identifiant de clé**, les 8 premiers octets de HKDF(info
  `lantern-save-e2e-1 key id`), écrits en 16 chiffres hexadécimaux
  minuscules : la clé dont une sauvegarde a besoin, stocké et affiché en
  clair ;
- la **clé d'enveloppe**, 32 octets de HKDF(info `lantern-save-e2e-1 wrap`).

**Une sauvegarde, schéma `lantern-save-e2e-1`.** Pour chaque sauvegarde, le
client crée une **clé de fichier** aléatoire de 32 octets, l'enveloppe avec
la clé d'enveloppe, et chiffre l'archive (le zip du § 9.1) avec elle par
morceaux, avec XChaCha20-Poly1305 (draft-irtf-cfrg-xchacha-03 : HChaCha20,
puis le ChaCha20-Poly1305 de la RFC 8439), comme le fait le STREAM d'age
avec ChaCha20-Poly1305 :

| Octets | Contenu |
|---|---|
| 0–7 | `LTNE2E01`, en ASCII |
| 8–15 | les 8 octets de l'identifiant de clé |
| 16–39 | le nonce de l'enveloppe : 24 octets aléatoires |
| 40–87 | la clé de fichier scellée par la clé d'enveloppe avec ce nonce, les octets 0–15 comme données additionnelles : 32 octets, puis l'étiquette de 16 octets |
| 88– | les morceaux |

Les octets 0–87 forment l'**en-tête**. L'archive est découpée en morceaux
de 65 536 octets, le dernier plus court (une archive vide est un seul
morceau vide). Le morceau *i*, à partir de 0, est scellé par la clé de
fichier avec le nonce de 24 octets formé de 16 octets nuls, de *i* sur 7
octets gros-boutiste, et d'un octet, `01` pour le dernier morceau et `00`
pour les autres, avec l'en-tête comme données additionnelles ; il est
écrit sous la forme de ses octets, puis de son étiquette de 16 octets. La
sauvegarde chiffrée fait 88 + *n* + 16 × (nombre de morceaux) octets pour
une archive de *n* octets. Vecteurs de test : `vectors/encrypted-saves.json`.

- Un lecteur MUST refuser une sauvegarde dont l'identifiant de clé n'est
  pas celui de sa clé, dont l'en-tête ou un morceau ne s'ouvre pas, dont le
  dernier morceau n'est pas marqué comme dernier, ou qui continue après
  lui, et n'en rien restaurer. [L-9.4-1] Un morceau coupé, déplacé,
  supprimé ou ajouté ne passe ainsi jamais inaperçu.
- Un client MUST NOT envoyer la clé de sauvegarde, une clé de fichier, la
  clé d'enveloppe ou la phrase de récupération à aucun serveur ni pair : de
  la clé, seul son identifiant quitte l'appareil. [L-9.4-2]
- Un client MUST créer une nouvelle clé de fichier et un nouveau nonce
  d'enveloppe, à partir d'une source d'aléa sûre, pour chaque sauvegarde.
  [L-9.4-3] Celui qui reprend un envoi (§ 9.3) garde l'en-tête qu'il a créé
  et chiffre de nouveau vers les mêmes octets, sans conserver le fichier
  chiffré.

**L'envoyer.** Comme toute sauvegarde (§ 9.2, § 9.3), avec son
`encryption`, `{"scheme": "lantern-save-e2e-1", "key_id":
"0a1b2c3d4e5f6071"}`, dans le document de l'envoi (§ 9.3), ou dans l'en-tête
`Lantern-Save-Encryption: lantern-save-e2e-1; key_id=0a1b2c3d4e5f6071`
d'une requête du § 9.2. `size`, `sha256`, `Content-Digest` et
`Repr-Digest` sont ceux des octets chiffrés, tels que le serveur les
conserve.

- Un serveur qui propose cette famille MUST conserver les octets d'une
  sauvegarde chiffrée tels qu'envoyés, la lister avec son `encryption`, et
  ne pas exiger d'elle ce qu'il vérifie d'une archive en clair, comme
  d'être un zip. [L-9.4-4] Il MAY vérifier que les octets commencent par
  `LTNE2E01` et l'identifiant de clé des métadonnées, et répondre `400`
  sinon.
- Un serveur qui ne la propose pas MUST répondre `400` à une sauvegarde
  envoyée avec un `encryption`, plutôt que de la conserver comme une
  archive. [L-9.4-5]
- Le titre, `kind`, `slot`, `game_version_code`, `profile`, `note`,
  `device`, les dates et les tailles restent en clair : le serveur en a
  besoin pour lister et conserver les sauvegardes. Un client SHOULD omettre
  `profile` et `note` d'une sauvegarde chiffrée, sauf si son utilisateur
  veut qu'ils soient affichés. [L-9.4-6]

**Transporter la clé.** L'utilisateur fait passer la clé d'un appareil à
l'autre sous l'une de deux formes des mêmes 35 octets : les 32 octets de la
clé, puis les 3 premiers octets de SHA-256(`lantern-save-key` ‖ la clé),
écrits dans l'alphabet de l'appairage (§ 5.2), 5 bits par symbole, les plus
significatifs d'abord : 56 symboles, affichés en 14 groupes de 4.

- Une **phrase de récupération**, que l'utilisateur note et saisit sur
  l'autre appareil : `7KQ2-MZ4P-…`. Des symboles plutôt que des mots : rien
  à traduire dans les langues qu'affiche une console, pas de liste de 2048
  mots à embarquer dans un homebrew, l'alphabet que l'utilisateur saisit
  déjà à l'appairage, sans `0`, `O`, `1` ni `I`, et un contrôle de 24 bits
  qui détecte un symbole mal saisi. Un lecteur ignore la casse, les espaces
  et les tirets.
- Un **QR code** : `LANTERN-SAVE-KEY-1:` suivi des 56 symboles, qui
  tiennent dans le mode alphanumérique du QR code, pour qu'un appareil muni
  d'une caméra le scanne.

- Un client MUST refuser une phrase ou un QR code dont le contrôle ne
  correspond pas, et le dire avant toute autre chose. [L-9.4-7]
- Un client MUST n'afficher la phrase ou le QR code que lorsque son
  utilisateur le demande, sur son propre écran. [L-9.4-8] Il SHOULD
  demander à l'utilisateur de noter la phrase quand il crée la clé.
  [L-9.4-9] Il conserve la clé là où son système protège les clés, comme
  une clé d'appareil (§ 5.4).

**Ce qui est perdu.** Le serveur ne peut plus montrer ce que contient une
sauvegarde, vérifier que c'est un zip, ni ne garder qu'une copie de deux
sauvegardes de la même partie : la même archive donne d'autres octets à
chaque fois. Personne ne peut rendre une sauvegarde à un utilisateur qui a
perdu à la fois sa clé et sa phrase. Le serveur voit toujours de quel titre
il s'agit, quand, quelle taille et depuis quel appareil ; il peut supprimer
une sauvegarde, en retenir une, ou en rendre une plus ancienne : la clé
protège ce que contient une sauvegarde, pas sa présence.

## 10. Codes de triche (fonctionnalité `cheats`)

- `GET <base>/v1/cheats?platform=&title_id=&build_id=` →
  `{"schema":1, "cheats":[Set…]}`, où un lot est
  `{"id":"cs_…", "platform":"switch", "title_id":"0100ABCD00010000",
  "build_id":"4A1B2C3D4E5F6071", "source":"Community list",
  "note":"Endless lamp oil", "updated":"2026-10-29T21:00:00Z",
  "size":512, "sha256":"…"}`. Un build peut avoir plusieurs lots, de
  plusieurs sources. Les filtres MUST garder ces lots et aucun autre.
  [L-10-1]
- `build_id` : le build du jeu auquel le lot est destiné, sous la forme du
  profil (annexe A), sur les plateformes dont les codes de triche en
  dépendent ; absent ailleurs.
- `GET <base>/v1/cheats/{id}` → le texte du lot, sous forme de fichier
  (§ 6.6), dans le format propre à la plateforme et d'au plus 1 Mio, que le
  client écrit là où le dit le profil (annexe A). Un identifiant inconnu
  MUST donner `404`. [L-10-2]
- Avec la portée `cheats.write`, un serveur MAY accepter
  `POST <base>/v1/cheats` ainsi que `PUT` et `DELETE
  <base>/v1/cheats/{id}` ; le corps de `POST` et de `PUT` est
  `{"schema":1, "platform", "title_id", "build_id", "source", "note",
  "text"}`. `POST` répond `201` avec le nouveau lot (`{"schema":1,
  "id":…}`, tel que listé), `PUT` et `DELETE` `204`. Un `POST` d'un lot qui
  existe (même plateforme, même titre, même build et même source) répond
  `409` `conflict` : `PUT` le remplace. Un serveur qui ne les accepte pas
  répond `405`. Un serveur qui les accepte MUST répondre ainsi. [L-10-3]
  Sans la portée, l'écriture MUST être refusée (`401`, `403` ou `405`).
  [L-10-4]

## 11. Demandes (fonctionnalité `requests`)

- `GET <base>/v1/requests` → `{"schema":1, "requests":[{"id", "platform",
  "title_id", "name", "status", "created"}…]}` : celles du compte lui-même,
  de la plateforme nommée (§ 4.3). `status` : `open`, `done` ou `declined`.
- `POST <base>/v1/requests` `{"schema":1, "platform":"switch",
  "title_id":"…"}` → `201` avec la nouvelle demande (`{"schema":1,
  "id":…}`, telle que listée), ou `200` avec la demande ouverte pour le
  même titre. `platform` vaut par défaut celle du client (§ 4.3). Un
  serveur MUST répondre ainsi. [L-11-1]
- `DELETE <base>/v1/requests/{id}` : le compte retire sa propre demande,
  quel que soit son statut. Un serveur MUST répondre `204`, et `404` pour la
  demande d'un autre compte ou une demande inconnue. [L-11-2]
- Chaque appareil du compte lit les mêmes demandes ; l'événement `request`
  (§ 18.2) leur dit quand une demande est créée, change de statut ou est
  retirée.

## 12. Erreurs

Toute erreur MUST être du `application/problem+json` (RFC 9457) avec un vrai
code d'état, jamais `2xx`. [L-12-1]

```json
{"schema": 1, "type": "https://lantern.boreale.dev/errors/account-frozen",
 "title": "Account frozen", "status": 403, "code": "account_frozen",
 "detail": "Your access is paused until Sunday.", "language": "en"}
```

Son `status` MUST être celui de la réponse, et son `code` l'un de ceux que
le tableau donne pour ce statut. [L-12-2] Son `type` est la page du code,
`https://lantern.boreale.dev/errors/<code, with - for _>`.

| Statut | `code` | Quand |
|---|---|---|
| 400 | `bad_request`, `key_required` | Une requête ou un corps mal formés ; un curseur ou un jeton `since` que le serveur n'a jamais donné ; une plateforme manquante là où il en faut une ; un appairage sans clé d'appareil, sur un serveur qui ne délivre que des jetons liés (§ 5.4) |
| 401 | `unauthorized`, `signature_required`, `signature_invalid`, `signature_expired`, `signature_replayed` | Pas de jeton là où il en faut un, ou un jeton inconnu, révoqué ou expiré (avec `WWW-Authenticate: Bearer`) ; un jeton lié sans signature (§ 5.4) ; une signature qui ne se vérifie pas ou n'a pas la forme que donne le § 5.4 ; le `created` d'une signature hors de la fenêtre du serveur ; le `nonce` d'une signature déjà vu |
| 403 | `forbidden`, `account_frozen` | Une portée manquante ; un compte gelé ; l'autorisation d'un pair absente ou non valide (§ 19.4) ; l'`installed` d'un autre appareil (§ 20.4) |
| 404 | `not_found` | |
| 405 | `bad_request` | Une méthode que la route n'accepte pas (avec `Allow`) |
| 409 | `conflict` | Le décalage d'un envoi qui n'est pas celui du serveur (avec `Upload-Offset`) ; un lot de codes de triche ou un compte qui existe déjà (§ 10, § 5.7) ; un compte qui ne peut pas être supprimé (§ 5.7) ; une écriture de synchronisation d'une autre génération (§ 20.4) |
| 410 | `gone` | Un curseur, un jeton `since`, un identifiant d'événement, une révision de synchronisation, un appairage, une invitation ou un identifiant de fichier expirés |
| 412 | `precondition_failed` | Une écriture de synchronisation dont le `If-Match` n'est pas celui de la collection (§ 20.4) |
| 413 | `too_large` | Une sauvegarde ou un morceau au-delà de la limite du serveur ; une collection de synchronisation pleine (§ 20.5) |
| 416 | `bad_request` | Une plage hors du fichier (avec `Content-Range: bytes */<size>`) |
| 422 | `unsupported_schema`, `digest_mismatch` | Un document de requête d'un schéma que le serveur ne sait pas lire ; un corps dont le SHA-256 n'est pas celui annoncé |
| 429 | `slow_down` | Trop de requêtes, de tentatives d'appairage, d'interrogations, de flux d'événements ou de téléchargements depuis un pair (avec `Retry-After`) |
| 500 | `internal` | Une défaillance du serveur lui-même ; le client peut réessayer plus tard |
| 503 | `unavailable` | Analyse en cours, maintenance (avec `Retry-After`) |

- Une route inconnue MUST donner `404` `not_found`. [L-12-3]
- `title` et `detail` sont destinés aux personnes, dans la langue
  `language` (§ 2.2) ; un client les affiche bornés et sans caractères de
  contrôle, et n'agit que d'après `status` et `code`.
- De nouveaux codes MAY venir avec des versions ultérieures de ce texte :
  un client qui reçoit un `code` qu'il ne connaît pas MUST agir d'après le
  seul statut. [L-12-4]

## 13. Limites

Un client MUST borner ce qu'il lit. [L-13-1] Un serveur MUST rester dans
ces limites : [L-13-2]

| Élément | Au plus |
|---|---|
| Un document JSON | 32 Mio, profondeur d'imbrication 16 |
| Un champ de texte | 4 Kio (`name` 512 octets, `note` 120 octets, `profile` 64 octets) |
| Une page | 1000 éléments |
| Titres lus à la fois | 100 |
| Un manifeste | 4096 fichiers, chaque chemin 1024 octets |
| Les `packages` d'un homebrew | 16 |
| Les `tags` d'un titre ou d'un homebrew | 32, de 64 octets chacun |
| Les `requires_data` d'un portage | 256 fichiers, chaque liste `accept` 32 |
| Un lot de codes de triche | 1 Mio |
| Un datagramme de découverte | 1200 octets |
| `Signature-Input`, `Signature` | 1 Kio chacun |
| Les `data` d'un événement (§ 18) | 4 Kio |
| Les `mirrors` d'un fichier (§ 19.2) | 8 |
| Une autorisation (§ 19.3) | 1 Kio |
| Une écriture de synchronisation (§ 20.4) | 1000 éléments ; une collection `limits.sync_items`, 100 000 au plus |

Un serveur MUST refuser un document de requête qui dépasse ces limites, ou
ses propres limites plus basses, avec `400` ou `413`, sans jamais défaillir
à cause de lui. [L-13-3]

## 14. Mise en cache

Chaque `GET` qui renvoie du JSON SHOULD porter un `ETag` et honorer
`If-None-Match` avec `304`. [L-14-1] Les réponses aux appels authentifiés
SHOULD porter `Cache-Control: private` et `Vary: Authorization` ; les
réponses qui dépendent de la plateforme ou de la langue varient aussi selon
`Lantern-Platform` et `Accept-Language`, et les réponses compressées selon
`Accept-Encoding` (§ 2.1). [L-14-2]

## 15. Sécurité et vie privée

- Aucun identifiant matériel, aucun en-tête de pistage. Un serveur ne
  connaît un appareil que par le nom que son utilisateur lui a donné
  pendant l'appairage, et le profil d'une sauvegarde que par le nom que son
  utilisateur lui a donné.
- Aucun mot de passe ne transite par l'appareil : il détient un jeton par
  serveur, que l'utilisateur peut révoquer depuis le serveur (§ 5), lié à
  une clé que l'appareil a créée (§ 5.4).
- Aucun chiffrement propriétaire des documents : TLS les protège, avec une
  clé épinglée à l'appairage quand aucune autorité ne la garantit (§ 5.3).
  Les sauvegardes peuvent être chiffrées sur l'appareil, par une
  construction ouverte dont le serveur ne voit jamais la clé (§ 9.4).
- Rien de ce que contient une console n'en sort pour la synchronisation
  sans le consentement de son utilisateur, et l'utilisateur supprime ce que
  conserve le serveur (§ 20).
- Un fichier pris sur un miroir ou un pair est vérifié comme s'il venait du
  serveur ; un pair ne sert que des fichiers, par leur empreinte, aux
  détenteurs d'une autorisation (§ 19).
- La découverte est une indication, jamais une preuve (§ 4.1).
- Un serveur ne peut pas changer les réglages d'un client ni ajouter
  d'en-têtes à ses requêtes ultérieures.
- Un client vérifie le SHA-256 d'un téléchargement avant de l'installer
  (§ 6.6), et la signature d'un homebrew quand il en a une (§ 8.4).
- Un homebrew n'écrit que les fichiers de son manifeste, sous les racines
  du profil, et rien hors des racines qui n'exigent pas de consentement
  sans l'accord de l'utilisateur (§ 8.3).
- Un serveur ne sert jamais les données qu'un portage tire de la propre
  copie du jeu de l'utilisateur (§ 8.6).
- Aucun identifiant de connexion ne va à une adresse externe (§ 7.1).
- Les serveurs sont faits pour les propres jeux de l'utilisateur.

## 16. Modèle de menaces

Ce contre quoi Lantern protège, et ce qu'il laisse à d'autres. Chaque
menace nomme les règles qui y répondent.

**Un réseau hostile** (le Wi-Fi d'un café, un réseau local avec un intrus,
une réponse DNS ou de découverte falsifiée, quelqu'un qui enregistre le
trafic).

- Protégé : TLS partout, HTTP en clair sur le bouclage seulement (§ 2) ; la
  clé d'un serveur du réseau local comparée par l'utilisateur et épinglée à
  l'appairage, une clé qui change refusée (§ 5.3) ; la découverte, une
  indication à laquelle on ne se fie jamais (§ 4.1) ; jetons et
  signatures envoyés seulement à l'origine du serveur (§ 2) ; des requêtes
  signées avec un nonce et une heure, pour qu'une requête enregistrée ne
  soit jamais acceptée deux fois (§ 5.4) ; chaque fichier vérifié par
  rapport à son SHA-256, le même dans le document et dans `Repr-Digest`
  (§ 6.6).
- Non protégé : un premier appairage où l'utilisateur ne compare pas les
  empreintes ; ce que révèlent les tailles et les horaires du trafic (quel
  jeu a été téléchargé) ; un réseau qui coupe la connexion.

**Un serveur malveillant ou compromis.**

- Protégé : un client n'écrit que les chemins d'un manifeste, sous les
  racines du profil, et demande avant toute racine qui exige un
  consentement (§ 8.2, § 8.3) ; la signature d'un auteur, dont la clé est
  épinglée par homebrew, est vérifiée quoi que dise le serveur, si bien
  qu'un serveur ne peut pas contrefaire la mise à jour d'un auteur
  (§ 8.4) ; un homebrew ne peut pas s'approprier l'identifiant système d'un
  autre (§ 8.3) ; les données d'un portage ne sont jamais récupérées sur le
  réseau (§ 8.6) ; un serveur ne peut pas changer les réglages d'un client
  (§ 15) ; les identifiants de connexion ne vont jamais à des adresses
  externes (§ 7.1) ; chaque document est borné (§ 13) et lu selon la règle
  du `schema` (§ 3.2).
- Non protégé : les jeux et les homebrews non signés sont ce que le serveur
  dit qu'ils sont : ne les installez que depuis un serveur auquel vous faites
  confiance. Un serveur voit ce que demandent ses clients, peut retenir une
  mise à jour ou mentir sur la fiche d'un jeu ou ses classifications (un
  plafond de classification se fie aux classifications du serveur, § 5.6),
  et conserve les sauvegardes telles qu'elles sont envoyées.

**Un jeton ou un appareil volé.**

- Protégé : un jeton lié à la clé de son appareil ne sert à rien sans elle
  (§ 5.4) ; chaque appareil a son propre jeton, que l'utilisateur révoque
  depuis la page du serveur ou une application d'administration (§ 5.1,
  § 5.7) ; le serveur ne garde que des empreintes des jetons (§ 5.1) ; les
  portées et un plafond de classification limitent ce que peut faire un
  jeton (§ 5.1, § 5.6) ; une adresse d'interrogation qui fuit ne donne rien
  (§ 5.4).
- Signatures contrefaites : une clé ou un R d'ordre faible, ou une
  signature encodée de façon non canonique, est refusée avant l'équation
  de vérification, par tout vérificateur, et une clé d'appareil d'ordre
  faible l'est à l'appairage (§ 8.4, § 5.4) : avec elles, l'équation seule
  accepte une contrefaçon pour environ un message sur 8, pour les requêtes
  comme pour les homebrews.
- Non protégé : un appareil volé détient sa clé et son jeton jusqu'à ce que
  l'utilisateur le révoque ; un jeton porteur seul, qu'un serveur peut
  refuser (§ 5.4), fonctionne pour quiconque le copie.

**Un manifeste hostile** (un chemin qui sort de son dossier, un lien, deux
chemins qui ne diffèrent que par la casse, un sysmodule glissé dedans, une
archive plus grande qu'elle ne le dit).

- Protégé : les règles du § 8.2 sur les chemins, et les racines du profil
  (annexe A) ; un client n'écrit que des fichiers, jamais au travers d'un
  lien, et vérifie chacun par rapport à son manifeste (§ 8.3) ; l'empreinte
  d'un manifeste figure dans la signature d'un auteur (§ 8.4) ; les limites
  du § 13 ; les chemins de données d'un portage sont relatifs à son dossier
  de données, que l'utilisateur approuve une fois (§ 8.6).
- Non protégé : ce que fait un homebrew une fois qu'il tourne.

**Un auteur de homebrew malveillant.**

- Protégé : un changement de clé est refusé sauf si l'utilisateur
  l'accepte, après avoir vu les deux empreintes (§ 8.4) ; un identifiant
  système qu'un autre homebrew a installé est refusé (§ 8.3) ; tout chemin
  hors de ses propres dossiers, comme celui d'un sysmodule, est d'abord
  montré à l'utilisateur (§ 8.3) ; ses exigences sont vérifiées avant qu'il
  soit proposé (§ 8.7).
- Non protégé : une signature prouve qui a fait un homebrew, pas qu'il est
  sûr. Lantern n'examine aucun code et ne l'isole pas : c'est le choix de
  l'utilisateur, et celui de la plateforme.

**Une console perdue.**

- Protégé : elle ne détient aucun mot de passe (§ 5.2) ; l'utilisateur
  révoque son appareil depuis le serveur ou une application
  d'administration sur un téléphone (§ 5.7), et son jeton échoue alors
  immédiatement ; ses sauvegardes restent sur le serveur, pour le compte
  (§ 9).
- Non protégé : ce qui se trouve sur le stockage propre de la console (ses
  sauvegardes, ses jeux, sa clé tant qu'elle n'est pas révoquée) : le
  protéger revient à la plateforme.

**Un miroir ou un pair hostile** (un miroir qui sert d'autres octets, une
console du réseau local qui ment, un pair qui répond lentement ou jamais).

- Protégé : chaque fichier venu d'un miroir ou d'un pair est vérifié par sa
  taille et son SHA-256, d'après le document du serveur, avant d'être
  conservé (§ 19.1) ; aucun jeton, aucune signature ni aucun cookie ne leur
  est envoyé (§ 19.1) ; un client s'arrête à la taille annoncée et se
  rabat sur son serveur.
- Non protégé : en HTTP en clair, quiconque observe le réseau voit quel
  fichier va où ; un pair ou un miroir peut refuser de servir, ou servir
  lentement.

**Quelqu'un sur le réseau local, contre un pair** (l'ordinateur portable
d'un invité, une télévision connectée).

- Protégé : un pair ne sert rien sans une autorisation d'un serveur auquel
  il s'est appairé, pour ce fichier précis, valable quelques minutes
  (§ 19.3, § 19.4) ; il ne sert que des apps et des paquets de homebrews
  qu'il détient en entier, par leur empreinte, jamais une sauvegarde, une
  clé, un jeton ni un chemin (§ 19.4) ; il est désactivé tant que son
  utilisateur ne l'active pas, ne répond qu'à ses propres réseaux, et
  limite ses téléchargements et ses requêtes (§ 19.4).
- Non protégé : une autorisation vue sur un réseau en HTTP en clair peut
  être rejouée, pour ce même fichier, jusqu'à son expiration ; la réponse
  de découverte d'un pair révèle au réseau son nom et les uid de ses
  serveurs.

**Un déluge de flux d'événements, ou un flux trop curieux** (§ 18).

- Protégé : chaque jeton détient au plus quelques flux, au-delà desquels un
  serveur répond `429` (§ 18.4) ; un flux ne porte que ce que son appelant
  pourrait lire, selon la portée, le compte, la plateforme et le plafond de
  classification (§ 18.2) ; le flux d'un jeton révoqué se termine à son
  battement de cœur suivant (§ 18.1) ; les événements nomment ce qui a
  changé, jamais les documents, qui se lisent avec les droits du jeton.
- Non protégé : un flux dit à son appelant quand quelque chose qu'il peut
  voir a changé, et donc quand le propriétaire du serveur travaille sur la
  bibliothèque.

**Un serveur curieux, pour ce qu'il garde de l'utilisateur** (§ 9.4, § 20).

- Protégé : rien de ce que contient une console n'en sort pour la
  synchronisation sans le consentement de son utilisateur, donné
  nommément pour `installed` (§ 20.1) ; l'utilisateur supprime ce que garde
  le serveur, immédiatement, et une console endormie ne peut pas le
  remettre (§ 20.3, § 20.5) ; une sauvegarde chiffrée sur l'appareil est
  faite d'octets que le serveur ne peut pas lire, par une clé qu'il ne voit
  jamais (§ 9.4).
- Non protégé : les métadonnées d'une sauvegarde chiffrée (son titre, ses
  dates, ses tailles et son appareil), et ce que garde un serveur tant que
  la synchronisation est active ; un serveur peut supprimer une
  sauvegarde, en retenir une ou en rendre une plus ancienne ; un
  utilisateur qui perd à la fois sa clé de sauvegarde et sa phrase perd ses
  sauvegardes chiffrées.

**Une bibliothèque statique** (§ 21) : ce que contient un hébergeur web ou
une clé USB.

- Protégé : la même chose que face à un serveur malveillant : manifestes,
  racines, empreintes et signatures des auteurs sont vérifiés quelle que
  soit la source (§ 8, § 6.6).
- Non protégé : une bibliothèque statique est publique pour quiconque
  atteint ses fichiers, n'a ni jeton, ni plafond de classification, ni
  appairage ; sur un stockage local, rien ne dit qui l'a écrite.

**Un jeton d'administration volé.**

- Protégé : il est lié à la clé de son appareil comme tout autre (§ 5.4) ;
  une suppression demande le nom du compte et refuse celui de l'appelant
  (§ 5.7).
- Non protégé : quiconque détient l'appareil et la clé d'un administrateur
  peut supprimer d'autres comptes et leurs données : la confirmation
  protège d'une erreur de manipulation, pas d'un attaquant. Réservez la
  portée `admin` à peu d'appareils.

Hors du champ : les droits sur les jeux. Lantern sert les propres jeux d'un
utilisateur et n'impose rien (§ 15).

## 17. Conformité

Une suite de conformité (`conformance/`) s'exécute contre l'URL d'un
serveur, avec ou sans jeton, et vérifie chaque exigence de ce texte qu'elle
peut voir de l'extérieur ; chaque contrôle nomme les identifiants qu'il
couvre. Les règles qu'elle ne peut pas voir (celles d'un client, ou
l'intérieur d'un serveur) sont listées par identifiant sur la
[page de traçabilité](https://lantern.boreale.dev/requirements/) du site.
Avec un jeton, elle n'écrit que ce qu'elle supprime ensuite : des
sauvegardes, un lot de codes de triche, une demande, des éléments de
synchronisation, les appareils qu'elle appaire et les invitations qu'elle
crée, et, avec `--admin-writes`, un compte à elle, qu'elle supprime ensuite
(§ 5.7). Avec `--static`, elle vérifie une bibliothèque statique (§ 21) au
lieu d'un serveur, à une adresse ou dans un dossier ; avec `--peer`, un pair
(§ 19.4). Un serveur de référence (`server/`) sert un dossier de paquets et
de homebrews, l'exporte sous forme de bibliothèque statique, et passe la
suite ; `server/peer.py` est un pair de référence.

**Niveaux.** Une implémentation est conforme à un niveau :

| Niveau | Contenu |
|---|---|
| `Lantern Core` | Transport, versions et poignée de main (§ 2–4) ; jetons, appairage et requêtes signées quand elle délivre des jetons (§ 5.1–5.4) ; la bibliothèque, ce qui manque, les changements et les sections quand ils sont proposés, et les fichiers (§ 6) ; erreurs, limites et mise en cache (§ 12–14) |
| `+titles` | Titres (§ 7) |
| `+homebrew` | Homebrews, paquets, manifestes, signatures, portages et exigences (§ 8) |
| `+saves` | Sauvegardes (§ 9) |
| `+cheats` | Codes de triche, et leur écriture quand elle est proposée (§ 10) |
| `+requests` | Demandes (§ 11) |
| `+admin` | Administration, invitations, plafonds de classification et suppression de comptes (§ 5.5–5.7) |
| `+events` | Événements : le flux, l'interrogation longue et leurs limites (§ 18) |
| `+peers` | Autorisations et miroirs (§ 19.2, § 19.3) ; avec `--peer`, le profil du pair (§ 19.4) |
| `+sync` | Synchronisation : collections, règle de fusion, suppression (§ 20) |
| `+encrypted_saves` | Sauvegardes chiffrées de bout en bout conservées telles qu'envoyées (§ 9.4) |
| `Lantern Static` | Une bibliothèque statique : son organisation, ses documents et ses fichiers (§ 21), sans les routes d'un serveur |

La suite affiche les niveaux qu'atteint un serveur : un niveau est atteint
quand sa famille est proposée à l'appelant, qu'aucun de ses contrôles
n'échoue, et qu'aucun n'a été laissé de côté faute de jeton ou de portée
(exécutez-la avec un jeton qui détient toutes les portées, et anonymement
sur un serveur public). Chaque niveau d'un serveur exige `Lantern Core` ;
`Lantern Static` est à part, pour une bibliothèque statique lue avec
`--static`.

**Le nom.** Seule une implémentation qui passe la suite à un niveau peut se
dire « Lantern compatible » et afficher le badge, avec ce niveau et la
version du texte : « Lantern compatible 0.5 · Core +titles ». Les badges et
le registre des implémentations sont
[sur le site](https://lantern.boreale.dev/conformance/) ; une
implémentation rejoint le registre par une pull request accompagnée de son
rapport.

**Vecteurs de test** (`vectors/`), pour les bibliothèques de clients et de
serveurs : requêtes signées (§ 5.4), signatures de homebrews (§ 8.4),
empreintes SPKI (§ 5.3), chemins (§ 8.2), `version_code` par profil
(annexe A), exigences (§ 8.7), plafonds de classification (§ 5.6),
sauvegardes chiffrées et phrases de récupération (§ 9.4), autorisations
(§ 19.3), règle de fusion de la synchronisation (§ 20.4) et organisation
statique (§ 21.1), chaque cas avec ce que décide un lecteur.

## 18. Événements (fonctionnalité `events`)

Ce qui a changé, poussé par le serveur au moment où cela arrive, pour qu'un
client en arrière-plan (le homebrew d'une console pendant que son
utilisateur joue, une intégration domotique comme boreale-ha) l'apprenne
sans relire la bibliothèque encore et encore. Deux voies portent les mêmes
événements : un flux (18.1), et l'interrogation longue (18.3) pour un client
qui ne peut pas garder une connexion ouverte. L'annexe B.10 dit comment une
console et une intégration domotique s'en servent.

### 18.1 Le flux

`GET <base>/v1/events`, avec `Accept: text/event-stream`, répond `200`
avec `Content-Type: text/event-stream` et `Cache-Control: no-store`, et
garde la réponse ouverte : des Server-Sent Events, tels que les définit le
standard HTML du WHATWG.

```text
retry: 5000

id: s_9f2c01aa_1042
event: ready
data: {"schema":1}

: heartbeat

id: s_9f2c01aa_1043
event: request
data: {"schema":1,"id":"r_7Qm2","platform":"switch","title_id":"0100ABCD00010000","status":"done"}
```

- L'`id` de chaque événement est un jeton de `GET <base>/v1/changes`
  (§ 6.4) : le flux et `changes?since=` partagent leurs jetons. Un serveur
  MUST donner à chaque événement un `id` qu'accepte `changes?since=`, et qui
  reprend juste après cet événement. [L-18.1-1]
- Un flux MUST commencer par un champ `retry`, les millisecondes qu'un
  client attend avant de se reconnecter, puis un événement `ready` dont
  l'`id` est le jeton à partir duquel il part : celui que le client a
  donné, ou le jeton courant. [L-18.1-2] Un client qui s'est connecté sans
  jeton apprend ainsi où il en est.
- Un client reprend avec `Last-Event-ID: <token>`, ou `?since=<token>`
  quand il ne peut pas poser l'en-tête (la requête l'emporte). Le serveur
  MUST alors envoyer, après `ready`, chaque événement postérieur à ce jeton
  que l'appelant peut voir, dans l'ordre, puis les nouveaux à mesure qu'ils
  arrivent. [L-18.1-3] Un jeton trop ancien pour le serveur MUST donner
  `410` `gone`, et un jeton qu'il n'a jamais donné `400` (ou `410`, comme
  pour `since`, § 6.4), avant que le flux ne commence. [L-18.1-4] Le client
  relit alors ce qu'il affiche (la bibliothèque, ses demandes) et se
  connecte sans jeton.
- `data` est une ligne de JSON, un document avec son `schema` (§ 3.2). Un
  lecteur MUST ignorer un événement dont il ne connaît pas l'`event`, et un
  événement dont le document est d'un `schema` plus récent. [L-18.1-5]
- Un serveur MUST écrire une ligne de commentaire (`:` suivi de n'importe
  quoi) ou un événement au moins toutes les `limits.heartbeat` secondes,
  pour que le client, et les mandataires entre eux, voient le flux en vie.
  [L-18.1-6] Un client qui n'entend rien pendant deux fois cette durée se
  reconnecte.
- Un serveur MUST NOT appliquer de `Content-Encoding` à un flux : chaque
  événement part dès qu'il est écrit. [L-18.1-7]
- La requête est authentifiée, et signée quand son jeton est lié (§ 5.4),
  une fois, à l'ouverture du flux. Un serveur MUST terminer le flux d'un
  jeton révoqué, ou d'un compte gelé ou supprimé, au plus tard à son
  battement de cœur suivant (§ 5.7). [L-18.1-8] Un serveur MAY terminer
  n'importe quel flux quand il le veut, au bout d'une heure par exemple :
  le client se reconnecte avec le dernier `id` qu'il a lu.
- Un client MUST attendre au moins `retry` avant de se reconnecter, et
  espacer ses tentatives comme le dit l'annexe B.2 tant que la connexion
  échoue. [L-18.1-9]

### 18.2 Les événements

| `event` | Qui le reçoit | `data` |
|---|---|---|
| `ready` | Chaque flux | `{"schema":1}` : le flux commence (18.1). |
| `library` | Portée `library` | `{"schema":1, "families":["apps","titles","homebrew","cheats"], "platforms":["switch"]}` : quelque chose de ces familles a changé sur ces plateformes. Le client relit leurs changements (§ 6.4, § 7.3) ou leurs listages. |
| `request` | Portée `requests` : les demandes du compte lui-même | `{"schema":1, "id", "platform", "title_id", "status"}` (§ 11) ; `"deleted": true` à la place de `status` quand elle a été retirée. |
| `pairing` | Portée `admin` | Un appairage en attente d'approbation, tel que le liste le § 5.7 : `{"schema":1, "id", "code", "device", "key", "expires"}`. |
| `save` | Portée `saves` : les sauvegardes du compte lui-même | Une sauvegarde conservée : `{"schema":1, "platform", "title_id", "save_id", "created", "device"}` (§ 9). |
| `sync` | Portée `sync.read` : celles du compte lui-même | `{"schema":1, "collection":"wishes", "rev":42}` : une collection a changé (§ 20). |
| `shutdown` | Chaque flux | `{"schema":1, "retry":30}` : le serveur s'arrête ; le client se reconnecte au moins `retry` secondes plus tard. |

- Un serveur MUST n'envoyer à un appelant que les événements de ce qu'il
  pourrait lire avec son jeton : de ses portées et de son compte, de sa
  plateforme quand il en a nommé une (`Lantern-Platform` ou `?platform=`,
  § 4.3), et dans les limites de son plafond de classification (§ 5.6).
  [L-18.2-1] Un événement `library` ne nomme que les familles et les
  plateformes dont l'appelant voit un changement ; un changement qu'il ne
  peut pas voir ne lui donne aucun événement.
- Un serveur SHOULD envoyer `shutdown` à chaque flux avant de s'arrêter
  volontairement. [L-18.2-2]
- Un événement dit ce qui a changé, jamais les documents : le client les
  lit sur leurs routes, selon leurs propres règles, et les `data` d'un
  événement restent petites (§ 13). Une version ultérieure peut ajouter des
  événements.

### 18.3 Interrogation longue

`GET <base>/v1/changes?since=<token>&wait=<seconds>` : les mêmes
événements, pour un client qui ne peut pas garder un flux ouvert (une
console qui se met en veille, un mandataire qui coupe les réponses
longues).

- Avec `wait`, un serveur MUST répondre dès qu'un événement que l'appelant
  peut voir survient après `since`, ou une fois `wait` secondes écoulées, au
  premier des deux ; un `wait` supérieur à `limits.wait` est ramené à cette
  valeur. [L-18.3-1]
- Son document MUST être celui du § 6.4, avec `events` : chaque événement
  postérieur à `since` que le flux enverrait à cet appelant, chacun
  `{"id", "event", "data"}`, dans l'ordre (sauf `ready` et `shutdown`),
  `[]` quand l'attente s'est terminée sans événement ; son `since` reprend
  après le dernier d'entre eux. [L-18.3-2]
- `wait` sans `since`, ou qui n'est pas un entier à partir de 0, MUST
  donner `400`. [L-18.3-3]
- Le client redemande aussitôt avec le nouveau `since` ; il n'attend
  (annexe B.2) qu'après une erreur.

### 18.4 Limites

- Un serveur qui propose `events` MUST donner, dans les `limits` de sa
  poignée de main : `heartbeat`, le nombre maximal de secondes entre deux
  battements de cœur, de 5 à 60 ; `event_streams`, combien de flux un jeton
  peut détenir à la fois (pour un appelant anonyme : une adresse), au moins
  1 ; et `wait`, l'attente la plus longue d'une interrogation longue, de 30
  à 300 secondes. [L-18.4-1]
- Au-delà d'`event_streams`, un serveur MUST répondre `429` `slow_down`,
  avec un `Retry-After` d'au plus `heartbeat` secondes : d'ici là, il a vu
  si un flux plus ancien du jeton écoute encore. [L-18.4-2]
- Un client SHOULD détenir un seul flux par serveur, et aucun tant qu'il
  n'a rien à montrer de ce que disent les événements. [L-18.4-3]

## 19. Miroirs et pairs (fonctionnalité `peers`)

Un fichier, c'est son SHA-256 (§ 6.6, annexe B.5) : quiconque sert ses
octets sert le fichier, et un client les vérifie de la même façon d'où
qu'ils viennent. Un client peut donc prendre un fichier de sa bibliothèque
quelque part de plus proche que son serveur : un **miroir** que nomme le
serveur, ou un **pair**, une console appairée sur le même réseau qui le
détient déjà. Seuls des fichiers passent par là, par leur empreinte : des
apps et des paquets de homebrews, jamais une sauvegarde, un document, ni
rien qui soit désigné par un chemin.

### 19.1 Ce que vérifie un client, quelle que soit la source

- Un client MUST vérifier la taille et le SHA-256 de ce qu'un miroir ou un
  pair a servi par rapport au document de son serveur (celui de l'app, ou
  celui du paquet) avant d'en conserver ou d'en installer quoi que ce soit,
  en traitant miroirs et pairs comme non fiables : rien de ce qu'ils disent
  (une taille, un en-tête, une redirection, un document) ne décide de quoi
  que ce soit. [L-19.1-1]
- Un client MUST NOT envoyer à un miroir ou à un pair son jeton, ses
  signatures, un cookie ni aucun identifiant de connexion de son serveur
  (§ 2) ; un pair reçoit une autorisation, et rien d'autre (§ 19.3).
  [L-19.1-2]
- Un client SHOULD cesser de lire une source dès qu'elle a donné plus
  d'octets que la taille, et prendre le fichier sur son serveur quand ce
  qu'a donné une source échoue à sa vérification. [L-19.1-3]

### 19.2 Miroirs

Une app (§ 6.1) ou un paquet de homebrew (§ 8.2) MAY porter `mirrors`, au
plus 8 autres adresses des mêmes octets : `[{"url":
"https://mirror.example.org/frostline.nsz"}]`.

- L'`url` d'un miroir est absolue, en `https`, ou en `http` pour une
  adresse d'un réseau privé : `10.0.0.0/8`, `172.16.0.0/12`,
  `192.168.0.0/16`, `fc00::/7` ou `fe80::/10`. Un client MUST NOT lire un
  miroir en HTTP en clair à une autre adresse. [L-19.2-1]
- Un serveur MUST ne nommer comme miroir qu'une adresse qui sert exactement
  les octets du fichier, et n'y mettre aucun de ses jetons. [L-19.2-2]
- Un client lit un miroir comme un fichier (§ 6.6), avec `Range` pour
  reprendre. Un miroir est une indication : un client peut l'ignorer, et
  prend le fichier sur son serveur quand le miroir échoue.

### 19.3 Autorisations

Un pair ne sert un fichier qu'à un client que son serveur autorise à le
lire. Le serveur le dit par une **autorisation** (grant) : une courte
déclaration, signée par une clé propre au serveur, qu'un pair vérifie sans
rien demander à personne.

`GET <base>/v1/grants/sha256/{hex}`, avec la portée `library` →

```json
{"schema": 1, "sha256": "3a7bd3e2…", "size": 734003200,
 "grant": "eyJleHAiOjE3OTMzNDYwMDAsInB1cnBvc2UiOi…Iq9k",
 "expires": "2026-10-30T09:40:00Z"}
```

- Le serveur MUST répondre `200` avec une autorisation seulement pour un
  fichier qu'il servirait à l'appelant (selon ses portées et sa
  plateforme, dans les limites de son plafond de classification : § 5.6),
  et `404` sinon, comme pour un fichier qu'il n'a pas. [L-19.3-1]
- Une autorisation s'écrit `<payload>.<signature>`, chacun en base64url
  sans remplissage. Le contenu est formé des octets UTF-8 de l'objet JSON
  `{"exp":<Unix seconds>,"purpose":"lantern-grant-1","sha256":"<hex>","size":<bytes>,"uid":"<server's uid>"}`,
  avec ces clés dans cet ordre et sans espace, `uid` étant celui de la
  poignée de main du serveur (§ 4.2) ; la signature est la signature
  Ed25519 (RFC 8032) de ces octets par la clé d'autorisation du serveur,
  dont la poignée de main donne la clé publique dans `peers.key`. Vecteurs
  de test : `vectors/grants.json`.
- L'`exp` d'une autorisation MUST se situer au plus
  `peers.grant_lifetime` secondes dans le futur, et `peers.grant_lifetime`
  valoir au plus 900. [L-19.3-2] Une autorisation désigne un fichier d'un
  serveur : quiconque la détient peut lire ce fichier sur un pair, comme
  son détenteur le pourrait sur son serveur.
- La clé d'autorisation MUST ne servir qu'aux autorisations et rester sur
  le serveur, sa clé publique, `peers.key`, étant la même pour chaque
  appelant. [L-19.3-3] Un serveur ne la change que si elle fuit : un pair
  refuse alors ses autorisations jusqu'à ce qu'il relise la poignée de
  main.

### 19.4 Pairs

Une console appairée MAY servir aux autres appareils de son réseau les
fichiers de son serveur qu'elle détient : c'est alors un **pair**. Cette
fonction est désactivée tant que son utilisateur ne l'active pas.

Un pair a une seule route, sous un chemin de base qui lui est propre (la
`base` de sa réponse de découverte) : `GET <peer base>/v1/blobs/sha256/{hex}`,
avec `Lantern-Grant: <grant>` → le fichier dont le SHA-256 est `<hex>`,
servi comme le dit le § 6.6 : `Range`, un `ETag` fort, `Repr-Digest`,
`Content-Length`, `Accept-Ranges` ; de même pour `HEAD`.

Un pair MUST :

- ne servir un fichier qu'avec une autorisation qui se vérifie avec la
  `peers.key` du serveur dont elle nomme l'`uid`, un serveur auquel il
  s'est appairé et dont il a lu la poignée de main sur la connexion
  épinglée (§ 5.3), dont l'`exp` n'est pas dépassé selon son horloge et
  dont le `sha256` est celui du chemin, et répondre `403` `forbidden`
  sinon ; [L-19.4-1]
- ne servir que des fichiers qu'il détient en entier, dont il a vérifié la
  taille et le SHA-256 d'après le document de son serveur, et seulement des
  apps et des paquets de homebrews : jamais une sauvegarde, une clé, un
  jeton, un document ni rien qui soit désigné par un chemin ; un fichier
  qu'il ne détient pas donne `404` `not_found` ; [L-19.4-2]
- ne servir que tant que son utilisateur le permet, et seulement aux
  adresses de ses propres réseaux ; [L-19.4-3]
- servir au plus `slots` téléchargements à la fois (sa réponse de
  découverte, de 1 à 8), et quelques requêtes par seconde et par adresse,
  en répondant `429` `slow_down` avec `Retry-After` au-delà ; [L-19.4-4]
- répondre aux erreurs comme le dit le § 12, en `application/problem+json`,
  sans `WWW-Authenticate` : un pair n'accepte aucun jeton. [L-19.4-5]

Un pair parle HTTP en clair sur un réseau privé (les adresses du § 19.2),
ou HTTPS avec un certificat à lui que personne n'épingle : ce qu'il sert
est vérifié par son empreinte, et rien de secret ne lui parvient qu'une
autorisation, valable pour un fichier pendant quelques minutes. Un client
MUST NOT envoyer une autorisation en HTTP en clair à une adresse hors d'un
réseau privé. [L-19.4-6]

### 19.5 Trouver des pairs

- Un client qui cherche des pairs ajoute `"peers": true` à son datagramme de
  découverte (§ 4.1). Un pair ne répond qu'à un tel datagramme, en unicast,
  avec `{"schema":1, "lantern":"peer", "uid":"<the peer's own uid>",
  "name":"Lea's Switch", "port":47116, "base":"/lantern", "tls":false,
  "slots":2, "servers":["6f1c2a8e-…"]}` : `servers` sont les uid des
  serveurs dont il accepte les autorisations, et `tls` dit s'il parle
  HTTPS. Sa réponse MUST avoir cette forme, rester dans les limites du
  § 4.1, et ne venir que d'un pair activé. [L-19.5-1] Un client plus ancien
  que cette version ignore une réponse dont le `lantern` n'est pas
  `server`.
- Un pair MAY aussi s'annoncer par DNS-SD sous `_lantern-peer._tcp`, avec
  les clés TXT `servers=<uid>,…`, `path=<base>`, `v=1` et `tls=0` ou `1`.
- Un client interroge les pairs dont les `servers` contiennent l'`uid` de
  son serveur ; il MAY d'abord demander `HEAD` à un pair, pour voir s'il
  détient le fichier. Une réponse est une indication, comme la découverte
  (§ 4.1).
- Un client SHOULD chercher des pairs au plus une fois par minute, et lire
  un fichier depuis au plus 2 pairs à la fois. [L-19.5-2]

## 20. Synchronisation (fonctionnalité `sync`)

Les souhaits d'un utilisateur, et ce que chacune de ses consoles a
installé, conservés par son serveur pour que toutes ses consoles les
voient, avec les portées `sync.read` et `sync.write`. Les demandes (§ 11)
appartiennent déjà au compte : chaque appareil du compte lit les mêmes, et
l'événement `request` (§ 18.2) leur signale un changement.

### 20.1 Consentement

- Un client MUST demander à son utilisateur avant d'activer la
  synchronisation, en disant quelles collections il envoie et à quel
  serveur, et ne rien lire ni écrire de `<base>/v1/sync` avant son accord.
  [L-20.1-1] La réponse est conservée par profil de console et par
  serveur : une console à plusieurs utilisateurs demande à chacun, et
  synchronise chaque profil avec le compte que son utilisateur a choisi (un
  profil qui veut sa propre synchronisation s'appaire avec son propre
  compte, § 5.2).
- Ce qu'une console a installé MUST NOT en sortir sans un consentement
  donné nommément pour cela : accepter de synchroniser les souhaits ne le
  couvre pas. [L-20.1-2]
- Un client MUST permettre à son utilisateur de désactiver la
  synchronisation ; il cesse alors aussitôt d'envoyer, et propose de
  supprimer ce que conserve le serveur (20.5). [L-20.1-3]

### 20.2 Collections

| Collection | Un élément par | `key` | `value` |
|---|---|---|---|
| `wishes` | Jeu souhaité | `<platform>/<title_id>` | `{"platform", "title_id", "name"?, "note"?}` |
| `installed` | Appareil du compte | L'identifiant de l'appareil, `d_…` (§ 5.7), que `GET <base>/v1/sync` donne à l'appareil | `{"device":"Lea's Switch", "platform":"switch", "apps":[{"app_id", "version_code"}…], "homebrew":[{"id", "build"}…]}` |

Un élément est `{"key", "value", "updated", "rev"}`, ou une suppression,
`{"key", "deleted": true, "updated", "rev"}` :

- `updated` : la date du dernier changement de l'élément, en UTC, à la
  milliseconde (`2026-10-30T09:12:03.250Z`), telle que l'a vue l'appareil
  qui l'a changé, corrigée de son décalage par rapport à la `Date` du
  serveur (annexe B.9) ;
- `rev` : la révision de la collection quand le serveur a accepté le
  changement, un entier qui croît à chaque changement de la collection.

Une version ultérieure peut ajouter des collections : un lecteur ignore
celle qu'il ne connaît pas.

### 20.3 Lecture

`GET <base>/v1/sync` (portée `sync.read`) → `{"schema":1,
"generation":"g_4Rz1", "device":"d_3f9a1c07b2e455d0",
"collections":{"wishes":{"rev":42, "items":12}, "installed":{"rev":7,
"items":2}}}` : ce que conserve le compte ; `device`, la clé propre de
l'appelant dans `installed`.

`GET <base>/v1/sync/{collection}?since=<rev>&page_size=&cursor=` →
`{"schema":1, "collection":"wishes", "generation":"g_4Rz1", "rev":42,
"items":[Item…], "next":null}`, une page comme au § 6.2 : avec `since`, les
éléments changés après cette révision, suppressions comprises ; sans lui,
tous les éléments sauf les suppressions. `rev` est celle de la collection
au moment où sa première page a été lue.

- Un serveur MUST donner, après `since`, chaque élément dont la `rev` est
  supérieure, suppressions comprises, ou répondre `410` `gone` quand il ne
  conserve plus les suppressions aussi loin en arrière ; le client relit
  alors la collection en entier. [L-20.3-1]
- `generation` ne change que quand les données de synchronisation du
  compte sont supprimées (20.5). Un client qui lit une autre `generation`
  que celle qu'il a gardée MUST NOT réécrire ses propres éléments : il
  abandonne sa copie de l'état de synchronisation, désactive la
  synchronisation et redemande l'accord de son utilisateur (20.1).
  [L-20.3-2] Ainsi, une console en veille pendant que son utilisateur
  supprimait ses données ne peut pas les faire revenir.

### 20.4 Écriture et conflits

`PATCH <base>/v1/sync/{collection}` (portée `sync.write`), `{"schema":1,
"generation":"g_4Rz1", "items":[{"key", "value", "updated"} or {"key",
"deleted": true, "updated"}…]}` → `200` `{"schema":1, "collection",
"generation", "rev", "items":[…]}` : chaque élément envoyé, tel que le
serveur le conserve alors, avec sa `rev`.

La règle de fusion, élément par élément, la même sur tous les serveurs :

1. De l'élément qu'a le serveur et de celui envoyé, le serveur garde celui
   dont l'`updated` est le plus tardif.
2. À `updated` égal, une suppression l'emporte ; entre deux valeurs, celle
   dont le JSON canonique (clés triées, sans espace, caractères non ASCII
   tels quels, en UTF-8) est la plus grande chaîne d'octets.
3. Un élément qu'il garde prend la `rev` suivante de la collection ; un
   élément qu'il ne garde pas reçoit pour réponse l'élément tel que le
   serveur l'a.

Ainsi, deux consoles qui changent deux éléments ne perdent jamais le
changement de l'autre, et deux consoles qui changent le même élément
aboutissent au même résultat, quel que soit l'ordre dans lequel arrivent
leurs changements. Vecteurs de test : `vectors/sync-merge.json`.

- Un serveur MUST fusionner selon ces règles, élément par élément, et
  répondre pour chaque élément envoyé tel qu'il le conserve alors.
  [L-20.4-1]
- Un serveur MUST prendre un `updated` de plus de `auth.skew` secondes en
  avance sur son horloge comme sa propre heure : une console dont
  l'horloge avance ne peut pas gagner tous les conflits à venir. [L-20.4-2]
- `If-Match: "<generation>-<rev>"`, ceux de la collection tels qu'une
  lecture les a donnés, rend une écriture tout ou rien : quand la
  collection a changé depuis, un serveur MUST ne rien changer et répondre
  `412` `precondition_failed`. [L-20.4-3] Un client l'envoie quand il a
  écrit ses éléments à partir de la collection entière, et laisse la règle
  fusionner sinon.
- Un serveur MUST refuser une écriture d'une autre `generation` que la
  sienne avec `409` `conflict` : les données ont été supprimées depuis.
  [L-20.4-4]
- Dans `installed`, un appareil MUST ne pouvoir écrire que son propre
  élément : un serveur répond `403` `forbidden` à une écriture d'une autre
  clé. [L-20.4-5]
- Un serveur MUST répondre `400` à un élément dont la `key` ou la `value`
  n'a pas la forme de sa collection (une clé de `wishes` est une plateforme
  et un identifiant de titre des § 4.3 et § 6.1), ou dont l'`updated`
  n'est pas une telle date. [L-20.4-6]

### 20.5 Suppression et conservation

- `DELETE <base>/v1/sync/{collection}`, et `DELETE <base>/v1/sync` pour
  toutes les collections (portée `sync.write`) → `204`. Un serveur MUST
  effacer ces éléments, suppressions comprises, immédiatement, et donner au
  compte une nouvelle `generation`. [L-20.5-1] Ses autres appareils
  l'apprennent à leur lecture suivante (20.3), et par l'événement `sync`.
- Un serveur MUST conserver une suppression au moins 30 jours, pour qu'un
  appareil qui se synchronise une fois par mois l'apprenne. [L-20.5-2]
- Un serveur MUST effacer les données de synchronisation d'un compte qu'il
  supprime (§ 5.7). [L-20.5-3]
- Un serveur SHOULD donner `limits.sync_items`, le nombre maximal
  d'éléments d'une collection, et répondre `413` `too_large` à une
  écriture au-delà. [L-20.5-4]

## 21. Bibliothèques statiques

Une bibliothèque servie sous forme de fichiers, qui ne changent que quand
on les réécrit : chez un hébergeur web comme GitHub Pages, sur le serveur
web d'un NAS, ou sur une clé USB ou une carte SD lues sans aucun serveur.
Une bibliothèque statique est en lecture seule, et publique pour quiconque
atteint ses fichiers.

### 21.1 Organisation

Une bibliothèque statique est un dossier, sa **racine** : une adresse
(`https://lea.example.org/library/`) ou un dossier sur un stockage que lit
l'appareil. Chaque route de lecture est un fichier sous elle :

| Route | Fichier |
|---|---|
| La poignée de main (§ 4.2) | `lantern.json` |
| `GET <base>/v1/apps?platform=<p>` | `v1/apps/<p>/pages/<n>.json` : la page *n*, à partir de 1 |
| `GET <base>/v1/titles/{title_id}` | `v1/titles/<p>/<title_id>.json` |
| Tous les titres d'une plateforme | `v1/titles/<p>/pages/<n>.json` : le document du § 7.2, avec `next` |
| `GET <base>/v1/homebrew?platform=<p>` | `v1/homebrew/<p>/pages/<n>.json` |
| `GET <base>/v1/homebrew/{id}` | `v1/homebrew/<p>/<id>.json` |
| `GET <base>/v1/cheats?platform=<p>&title_id=<t>` | `v1/cheats/<p>/<t>.json` |
| `GET <base>/v1/cheats/{id}` | `v1/cheats/<id>.txt` |
| Un fichier (§ 6.6) | `v1/blobs/sha256/<hex>` : le fichier dont le SHA-256 est `<hex>` |

`<p>` est une plateforme des `platforms` de la poignée de main. Un titre
sans lot de codes de triche n'en a pas de fichier. Vecteurs de test :
`vectors/static-layout.json`.

- Un listage est trié comme le trie un serveur (par nom : § 6.2, § 8.5) et
  découpé en pages de `static.page_size` éléments : le curseur de la page
  *n* + 1 est `"<n+1>"`, et `next` vaut `null` sur la dernière page. Une
  plateforme qui n'a rien d'une famille a une première page vide. La même
  bibliothèque donne les mêmes pages.
- Une bibliothèque statique MUST ne contenir ces fichiers que là où le
  tableau les place, chacun valide selon son schéma comme l'est le document
  d'un serveur (§ 3.2), ses pages chaînées comme ci-dessus, ainsi que
  chaque fichier vers lequel pointent ses documents, de leur taille et de
  leur SHA-256. [L-21.1-1]
- Chaque `file` d'un document, et chaque `url` d'une image qui n'est pas
  `external`, MUST être un chemin relatif à la racine, comme
  `v1/blobs/sha256/3a7b…` : sans schéma, sans `/` initial, sans partie
  `..`, sans `\` et sans requête. [L-21.1-2]
- Ses textes sont dans une seule langue, le `language` de la poignée de
  main (§ 2.2).

### 21.2 Sa poignée de main

`lantern.json` est une poignée de main (§ 4.2) avec `static` :
`{"generated": "2026-10-30T18:00:00Z", "page_size": 100}`, quand ses
fichiers ont été écrits et la taille de ses pages. Sa `base` est `.` : la
racine.

- La poignée de main d'une bibliothèque statique MUST indiquer `account`
  `{"state":"anonymous", "scopes":["library","cheats"]}` (sans `cheats`
  quand elle n'en a pas), et donner 0 dans `features` à chaque famille
  qu'une bibliothèque statique ne peut pas proposer : `changes`,
  `sections`, `saves`, `encrypted_saves`, `requests`, `pairing`,
  `signatures`, `admin`, `events`, `peers` et `sync`. [L-21.2-1]
- `cheats`, quand il est au-dessus de 0, est en lecture seule (§ 10).
  `limits` ne donne que `page_size`.

### 21.3 En lire une

- Un client MUST lire les fichiers d'une bibliothèque statique comme du
  JSON quel que soit leur `Content-Type` (une clé USB n'en a pas, et un
  hébergeur web peut en annoncer un autre), et vérifie chaque fichier qu'il
  prend par sa taille et son SHA-256 (§ 6.6), comme depuis un serveur.
  [L-21.3-1] Un hébergeur web peut compresser ce qu'il sert : le client
  vérifie les octets une fois décodés.
- Ce qu'une bibliothèque statique ne peut pas fournir, un client le calcule
  à partir de ses pages : ce qui manque, selon les règles du § 6.3 sur tout
  le listage de sa plateforme ; les filtres et la recherche (§ 6.2, § 8.5) ;
  les mises à jour des homebrews (§ 8.5), en comparant `build`. Un client
  MUST calculer ce qui manque selon les règles du § 6.3, comme le ferait un
  serveur. [L-21.3-2]
- Une bibliothèque statique n'a ni appairage, ni jeton, ni plafond de
  classification : quiconque lit ses fichiers les lit tous, et une
  bibliothèque à une adresse publique est publique. Elle n'a ni
  changements ni événements : un client relit `lantern.json`, puis ses
  pages quand `static.generated` a changé (leur `ETag`, là où HTTP en
  donne un, épargne celles qui n'ont pas changé).
- Sur HTTP, le § 2 s'applique : HTTPS sauf sur le bouclage. Sur un stockage
  local, rien ne dit qui a écrit les fichiers, sinon l'utilisateur qui l'a
  branché ; les vérifications des § 6.6 et § 8 s'appliquent comme pour
  tout serveur.
- Un client à qui l'on donne une adresse essaie d'abord le
  `/.well-known/lantern` de l'origine, puis `<address>/lantern.json` ; un
  document avec `static` est une bibliothèque statique.

## Annexe A — Profils de plateforme

Un profil dit, pour une plateforme, ce que le cœur laisse ouvert. Il donne :

- la forme de `title_id` et d'`app_id`, avec une expression régulière ;
- les `type` d'app, et comment est dérivé `version_code` ;
- les `format` de paquet ;
- pour les codes de triche : le format de fichier, la forme de `build_id`
  et l'endroit où le client place un lot ;
- pour les sauvegardes : les types, les emplacements (slots) quand un titre
  en a plusieurs, et ce que contient l'archive, à quelle racine ;
- pour les homebrews : les formats de paquet et l'endroit où va un fichier
  unique, le `system_id` quand il y en a un, les architectures (`arch`,
  § 8.2) quand il y en a plusieurs, les racines où un client peut écrire
  sans demander, celles qui exigent le consentement de l'utilisateur, les
  zones pour le `data_root` d'un portage (§ 8.6), et les clés de
  `requires.min`.

Les chemins s'écrivent comme le dit le § 8.2 ; le profil dit comment ils
correspondent à l'appareil. Le profil de la Switch est complet. Ceux de la
3DS, de la Vita, de la PS4, d'Android et de Linux sont des brouillons, **à
relire par quelqu'un qui connaît la plateforme** : ce qui est marqué « (à
vérifier) » n'est pas arrêté. Les autres plateformes sont ouvertes : pas
encore de profil (annexe A.7).

### A.1 Nintendo Switch (`switch`)

- **Identifiants.** `title_id` : l'identifiant du jeu de base, 16 chiffres
  hexadécimaux en majuscules (`^[0-9A-F]{16}$`), ses 13 bits de poids
  faible à zéro. `app_id` : l'identifiant propre du paquet, de la même
  forme : le `title_id` pour le jeu de base, le `title_id` plus `800`
  (hexadécimal) pour sa mise à jour, et un identifiant propre au-dessus
  pour un contenu additionnel.
- **Types** : `base`, `update`, `dlc`. Une mise à jour est un paquet à part.
- **Versions.** `version_code` : la version entière du titre, telle que le
  système la lit (`196608` pour `v196608`) ; `version_name` : la version
  d'affichage des données de contrôle du jeu (`1.3.0`).
- **Formats** : `nsp`, `nsz`, `xci`, `xcz`.
- **Chemins** : `/` est la racine de la carte SD.
- **Codes de triche.** Le format texte d'Atmosphère. `build_id` :
  hexadécimal en majuscules, 1 à 64 chiffres ; Atmosphère nomme ses
  fichiers avec les 16 premiers, ceux de l'identifiant de build de
  l'exécutable principal. Le client écrit un lot dans
  `/atmosphere/contents/<title_id>/cheats/<build_id>.txt`, jamais dans
  `toggles.txt`, le fichier où Atmosphère retient quels codes sont actifs.
- **Sauvegardes.** Types `account` (la sauvegarde d'un utilisateur ;
  `profile` est le pseudonyme de l'utilisateur), `device`, `bcat`, `cache`,
  et `other` pour le reste (sauvegardes temporaires, StreamPlay et système).
  Pas d'emplacements. Le zip contient les fichiers du système de fichiers
  de la sauvegarde tels qu'ils y sont, à la racine de l'archive.
- **Homebrews.** Formats `nro` (un fichier unique, à
  `/switch/<id>/<id>.nro` : le menu homebrew prend le `.nro` d'un dossier
  qui porte le nom du dossier, ou le seul qu'il contient), `ovl` (une
  superposition, un fichier unique dans `/switch/.overlays/`, sous son
  propre nom de fichier, qu'attendent certains chargeurs) et `zip` ; une
  archive place au plus un `.nro` dans un dossier, ou un `.nro` du nom du
  dossier. Pas de `system_id`. Une seule architecture, donc pas d'`arch`.
  Racines sans consentement : `/switch/<id>/` et `/config/<id>/` (une
  convention des homebrews, pas une règle du système). Racines qui exigent
  un consentement : `/atmosphere/`, qui contient les sysmodules
  (`/atmosphere/contents/<program id>/`, avec `exefs.nsp`,
  `flags/boot2.flag` et `toolbox.json`), les fichiers LayeredFS et
  `exefs_patches` ; et `/switch/.overlays/`, qui contient les
  superpositions (des fichiers `.ovl`, qui exigent nx-ovlloader :
  `requires.homebrew`). Rien d'autre. Zones pour le `data_root` d'un
  portage : `/switch/` et `/config/`. Clés de `requires.min` : `firmware`
  (la version du système, `18.0.0`) et `atmosphere` (`1.7.0`).
- **Lire un `.nro`.** Un serveur lit son nom et son auteur dans les données
  de contrôle (NACP) de sa section de ressources ; depuis le système
  21.0.0, son bloc de titres peut être compressé en Deflate
  (`TitlesDataFormat` 1). La version du NACP n'est que du texte : `build`
  vient du `homebrew.json` de l'auteur, jamais du NACP.

### A.2 New Nintendo 3DS (`3ds`), brouillon

À relire par quelqu'un qui connaît la plateforme.

- **Identifiants.** `title_id` : 16 chiffres hexadécimaux en majuscules,
  l'identifiant du jeu, qui commence par `00040000` (celui d'une démo par
  `00040002`) : `^0004000[02][0-9A-F]{8}$`. `app_id` : l'identifiant propre
  du paquet, le `title_id` pour le jeu ; celui d'une mise à jour commence
  par `0004000E`, celui d'un contenu additionnel par `0004008C`, avec les
  mêmes 8 derniers chiffres que celui du jeu
  (`^0004(0000|0002|000E|008C)[0-9A-F]{8}$`).
- **Types** : `base`, `update`, `dlc`. Une mise à jour est un paquet à part.
- **Versions.** `version_code` : la version du titre sur 16 bits des
  métadonnées du titre ; `version_name` : ses 6 bits de poids fort, ses 6
  bits suivants et ses 4 bits de poids faible, comme version majeure,
  mineure et corrective (`2069` donne `2.1.5`).
- **Formats** : `cia` seulement. Les copies de cartouches (`3ds`, `cci`) ne
  sont jamais installées.
- **Chemins** : `/` est la racine de la carte SD.
- **Codes de triche.** Des codes Gateshark au format texte de Luma3DS, un
  fichier par jeu, à `/cheats/<title_id>.txt`. Pas de `build_id`. Rosalina
  préfère `/luma/titles/<title_id>/cheats.txt` : quand ce fichier existe,
  le client avertit l'utilisateur que c'est lui, et non le nouveau lot, qui
  est utilisé.
- **Sauvegardes.** Les données de sauvegarde du jeu en `device` (la 3DS n'a
  qu'un utilisateur) ; ses données supplémentaires en `other`, dans une
  archive à part, son `slot` étant l'identifiant des données
  supplémentaires (à vérifier). Ce que contient le zip et à quelle racine
  (à vérifier).
- **Homebrews.** Formats `3dsx` (un fichier unique, à
  `/3ds/<id>/<id>.3dsx`) et `zip` ; un `cia` est installé par le système
  comme un titre, qui l'installe sans demander : le client demande
  toujours d'abord à l'utilisateur, et son `system_id` est l'identifiant de
  titre. Un serveur MAY lire le nom et l'auteur d'un `3dsx` dans son SMDH,
  qui n'a pas de version : `build` vient de l'auteur. Une seule
  architecture, donc pas d'`arch`. Racines sans consentement :
  `/3ds/<id>/`. Racines qui exigent un consentement : `/luma/` (greffons,
  correctifs des titres, sysmodules), `/boot.firm`, `/boot.3dsx` et
  `/gm9/`. Zones pour le `data_root` d'un portage : `/3ds/`. Clés de
  `requires.min` : `firmware` (la version du système sans sa région,
  `11.17.0`) et `luma`.

### A.3 PlayStation Vita (`vita`), brouillon

À relire par quelqu'un qui connaît la plateforme.

- **Identifiants.** `title_id` : neuf lettres majuscules et chiffres
  (`^[A-Z0-9]{9}$`) ; celui d'un jeu compte quatre lettres et cinq chiffres
  (`PCSE00000`). `app_id` : le `title_id` pour le jeu et sa mise à jour ;
  l'identifiant de contenu d'un contenu additionnel
  (`^[A-Z]{2}[0-9]{4}-[A-Z0-9]{9}_[0-9]{2}-[A-Z0-9]{16}$`).
- **Types** : `base` (`CATEGORY` `gd` dans son `param.sfo`), `update`
  (`gp`), `dlc` (`ac`).
- **Versions.** `version_code` : `APP_VER` `XX.YY` sous la forme
  `XX`×100+`YY` (`01.03` donne `103`) ; `version_name` : `APP_VER`.
- **Formats** : `vpk`, et `pkg` seulement avec sa licence.
- **Chemins** : `/ux0/`, `/ur0/` et `/uma0/` sont les stockages `ux0:`,
  `ur0:` et `uma0:`.
- **Codes de triche.** Les fichiers `.psv` de VitaCheat, à
  `/ux0/vitacheat/db/<title_id>.psv` ; pas de `build_id` (à vérifier :
  VitaCheat est fermé).
- **Sauvegardes.** Les données de sauvegarde du jeu en `device` ; le zip
  contient le dossier déchiffré `ux0:user/00/savedata/<title_id>/`, avec
  son `sce_sys/`, à la racine de l'archive.
- **Homebrews.** Format `vpk`, décompressé et promu par le client, qui
  demande d'abord à l'utilisateur : pas de `path`, et l'application
  arrive dans `ux0:app/<title_id>/`. `system_id` : cet identifiant de
  titre. Une seule architecture, donc pas d'`arch`. Racines sans
  consentement : `/ux0/data/<id>/`. Racines qui exigent un consentement :
  `/ux0/tai/`, `/ur0/tai/` et le `config.txt` des greffons qu'ils
  contiennent (à vérifier : lequel l'emporte). Zones pour le `data_root`
  d'un portage : `/ux0/data/`.

### A.4 PlayStation 4 (`ps4`), brouillon

À relire par quelqu'un qui connaît la plateforme.

- **Identifiants.** `title_id` : quatre lettres majuscules et cinq chiffres
  (`^[A-Z]{4}[0-9]{5}$`, `CUSA00000`). `app_id` : le `title_id` pour le jeu
  et sa mise à jour ; l'identifiant de contenu d'un contenu additionnel
  (`^[A-Z]{2}[0-9]{4}-[A-Z]{4}[0-9]{5}_[0-9]{2}-[A-Z0-9]{16}$`).
- **Types** : `base`, `update`, `dlc`.
- **Versions.** `version_code` : `APP_VER` `XX.YY` sous la forme
  `XX`×100+`YY` ; `version_name` : `APP_VER`.
- **Formats** : `pkg`.
- **Chemins** : `/` est la racine du système telle que la voient les
  homebrews ; `/data/` est `/user/data/`.
- **Codes de triche.** Les formats de GoldHEN, `json`, `shn` et `mc4`, à
  `/data/GoldHEN/cheats/<format>/<title_id>_<build_id>.<format>`, un format
  par titre et par version. `build_id` : l'`APP_VER` du jeu (`01.03`),
  avec `_<process>` quand un lot vise un autre processus que celui du jeu.
- **Sauvegardes.** `account`, une sauvegarde par dossier de sauvegarde, son
  `slot` étant le nom du dossier (à vérifier : comment ils sont rangés sur
  le disque).
- **Homebrews.** Format `pkg`, installé par le service de paquets du
  système, qui n'affiche rien : le client demande d'abord à l'utilisateur
  (à vérifier). Pas de `path`. `system_id` : son identifiant de titre. Une
  seule architecture, donc pas d'`arch`. Racines sans consentement :
  `/data/<id>/`. Racines qui exigent un consentement : `/data/GoldHEN/`.
  Zones pour le `data_root` d'un portage : `/data/`. Clés de
  `requires.min` : `firmware` et `goldhen`.

### A.5 Android (`android`), brouillon

À relire par quelqu'un qui connaît la plateforme.

- **Identifiants.** `title_id` : le nom de paquet de l'application
  (`^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$`) ; `app_id` : le
  même.
- **Types** : `base` seulement : un paquet plus récent du même `app_id`
  remplace l'ancien, et c'est la mise à jour que cherche le § 6.3. Le
  système n'a pas de contenus additionnels, et cette version n'a pas de
  fichiers d'extension (OBB).
- **Versions.** `version_code` : le `versionCode` du paquet ;
  `version_name` : son `versionName`.
- **Formats** : `apk`, et `apks` (paquets fractionnés, installés en une
  seule session).
- **Codes de triche** : aucun.
- **Sauvegardes** : pas de profil (les données d'une application lui
  appartiennent).
- **Homebrews.** Formats `apk` et `apks`, installés par l'installateur du
  système : pas de `path`. L'installateur demande à l'utilisateur, sauf si
  le client est l'installateur attitré de l'application et que les
  conditions de `setRequireUserAction` sont remplies. `system_id` : le nom
  de paquet. `signer_sha256` (§ 8.2) : le SHA-256 du certificat de
  signature, qu'une mise à jour doit partager. `arch`, d'après les ABI
  d'Android : `arm64-v8a` est `aarch64`, `armeabi-v7a` est `armhf`, `x86`
  est `x86` et `x86_64` est `x86_64` ; un paquet sans `arch` contient
  toutes les ABI dont il a besoin. Zones pour le `data_root` d'un portage :
  un dossier que l'utilisateur choisit pour lui (à vérifier). Clés de
  `requires.min` : `sdk` (le niveau d'API minimal, `26`). Android 14 et 15
  refusent un paquet dont le `targetSdkVersion` est inférieur à 23 et 24.

### A.6 Linux (`linux`), brouillon

À relire par quelqu'un qui connaît la plateforme.

Une seule plateforme pour tous les systèmes Linux, ordinateur ou console
portable, quelle que soit leur distribution : ce qui les distingue
(architecture, bibliothèque C, graphisme, mémoire, écran) est dit par
`arch` (§ 8.2) et `requires` (§ 8.7), pas par un nom de plateforme.

- **Identifiants.** Linux n'a pas d'identifiant propre pour les logiciels
  installés : pas de `system_id`. Cette version ne sert que des homebrews :
  un serveur MAY servir des apps selon les règles du cœur, comme sur une
  plateforme ouverte (§ 4.3), et un client n'en installe aucune.
- **Chemins.** `/` est le dossier que le client a choisi pour les
  homebrews, et montré à l'utilisateur : sur une console portable, son
  dossier de portages tel que l'utilise PortMaster (à vérifier : il diffère
  selon les distributions, par exemple `/roms/ports/`) ; sur un ordinateur,
  `$XDG_DATA_HOME` (`~/.local/share/`), si bien que le dossier propre d'un
  homebrew est `$XDG_DATA_HOME/<id>/`. Un client n'écrit rien hors de ce
  dossier.
- **Homebrews.** Format `zip`, une archive avec un manifeste (§ 8.2) ; pas
  de fichier unique. Un fichier est rendu exécutable (mode `0755`, sinon
  `0644`) quand l'entrée de l'archive qui le concerne a le bit d'exécution
  de son propriétaire (les attributs externes du zip) ; le client ne pose
  jamais d'autre bit (setuid, setgid, sticky), et refuse un paquet dont
  l'archive contient un lien à un chemin du manifeste. Racines sans
  consentement : `/<id>/`. Racines qui exigent un consentement : le reste
  de `/`, comme un script de lancement à côté des dossiers de portages, ou
  le dossier d'un portage du nom que lui donne PortMaster ; un client
  refuse un chemin que contient le manifeste d'un autre homebrew installé.
  `arch` : `aarch64`, `armhf`, `x86`, `x86_64` et `riscv64`. Zones pour le
  `data_root` d'un portage : `/`, le dossier du client (le dossier de
  données d'un portage, comme `/<id>/data/`, s'y trouve). Clés de
  `requires.min` : `glibc`, `ram_mb` et `screen` ; les interfaces
  graphiques vont dans `requires.gpu` (§ 8.7 ; à vérifier : comment un
  client les apprend, par exemple d'EGL et du chargeur de Vulkan).
- **Codes de triche** : aucun dans cette version.
- **Sauvegardes** : aucune dans cette version (pas de sauvegardes système).
- **PortMaster.** La plupart des portages pour consoles portables sous
  Linux suivent l'empaquetage de [PortMaster](https://portmaster.games/) :
  un script de lancement dans le dossier des portages, les fichiers du
  portage dans un dossier à côté, et les données du jeu fournies par
  l'utilisateur. Un portage Lantern de ce genre garde cette organisation (le
  script et le dossier exigent un consentement, ci-dessus) et dit dans
  `requires_data` (§ 8.6) ce que fournit l'utilisateur. PortMaster nomme
  ses architectures `aarch64`, `armhf` et `x86_64`, comme Lantern, si bien
  que la liste d'un portage se reprend telle quelle (à vérifier).

### A.7 Plateformes ouvertes

Ouvertes : pas encore de profil. `ios`, `windows`, `macos` et `web`, ainsi
que les noms de boutiques d'Atlas (`steam`, `gog`, `xbox`), n'en ont pas ;
le § 4.3 dit ce que font sur elles un serveur et un client.

## Annexe B — Recommandations aux clients

Non normatif : des conseils tirés de ce que rencontrent consoles et
téléphones à l'usage. Un client qui les suit est plus agréable pour ses
utilisateurs et pour les serveurs qu'il lit.

### B.1 Délais

- Connexion : 10 secondes, 3 sur le réseau local ; la poignée de main TLS
  dans le même délai.
- Une requête JSON : 30 secondes sans un octet, 60 en tout.
- Un fichier : pas de limite au total, mais 60 secondes sans un octet, puis
  reprise (B.4).
- Interroger un appairage : comme le dit `interval`, jusqu'à `expires`.

### B.2 Nouvelles tentatives

- Ne retenter que ce qui peut l'être : `GET`, `HEAD`, `PUT` et `DELETE` ;
  les `POST` qui ne font que lire (`apps/missing`, `homebrew/updates`) ; le
  `PATCH` d'un envoi après un `HEAD` qui dit où reprendre. Ne jamais
  retenter un autre `POST` à l'aveugle : une demande envoyée deux fois fait
  deux demandes.
- Retenter après une connexion perdue, `408`, `429`, `500`, `502`, `503` et
  `504` ; jamais après un autre `4xx`.
- Espacer exponentiellement, avec une gigue complète : avant la tentative
  *n*, attendre un temps aléatoire entre 0 et min(60, 2^*n*) secondes ;
  abandonner après 5 tentatives, et le dire.
- `Retry-After` est un plancher : attendre au moins ce temps, quoi que dise
  l'espacement.
- Après `401` `signature_expired`, signer de nouveau une fois avec la `Date`
  du serveur (§ 5.4) ; après tout autre `401`, demander à l'utilisateur de
  s'appairer de nouveau plutôt que de retenter.

### B.3 Hors ligne, depuis le cache

- Garder la dernière poignée de main, les pages lues, les titres et leurs
  images, chacun avec son `ETag` ; revalider avec `If-None-Match` une fois
  en ligne.
- Sans serveur, afficher la bibliothèque en cache, marquée hors ligne avec
  son âge ; ce qui exige le serveur (un téléchargement, une sauvegarde)
  attend et le dit.
- Un document en cache d'un `schema` plus récent est absent, comme sur le
  réseau (§ 3.2).
- Rien n'est installé depuis le cache sans que son SHA-256 soit vérifié.

### B.4 Des téléchargements qui survivent à la veille

- Écrire dans un fichier partiel, et garder à côté son URL, son `ETag` et
  le `sha256` de l'app ; calculer l'empreinte à mesure que les octets
  arrivent, en gardant l'état du calcul, ou recalculer celle du fichier
  partiel à la reprise.
- Après une mise en veille ou une connexion perdue, reprendre avec
  `Range: bytes=<have>-` et `If-Range: <ETag>`. Un `206` continue ; un `200`
  signifie que le fichier a changé : recommencer. Un `404` ou un `410`
  signifie que son identifiant a expiré : relire l'app et comparer son
  `sha256`.
- Sur une console, empêcher la mise en veille pendant le téléchargement si
  le système le permet, et dire qu'un téléchargement se met en pause avec
  la console.
- L'envoi d'une sauvegarde reprend de la même façon, à partir de
  l'`Upload-Offset` de `HEAD` (§ 9.3).

### B.5 Plusieurs serveurs

- Un fichier, c'est son SHA-256 : deux apps du même `sha256` sont le même
  paquet, quel que soit le serveur qui les liste. L'afficher une fois, avec
  ses serveurs ; le prendre sur le plus rapide (le réseau local d'abord),
  et le vérifier de la même façon.
- Les titres se fusionnent par `platform` et `title_id` ; les homebrews par
  `platform` et `id`, le `build` le plus élevé d'abord. La clé épinglée
  d'un homebrew est celle de l'identifiant, quel que soit le serveur : un
  serveur ne peut pas apporter une autre clé (§ 8.4).
- Chaque serveur garde son propre jeton, sa clé, son épinglage et son
  plafond de classification ; un plafond fixé par un serveur ne dit rien
  d'un autre.

### B.6 Erreurs et empreintes

- Afficher le `title` et le `detail` d'une erreur (§ 12), bornés, sans
  caractères de contrôle, avec le nom du serveur ; le statut et le `code`
  en petit, pour un rapport ; jamais le JSON brut.
- Afficher une empreinte en police à chasse fixe, par groupes de 4, assez
  grande pour être comparée d'un bout à l'autre d'une pièce. À l'appairage,
  le code, l'empreinte et le QR code côte à côte (§ 5.2, § 5.3).
- Une clé qui change est une alarme, pas une erreur : dire que la clé du
  serveur a changé, afficher les deux empreintes, et ne s'appairer de
  nouveau que si l'utilisateur le demande.

### B.7 Les données d'un portage, avant le lancement

- Vérifier les fichiers du § 8.6 avant chaque lancement ; garder leurs
  empreintes par taille et date de modification, pour qu'un lancement ne
  demande pas de recalcul sauf si un fichier a changé.
- Afficher chaque fichier manquant ou inconnu avec son `hint` ; quand un
  groupe (`one_of`) offre plusieurs possibilités, les afficher toutes.
- Vérifier de nouveau dès que l'utilisateur dit avoir copié les fichiers.

### B.8 Le budget d'un démarrage à froid

Le premier démarrage d'un client sur un serveur auquel il s'est appairé,
avant son premier écran, demande au plus :

| Requête | Contenu |
|---|---|
| 1 | `GET <base>/v1/` (§ 4.2) |
| 2 | La première page de la bibliothèque, `page_size=50` (§ 6.2), ou des homebrews |
| 3 | Les titres des apps à l'écran, en une fois (`GET <base>/v1/titles?ids=`, § 7.2) |

soit 3 requêtes, et au plus 256 Kio de JSON tels qu'ils circulent
(compressés quand le serveur compresse, § 2.1). Les images viennent après,
à la demande, mises en cache par leur contenu. La suite de conformité
mesure ces trois requêtes sur un serveur et avertit quand elles dépassent
256 Kio.

### B.9 Horloges

L'horloge d'une console est souvent fausse. Calculer le décalage par
rapport à la `Date` du serveur à partir de la réponse de la poignée de
main, et signer avec (§ 5.4) ; afficher les heures dans le fuseau propre
de l'appareil.

### B.10 Les événements en arrière-plan

- **Le homebrew d'une console.** Pendant que son utilisateur joue, un
  homebrew en arrière-plan garde un flux (§ 18.1) vers son serveur, et
  affiche une petite notification quand une demande qu'il a faite est
  satisfaite ou qu'une sauvegarde est arrivée d'une autre console. Quand la
  console se met en veille, le flux meurt : au réveil, le homebrew demande
  une fois `changes?since=<the last id>&wait=0`, qui donne ce qui s'est
  passé pendant son sommeil, puis rouvre son flux avec `Last-Event-ID`. Un
  homebrew qui ne peut pas garder une socket en arrière-plan fait plutôt de
  l'interrogation longue avec un `wait` d'une minute environ.
- **Une intégration domotique** (boreale-ha, pour Home Assistant). Elle
  s'appaire comme un appareil, par un QR code affiché dans sa
  configuration, avec les portées de ce qu'elle montre : `library` pour un
  capteur des nouveaux jeux, `requests` pour l'état des demandes d'un
  foyer, `admin` pour lever une notification quand une console attend une
  approbation (l'événement `pairing`, avec son code et son empreinte, que
  l'administrateur compare avant d'approuver). Elle garde un flux,
  transforme chaque événement en un événement à elle, marque le serveur
  indisponible sur `shutdown` et revient après son `retry`.
- Toutes deux gardent le dernier `id` lu, pour que rien ne soit manqué d'un
  redémarrage à l'autre, et ne relisent la bibliothèque qu'après un `410`.

### B.11 Partager sur le réseau local

- N'activer le partage que quand l'utilisateur le demande, dire ce qu'il
  fait (« les autres consoles de ce réseau pourront télécharger les jeux
  que détient cette console, une fois que votre serveur les y autorise »),
  et afficher combien de téléchargements il a servis.
- Avant de lire un fichier sur un pair, demander une autorisation au
  serveur ; demander d'abord `HEAD` aux pairs, prendre le fichier sur l'un
  d'eux, continuer de lire le fichier sur le serveur quand le pair est plus
  lent ou échoue, et le vérifier en entier avant de le garder.
- Une sauvegarde ne passe jamais par un pair, chiffrée ou non.

### B.12 Synchronisation et clés de sauvegarde

- Demander le consentement une fois par profil, en termes simples :
  « Garder vos souhaits sur Living room shelf, pour que vos autres consoles
  les voient ? » et, séparément, « Partager aussi ce que cette console a
  installé ? ».
- Lire `GET <base>/v1/sync/{collection}?since=` au démarrage et à chaque
  événement `sync` ; écrire chaque changement au moment où il se produit,
  avec son `updated`.
- Quand une console crée une clé de sauvegarde, afficher sa phrase une
  fois, demander à l'utilisateur de la noter, et proposer de l'afficher de
  nouveau plus tard ; ne jamais la laisser dans une capture d'écran que le
  système prend de lui-même, là où le système permet à un homebrew de le
  signaler.

## Annexe C — La route vers la 1.0

Non normatif : ce dont ce texte a besoin avant sa version 1.0, quand
`/v1/` et le `schema` 1 cesseront de changer de forme.

1. **Deux serveurs et deux clients indépendants** atteignent `Lantern Core`
   avec la suite de conformité, chacun écrit à partir de ce texte par des
   personnes qui n'ont pas écrit les autres, et chaque paire d'entre eux
   fonctionne ensemble : appairage, listage, téléchargement, ce qui manque.
2. **Un cœur sans question ouverte** : chaque section du § 2 au § 14, et le
   § 17, sans partie marquée « à vérifier », et aucun ticket étiqueté comme
   question à leur sujet encore ouvert.
3. **Des profils relus pour deux plateformes au moins**, par des personnes
   qui les connaissent et qui ne sont pas les auteurs de ce texte : celui de
   la Switch et un autre, leurs identifiants, formats, chemins et racines
   essayés sur de vrais appareils.
4. Les familles au-delà du cœur (§ 7 à § 11, § 18 à § 21) peuvent rester au
   `schema` 1 et continuer de grandir après la 1.0, par ajouts seulement
   (§ 3.5).
5. Ensuite la règle des brouillons (§ 3.5) prend fin : un changement de
   forme fait monter le `schema` d'un document, et l'ancien reste servi tant
   que des clients le lisent.


## Modifications {#changes}

- 0.1 (2026-10-30) : premier brouillon.
- 0.1 (2026-10-30), d'après la suite de conformité : des identifiants
  erronés donnent aussi 401 sur la poignée de main, de même qu'un jeton
  inconnu ; une famille à 0 répond 404, 401 ou 403 ; `sort` vaut `name` par
  défaut et `release` va du plus récent au plus ancien ; un `page_size`
  au-delà de la limite y est ramené ; des codes pour 405 et 416.
- 0.1 (2026-10-30) : un curseur ou un jeton `since` expiré donne 410, un
  que le serveur n'a jamais donné 400 (ou 410 s'il ne sait pas faire la
  différence) ; un 416 porte `Content-Range: bytes */<size>` ; une
  défaillance du serveur répond 500 avec le code `internal`.
- 0.2 (2026-10-30) : un protocole à part entière, sans rien garder pour les
  protocoles utilisés avant lui ; toujours `/v1/` et le `schema` 1, en tant
  que brouillon.
  - Découverte (§ 4.1) : des datagrammes propres à Lantern sur UDP 47115,
    une annonce DNS-SD `_lantern._tcp`, et la découverte comme simple
    indication. Le datagramme et le port d'Ownfoil disparaissent.
  - Authentification (§ 5) : des jetons porteurs seulement, par appareil,
    hachés par le serveur, révocables, éventuellement à durée limitée ;
    l'authentification HTTP Basic disparaît. L'appairage est exigé d'un
    serveur privé, approuvé du côté du serveur seulement, avec des codes
    d'un alphabet sans ambiguïté (au moins 40 bits) qui expirent en
    10 minutes et sont limités en débit (429 `slow_down`). `pairing` est
    proposé à chaque appelant, anonyme compris.
  - Transport (§ 2, § 5.3) : HTTPS partout, HTTP en clair sur le bouclage
    seulement ; une clé auto-signée est épinglée à l'appairage, après que
    l'utilisateur a comparé son empreinte SPKI sur la console et sur le
    serveur.
  - Intégrité (§ 6.1, § 6.6) : `sha256` est exigé sur chaque app,
    `Repr-Digest` sur chaque réponse de fichier, et un client vérifie
    toujours un téléchargement avant de l'installer.
- 0.3 (2026-10-30) : toutes les plateformes sur lesquelles tourne Aurore,
  et quatre familles ; toujours `/v1/` et le `schema` 1, en tant que
  brouillon. Les fichiers deviennent le § 6.6, et les sections à partir de
  la 7 sont renumérotées : les erreurs sont au § 12.
  - Plateformes (§ 4.3, annexe A) : un cœur qui ne connaît aucune
    plateforme, et un profil par plateforme. Chaque app, titre, homebrew,
    sauvegarde et lot de codes de triche porte `platform` ; la poignée de
    main liste `platforms` ; un client nomme la sienne avec
    `Lantern-Platform` (ou `?platform=`), et le serveur ne répond que pour
    elle. Les noms de plateformes d'Atlas, et `3ds`, `vita`, `ps4`,
    `android`, `ios`, `windows`, `macos`, `linux` et `web`. Profils :
    celui de la Switch complet ; ceux de la 3DS, de la Vita, de la PS4,
    d'Android et de Linux (une seule plateforme pour les ordinateurs comme
    pour les consoles portables) en brouillon ; les autres ouverts, où un
    client n'installe rien.
  - Apps (§ 6.1) : `title_id` et `app_id` sont des chaînes opaques de la
    forme du profil, `type` et `format` viennent de ses listes, et
    `version` et `display_version` deviennent `version_code` et
    `version_name`. Ce qui manque (§ 6.3) exige une plateforme.
  - Titres (§ 7) : `titles` remplace `media`, avec le développeur, des
    genres d'une liste fixe et des étiquettes, les joueurs sur un appareil
    et en ligne, des classifications par âge par organisme, un résumé et
    une description localisés, des images et une vidéo externe, et
    `updated` ; plusieurs titres en une requête, et leurs changements.
  - Homebrews (§ 8) : une nouvelle famille : des entrées avec un
    identifiant stable en DNS inversé, un `kind` et un `build` à comparer,
    des paquets d'un seul fichier ou un zip avec un manifeste, par
    architecture là où une plateforme en a plusieurs, les règles que suit
    un client pour les installer et les désinstaller, une signature ed25519
    facultative dont la clé est épinglée par identifiant, et les mises à
    jour de ce qui est installé ; les dépendances envers d'autres
    homebrews, et l'identifiant propre à la plateforme de ce qui est
    installé, qu'un client ne laisse jamais deux entrées partager. Les
    portages de jeux nomment leur jeu original, leur moteur et leur dossier
    de données, et les fichiers que l'utilisateur fournit à partir de sa
    propre copie, qu'un serveur ne sert jamais. Les mods sont hors du
    champ. Les rayons viennent de `kind` et de `genres` (la liste des
    titres), avec des `tags` libres, et le listage filtre par `kind` et
    `genre`. Exigences (§ 8.7) qu'un client vérifie avant de proposer un
    paquet : `requires.min` (`glibc`, `ram_mb`, `screen`, et les clés du
    profil) et `requires.gpu` ; une qu'il ne sait pas lire donne un
    avertissement, une qui échoue un refus. Les architectures gagnent
    `riscv64` ; une qu'un lecteur ne connaît pas n'est jamais la sienne.
  - Sauvegardes (§ 9) : des envois reprenables par morceaux ;
    `Content-Digest` exigé sur une sauvegarde envoyée en une requête, et
    vérifié (422 `digest_mismatch`) ; le `kind`, le `slot`, le
    `game_version_code`, le `profile` et la `platform` d'une sauvegarde ;
    les `limits` de la poignée de main donnent les tailles et le nombre de
    sauvegardes conservées.
  - Codes de triche (§ 10) : plusieurs lots par build, chacun avec son
    identifiant, sa source, sa date de mise à jour et son SHA-256, lus par
    identifiant ; les écrire exige `cheats.write`.
  - Les demandes (§ 11) portent `platform`.
- 0.4 (2026-10-30) : l'accès et la qualité du texte ; toujours `/v1/` et le
  `schema` 1, en tant que brouillon. Chaque route et chaque champ de la 0.3
  restent, avec les ajouts ci-dessous ; le § 5 devient « Authentification
  et accès ».
  - Identifiants d'exigence (§ 3.5) : chaque MUST et chaque SHOULD a son
    identifiant, `L-<section>-<n>`, que nomment les contrôles de la suite.
    Les règles que la suite de la 0.3 imposait déjà sous forme de simples
    affirmations sont désormais écrites comme des exigences (MUST), sans
    changer de sens ; un client n'envoie son jeton et ses signatures qu'à
    l'origine du serveur (§ 2).
  - Clés d'appareil et requêtes signées (§ 5.4, fonctionnalité
    `signatures`) : une clé Ed25519 créée à l'appairage, `key` dans la
    demande d'appairage ; les requêtes d'un jeton lié signées selon la
    RFC 9421 (`@method`, `@target-uri`, `authorization`,
    `content-digest` ; `created`, `nonce`, `keyid`, `alg`) dans une
    tolérance de 300 secondes, les nonces conservés contre le rejeu ;
    l'interrogation d'un appairage avec clé signée ; de nouveaux codes
    `signature_required`, `signature_invalid`, `signature_expired`,
    `signature_replayed` (401) et `key_required` (400). Les jetons sans
    clé sont porteurs seuls, ce qu'un serveur MAY refuser. La poignée de
    main ajoute `auth`, `account.bound` et `features.signatures`.
  - Appairage (§ 5.2) : `verify_complete`, pour un QR code que dessine un
    client, le code et l'empreinte toujours affichés à côté ; le document
    du jeton ajoute `bound` et `rating_cap`.
  - Invitations (§ 5.5), plafonds de classification (§ 5.6, avec un tableau
    des âges par système de classification) et une API d'administration
    (§ 5.7, fonctionnalité et portée `admin`) : comptes, appareils,
    appairages en attente, invitations ; 409 pour un compte qui existe, 410
    pour une invitation qui n'existe pas.
  - `Accept-Language` (§ 2.2) choisit la langue des erreurs et du `motd` de
    la poignée de main ; un problème et la poignée de main portent
    `language`.
  - Compression (§ 2.1) : `zstd` ou `br`, et `gzip`, recommandés sur le
    JSON, jamais sur les fichiers ; une note sur HTTP/2.
  - `Deprecation` et `Sunset` (§ 3.4) ; comment le texte évolue (§ 3.5).
  - `atlas` sur les apps, les titres et les homebrews (§ 6.1) ;
    `installed_size` sur les apps et les paquets, et un client qui décide
    de ce qui tient (§ 6.3) ; `ratings` sur les homebrews (§ 8.1).
  - `DELETE <base>/v1/requests/{id}` (§ 11).
  - Un correctif de sécurité de la vérification Ed25519 (§ 8.4, § 5.4) : un
    vérificateur refuse une clé ou un R d'ordre faible et les encodages non
    canoniques, avant l'équation, qui seule acceptait une contrefaçon (une
    clé et un R d'ordre faible, S = 0) pour environ un message sur 8 ; un
    serveur refuse une clé d'appareil d'ordre faible à l'appairage. Le
    serveur de référence et le client de référence de la suite acceptaient
    de telles contrefaçons jusqu'à la 0.4 ;
    `vectors/ed25519-refused.json` contient les cas.
  - Un serveur refuse un document au-delà des limites sans défaillir
    (§ 13).
  - Un modèle de menaces (§ 16) ; des niveaux de conformité, le nom et le
    badge (§ 17) ; des vecteurs de test (`vectors/`) ; des recommandations
    aux clients (annexe B).
- 0.5 (2026-10-30) : ce qui se passe pendant que personne ne demande rien,
  des fichiers partagés sur le réseau local, la synchronisation, les
  sauvegardes chiffrées et les bibliothèques statiques ; toujours `/v1/` et
  le `schema` 1, en tant que brouillon. Chaque route et chaque champ de la
  0.4 restent, avec les ajouts ci-dessous ; quatre familles facultatives
  sont nouvelles, chacune déclarée dans `features` : `events`, `peers`,
  `sync` et `encrypted_saves`.
  - Événements (§ 18) : des Server-Sent Events à `<base>/v1/events`, dont
    les identifiants sont des jetons de `changes`, pour que
    `Last-Event-ID` reprenne là où le ferait `changes?since=` ; les
    événements `library`, `request`, `pairing`, `save`, `sync` et
    `shutdown`, chacun envoyé seulement aux appelants qui pourraient lire
    ce dont il parle ; des battements de cœur, `retry`, une limite de flux
    par jeton ; l'interrogation longue avec `changes?wait=`, dont le
    document gagne `events`. Les `limits` de la poignée de main ajoutent
    `heartbeat`, `event_streams` et `wait`.
  - Miroirs et pairs (§ 19) : `mirrors` sur les apps et les paquets ; des
    autorisations, signées par une clé propre au serveur (`peers` dans la
    poignée de main), avec lesquelles une console appairée partage les
    fichiers qu'elle détient, par leur SHA-256, à
    `/v1/blobs/sha256/{hex}` ; des pairs trouvés par la découverte
    (`"peers": true`, une réponse `lantern` `peer`) ou par DNS-SD. Un
    client vérifie ce que donne un miroir ou un pair comme ce que donne son
    serveur ; HTTP en clair est permis pour eux sur un réseau privé
    seulement (§ 2).
  - Synchronisation (§ 20) : les souhaits et ce que chaque console a
    installé, conservés par compte avec les portées `sync.read` et
    `sync.write`, seulement avec le consentement de l'utilisateur ; une
    règle de fusion par élément selon l'heure, avec `If-Match` pour une
    écriture tout ou rien (nouveau code `412` `precondition_failed`), et la
    suppression, qu'une console en veille ne peut pas annuler
    (`generation`).
  - Sauvegardes chiffrées (§ 9.4) : `lantern-save-e2e-1`,
    XChaCha20-Poly1305 par morceaux de 64 Kio avec une clé de fichier
    enveloppée par une clé dérivée de la clé de sauvegarde de l'utilisateur
    (HKDF-SHA-256) ; la clé transportée sous forme de phrase de récupération
    dans l'alphabet de l'appairage, ou de QR code ; `encryption` sur une
    sauvegarde.
  - Bibliothèques statiques (§ 21) : les routes de lecture sous forme de
    fichiers (poignée de main, pages aux curseurs fixes, titres, homebrews,
    codes de triche, fichiers par leur SHA-256), une poignée de main avec
    `static`, et ce qu'un client calcule lui-même ; le serveur de référence
    en exporte une, et la suite en vérifie une (`--static`).
  - Supprimer un compte (§ 5.7) : `DELETE <base>/v1/admin/users/{name}`,
    confirmé par le nom, qui révoque ses appareils et efface ses données ;
    la suite supprime désormais le compte qu'elle crée.
  - Découverte (§ 4.1) : le serveur de référence s'annonce par DNS-SD, avec
    la seule bibliothèque standard.
  - Les schémas vérifient les identifiants de chaque profil, brouillons
    compris, dans chaque document qui les porte, et le `build_id` d'un lot
    de codes de triche selon le profil.
  - Un modèle de menaces pour chaque ajout (§ 16), les niveaux de
    conformité `+events`, `+peers`, `+sync`, `+encrypted_saves` et
    `Lantern Static` (§ 17), les recommandations aux clients B.10 à B.12,
    et la route vers la 1.0 (annexe C).

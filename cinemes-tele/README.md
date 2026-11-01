# Cartellera per a la tele

Carrusel de pòsters dels cinemes de la zona per a la pantalla d'inici d'una Android TV, amb la fitxa de cada
pel·lícula. No forma part del tauler: és aquí només com a còpia del codi.

| Cinema | Lloc | Font |
|---|---|---|
| Teatre Mundial | la Bisbal d'Empordà | agenda municipal (schema.org) |
| Cinema Montgrí | Torroella de Montgrí | portada i fitxes de la web |
| TeMePé | Palafrugell | agenda municipal (schema.org) |
| OCINE | Platja d'Aro i Girona | API de la web d'entrades |
| Odeon | Salt | pàgina de pel·lícules, a través de r.jina.ai |

## Què hi ha

- `app/`: l'app ajudant `cat.latdg.temps`, sense icona.
  - `Cinema.java`: el scraper. Fusiona les fonts i desa `cine.json` i els pòsters.
  - `Tmdb.java`: valoració, plataformes i pòster. `Traductor.java`: del castellà al català (Softcatalà).
  - `Tls12.java`: el servidor d'OCINE talla la salutació TLS 1.3 d'Android 10.
  - `TempsProvider.java`: dona les dades al launcher.
  - `FilmActivity.java`: la fitxa de la pel·lícula.
- `launcher/`: la part del launcher [cleanyourtv](https://github.com/Gathin23/cleanyourtv) (llicència MIT).
  - `InfoLine.java`: la fila de pòsters.
  - `carrussel.patch`: els enganxos a `MainActivity.java` i `config.xml`, per a la v3.2.0.

## TMDB

Valoració, plataformes i pòsters surten de l'API de TMDB, que demana un token de lectura propi: es demana a
themoviedb.org (Configuració, API) i es posa a `tmdb.token` de `local.properties`, que queda fora del repositori. El
token va dins de l'APK compilat, així que l'APK tampoc s'ha de publicar. Sense token, `Tmdb.java` no fa res i la
cartellera surt igual amb les dades dels cinemes.

This product uses the TMDB API but is not endorsed or certified by TMDB. Les dades de plataformes són de JustWatch, a
través de TMDB.

## Compilar

Cal JDK 17 i l'SDK d'Android 34.

    cp local.properties.example local.properties
    ./gradlew assembleRelease

Per al launcher, a un clon de cleanyourtv a la v3.2.0: `git apply carrussel.patch`, i copia `InfoLine.java` a
`launcher/app/src/main/java/com/gathin/tvhome/`.

La cartellera s'actualitza cada 3 hores, o 10 minuts després d'un error, i només mentre la pantalla d'inici és visible.
Si un cinema no respon, se'n conserven les darreres sessions bones. OCINE i l'Odeon poden rebutjar les connexions que
arriben des d'una VPN. Per veure quina font falla: `content query --uri content://cat.latdg.temps/cine_estat`.

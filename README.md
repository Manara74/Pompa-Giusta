# Pompa Giusta

App web per confrontare i prezzi dei carburanti in Italia con la media della propria regione.

- **Zona**: i distributori di una provincia o di un comune, con la differenza in centesimi rispetto alla media regionale e il risparmio su un pieno.
- **Vicino a me**: i distributori attorno alla tua posizione, ordinati per convenienza (viaggio compreso).
- **Percorso**: scrivi partenza e arrivo (per esempio casa e lavoro) e vedi i distributori lungo la strada, con il costo del pieno comprensivo della deviazione.
- **Servizi**: lavaggio, aria/gonfiaggio, bar o negozio, ricarica elettrica, officina, WC, aperto 24 ore. I dati arrivano da OpenStreetMap e sono incompleti: se un servizio manca puoi segnarlo tu, solo sul tuo telefono.

## Come usarla sul telefono

Apri **https://manara74.github.io/Pompa-Giusta/** (le maiuscole contano). Non serve nessun account e non c'è niente da scaricare. Per averla come una app con la sua icona:

**iPhone (iOS)**
1. Apri il link con **Safari** (con Chrome non funziona).
2. Tocca il pulsante di condivisione, il quadrato con la freccia in su.
3. Scegli **Aggiungi alla schermata Home** e conferma.

**Android**
1. Apri il link con **Chrome**.
2. Tocca i tre puntini in alto a destra.
3. Scegli **Installa app** o **Aggiungi a schermata Home**.

Casa, lavoro, preferiti e note restano sul tuo telefono. Se cancelli i dati del sito o disinstalli l'app, si perdono.

## Come si aggiorna da sola

Ogni mattina GitHub esegue `scripts/build_data.py`, che scarica i file aperti del Ministero (Prezzi alle 8 e Anagrafica impianti), prepara i dati e ripubblica il sito. Ogni domenica `scripts/build_services.py` raccoglie i servizi da OpenStreetMap.

## Attivazione (una volta sola)

1. **Settings → Pages → Build and deployment → Source**: scegli **GitHub Actions**.
2. **Actions**: se GitHub chiede di abilitare i workflow, conferma.
3. **Actions → Aggiorna prezzi e pubblica → Run workflow** per la prima pubblicazione.
4. **Actions → Aggiorna i servizi dei distributori → Run workflow** per raccogliere i servizi la prima volta (richiede molto tempo, anche più di un'ora).
5. L'indirizzo dell'app compare nel passo «deploy» del primo workflow e in **Settings → Pages**.

## Privacy

Nel repository ci sono solo il programma e dati pubblici. Casa, lavoro, preferiti e note sui servizi restano nel browser del telefono. Per cercare un indirizzo e tracciare il percorso, l'app contatta i servizi pubblici di OpenStreetMap (Nominatim e il server di routing OSRM).

## Limiti

- I prezzi sono quelli comunicati dai gestori e in vigore alle 8 del giorno precedente alla pubblicazione.
- Le medie escludono gli impianti autostradali e i carburanti speciali e scartano i prezzi comunicati più di 8 giorni prima.
- La deviazione sul percorso è una stima in linea d'aria, non un calcolo sulle strade.
- Il manometro del gonfiaggio, la ricarica dell'aria condizionata e gli orari non sono disponibili in nessun dato aperto.

## Licenze dei dati

Prezzi: Ministero delle Imprese e del Made in Italy, licenza IODL 2.0. Servizi e mappe: © OpenStreetMap contributors, licenza ODbL.

# FreeCAD AI Copilot — Sintesi del Brainstorming Architetturale

> Documento di sintesi della sessione di brainstorming strategico (14 giugno 2026).
> Raccoglie i principi fondanti, l'architettura macroscopica decisa e i nodi ancora aperti.
> Serve come base di partenza per lo sviluppo.

---

## Obiettivo del progetto

Un assistente AI (Copilot) per **FreeCAD** che **automatizza la progettazione** — dall'operazione
minima al componente intero — tramite comandi in linguaggio naturale.

- Funziona sia con **modelli locali** (privacy) sia con **API esterne** (OpenAI, Anthropic).
- **Cross-platform**: Windows, macOS, Linux.
- Distribuito **gratuitamente da GitHub**, sopra una base FreeCAD non modificata.
- Visione di lungo periodo: un giorno i modelli girano in locale sulla SSD dell'utente,
  liberandosi del tutto da cloud, host e server.

### Vincolo tecnico di riferimento

- **FreeCAD target: 1.1.1** — installer disponibili in `000___Installer/` per tutte le piattaforme
  (Windows `.exe` e `.7z`, macOS x86_64 e arm64, Linux x86_64 e aarch64).
- **Python interno di FreeCAD: 3.11** (tutti gli installer sono `py311`).
- **Conseguenza architetturale (principio 3):** l'addon dentro FreeCAD convive con Python 3.11, ma il
  **motore AI separato NON deve dipendere dal Python 3.11 interno di FreeCAD**. Gira come processo a sé,
  con il proprio ambiente, per restare libero dal vincolo di versione e poter evolvere in autonomia.

---

## I nove principi fondanti (la "costituzione")

Ogni decisione futura deve essere coerente con questi principi. Sono il punto fermo del progetto.

1. **Privacy-first / local-first** — Tutto gira in locale di default; cloud e API sono un'opzione, mai un obbligo.
2. **FreeCAD intoccato** — La base resta FreeCAD puro da GitHub; siamo un addon compatibile sopra, non un fork.
3. **Cervello separato e intercambiabile** — Il motore AI è un processo a sé; il modello vero e proprio sta fuori dal pacchetto, scelto dall'utente.
4. **Il modello agisce, non chiede permesso** — Automazione vera, dall'operazione minima al componente intero.
5. **Precisione col vocabolario strutturato, potenza col Python libero — ma trasparente** — Quando l'agente esce dal controllato ed esegue Python libero, l'utente lo vede.
6. **Sicurezza = reversibilità** — Tutto dentro transazioni annullabili; conferma umana solo per azioni irreversibili.
7. **Non fidarsi mai dell'utente** — L'agente percepisce e verifica da sé; gestisce nonsense e richieste impossibili senza rompersi.
8. **Correttezza prima della velocità** — La lentezza locale è accettata e si migliora nel tempo, passo dopo passo.
9. **Adattamento, non esclusione** — Gira con qualsiasi modello; si adatta alle macchine deboli accettando complessità inferiori; informa l'utente sui limiti senza obbligarlo a un modello specifico.

---

## Architettura macroscopica

### Deployment

L'utente ha **già FreeCAD** installato. Scarica un pacchetto che contiene due cose:

1. **Addon leggero** dentro FreeCAD — interfaccia utente + "ponte" verso il motore. Piccolo (KB/MB).
2. **Motore AI separato** — un processo a sé stante che orchestra l'agente. Leggero/medio.

Il **modello vero e proprio** (i GB di "pesi") **non** è nel pacchetto: si scarica/configura
al primo avvio (download guidato di un modello locale, oppure inserimento di una API key).
Questo tiene il pacchetto base leggero e coerente con la libertà di scambiare il modello.

> Tre strati distinti: (1) addon, (2) motore/runtime, (3) modello. Il pacchetto contiene 1 e 2;
> il 3 è esterno.

### L'agente

Un **agente unico a due marce**:

- **Marcia diretta** — per i comandi semplici (es. "smussa questo spigolo"): intenzione → comando → eseguito, senza pianificazione. Immediata.
- **Marcia progetto** — per gli obiettivi complessi (es. "progetta una staffa"): il modello stende un piano a passi, poi lo esegue con il ciclo *agisci → osserva → correggi*.

Il multi-agente specializzato (Geometria / Codice / UI) è **rimandato** a evoluzione futura:
all'inizio moltiplicherebbe latenza, costi e punti di rottura.

### Azione sulla geometria (modello di sicurezza)

Il modello è l'agente che **agisce**, non un consulente che chiede permesso. La sicurezza non è
autorizzazione preventiva, ma **reversibilità**:

- **Vocabolario strutturato** — un catalogo di comandi sicuri scritti e validati da noi (es. `crea_foro`, `estrudi`, `smussa`). Danno precisione, soprattutto ai modelli locali deboli. Il modello li invoca autonomamente (tool calling) e vengono eseguiti subito.
- **Python libero** — quando il vocabolario non basta, il modello può scrivere ed eseguire Python arbitrario su FreeCAD. **Trasparenza obbligatoria**: l'utente viene informato in modo inequivocabile che qui il pacchetto non controlla più i comandi e il codice agisce liberamente sulla base del modello. Il codice resta visibile/ispezionabile.
- **Transazioni annullabili** — ogni azione gira dentro una transazione FreeCAD; se qualcosa si rompe (o l'utente annulla), rollback automatico al punto di partenza. L'utente non perde mai il lavoro.
- **Ciclo di autocorrezione** — dopo ogni comando l'agente legge il risultato (ricalcolo ok? geometria valida?) e si corregge da solo in caso di errore.
- **Conferma umana** — solo per azioni **irreversibili** (es. sovrascrivere file su disco), dove undo/transazione non bastano.

### Percezione del documento (gli "occhi" dell'agente)

Principio chiave: **non fidarsi dell'utente**, che potrebbe non essere un esperto CAD e fare test
di ogni tipo. L'agente deve orientarsi da solo.

- La percezione è una **capacità attiva di ispezione**, non un pacchetto di dati passato una volta.
- **Sguardo d'insieme** — "cosa c'è nel documento?": panoramica economica, sempre disponibile, primo passo di ogni task.
- **Sguardo ravvicinato** — "dettagli del corpo X / di questa faccia": l'agente decide *lui* su cosa zoomare in base all'obiettivo. È una forma di **RAG sulla geometria**, guidata dall'agente, non dall'utente.
- **Verifica di fattibilità** — la richiesta dell'utente è un desiderio, non un ordine valido: l'agente la confronta sempre con la realtà del documento (es. "foro da 50mm su piastra da 5mm" → impossibile, gestito senza rompere nulla).
- **Disambiguazione autonoma** — prova prima a capire da sé; chiede solo se davvero ambiguo, e con linguaggio semplice (es. evidenziando a schermo "intendi questo?").
- **Tolleranza al nonsense** — riconosce richieste assurde/contraddittorie e risponde con calma, senza rompere il documento né bloccare FreeCAD.

### La presa universale (collegamento ai modelli)

Il componente che rende reale "locale *o* API, intercambiabili" e "funziona dappertutto".

- **Lato agente standardizzato** — l'agente produce sempre lo stesso tipo di richiesta (obiettivo + contesto + comandi disponibili) e riceve sempre lo stesso tipo di risposta, senza sapere chi la eseguirà. Scritto una volta sola, non cambia mai.
- **Lato motore variabile** — un *adattatore* per ogni tipo di motore (Ollama, llama.cpp, API OpenAI, API Anthropic) traduce la lingua interna nel dialetto specifico. Aggiungere un modello = scrivere un adattatore, senza toccare l'agente.
- **Colmare il divario del tool calling** — se il modello ha il tool calling nativo, l'adattatore lo usa; se non ce l'ha (modelli deboli), lo **emula** (chiede output strutturato e lo interpreta). L'agente vede sempre la stessa cosa.
- **Profilo di capacità** — ogni adattatore dichiara cosa il modello sa fare (vede immagini? quanto contesto? tool calling nativo o emulato?). L'agente adatta la marcia. Nessuna lista di modelli "buoni/cattivi": adattamento, non esclusione.
- **Misura empirica della capacità** — non si chiede "che modello hai?": si lascia agire l'agente e si osserva. Se sbaglia di continuo, siamo oltre la sua portata → si degrada con grazia o si informa l'utente. La **reversibilità** (principio 6) è ciò che ci permette di lasciar *provare* qualsiasi modello senza rischi.
- **Spia della privacy** — la presa sa se la spina è locale o remota; quando i dati starebbero per uscire dalla macchina, è dichiarato in modo inequivocabile.
- **Configurazione al primo avvio** — l'utente sceglie la spina (modello locale o API key). Nessun obbligo, nessun requisito minimo imposto.

---

## Nodi ancora aperti (per le sessioni future)

- **Meccanica del ponte** addon ↔ motore: come viaggiano concretamente i messaggi tra i due processi (rimandato più volte, da affrontare presto).
- **Formato della descrizione testuale del d
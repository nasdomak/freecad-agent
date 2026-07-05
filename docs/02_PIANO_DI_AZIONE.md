# FreeCAD AI Copilot — PIANO DI AZIONE

> Deliverable della sessione di sviluppo n.1 (14 giugno 2026).
> Redatto dal Lead Software Architect. **In attesa di approvazione di Marco prima di scrivere codice.**
> Riferimenti: `00_SINTESI_Brainstorming.md` (principi e architettura), `01_PROMPT_Avvio_Sviluppo.md` (mandato).

---

## 0. Sintesi esecutiva (TL;DR)

Costruiamo il sistema in tre strati separati — **addon FreeCAD** (UI + ponte), **motore AI** (processo
autonomo con Python proprio), **modello** (esterno, scelto dall'utente) — collegati da un **ponte locale
JSON-RPC su socket**. Sviluppiamo dal basso verso l'alto in **6 fasi**, partendo dal pezzo più rischioso
e più fondante: il **ponte** e l'**esecutore del vocabolario** dentro FreeCAD, prima ancora di collegare
un vero modello. La **Fase 1 eseguibile** è un addon minimo che riceve un comando strutturato via socket,
lo esegue in una transazione annullabile e restituisce il risultato — senza AI. Questo ci dà subito lo
scheletro su cui innestare, in ordine di rischio crescente, percezione, presa universale e agente.

I tre rischi maggiori sono, in ordine: **(1) emulazione del tool calling** per i modelli deboli,
**(2) meccanica del ponte** addon↔motore, **(3) formato del contesto geometrico**. Il piano li affronta
in modo isolato e prototipabile, mai tutti insieme.

---

## 1. Struttura di progetto

Monorepo unico su GitHub. Tre strati = tre aree top-level, più supporto.

```
freecad-ai-copilot/
├── addon/                      # STRATO 1 — vive dentro FreeCAD (Python 3.11 obbligato)
│   ├── InitGui.py              # entry point del workbench FreeCAD
│   ├── ai_copilot/
│   │   ├── ui/                 # pannello, console comandi, indicatori (spia privacy, banner Python libero)
│   │   ├── bridge_client.py    # ponte lato addon: parla col motore via socket JSON-RPC
│   │   ├── executor/           # esegue i comandi DENTRO FreeCAD
│   │   │   ├── vocabulary/     # implementazioni dei comandi strutturati (crea_foro, estrudi, smussa…)
│   │   │   ├── transaction.py  # wrapping in transazioni annullabili + rollback
│   │   │   └── free_python.py  # esecuzione Python libero (sandbox-light + trasparenza)
│   │   └── perception/         # gli "occhi": ispezione attiva del documento
│   │       ├── overview.py     # sguardo d'insieme (panoramica economica)
│   │       └── detail.py       # sguardo ravvicinato (RAG geometrico)
│   └── package.xml             # metadata addon per FreeCAD Addon Manager
│
├── engine/                     # STRATO 2 — processo AI separato (Python PROPRIO, NON quello di FreeCAD)
│   ├── pyproject.toml          # ambiente isolato, versione Python libera
│   ├── core/
│   │   ├── agent.py            # agente unico a due marce (diretta / progetto)
│   │   ├── loop.py             # ciclo agisci → osserva → correggi
│   │   └── session.py          # stato della conversazione / del task
│   ├── bridge_server.py        # ponte lato motore: server JSON-RPC verso l'addon
│   ├── grip/                   # LA PRESA UNIVERSALE
│   │   ├── interface.py        # contratto standard lato-agente (richiesta/risposta invarianti)
│   │   ├── capability.py       # profilo di capacità + misura empirica
│   │   ├── tool_calling.py     # tool calling nativo VS emulato (il nodo più rischioso)
│   │   └── adapters/           # ollama.py, llamacpp.py, openai.py, anthropic.py
│   └── contracts/              # schema condivisi addon↔motore (vocabolario, contesto, messaggi)
│
├── shared/                     # contratti versionati condivisi dai due strati (JSON Schema)
│   ├── commands.schema.json    # il vocabolario strutturato come dato, non come codice
│   ├── context.schema.json     # formato della descrizione del documento
│   └── protocol.schema.json    # messaggi del ponte
│
├── installer/                  # bootstrap primo avvio: scarica modello / configura API key / crea venv motore
├── tests/                      # unit + integrazione (mock di FreeCAD dove serve)
├── docs/                       # questo piano, ADR (decisioni architetturali), guide
└── 000___Installer/            # già presente: FreeCAD 1.1.1 per tutte le piattaforme
```

**Decisione chiave:** il **vocabolario** vive in due posti complementari. La *definizione* (nome,
parametri, schema) sta in `shared/commands.schema.json` — un dato neutro che sia addon che motore leggono.
L'*implementazione* (il codice che tocca FreeCAD) sta in `addon/executor/vocabulary/`. Così il motore sa
"cosa esiste e con che parametri" senza dipendere da FreeCAD, e l'addon sa "come farlo davvero". Aggiungere
un comando = una entry nello schema + una funzione nell'executor. Coerente col principio 5 (precisione).

---

## 2. Stack tecnologico minimo

**Linguaggi.** Python ovunque, ma con **due interpreti distinti e indipendenti** (principio 3):
- Addon → vincolato al **Python 3.11 interno di FreeCAD** (non possiamo sceglierlo).
- Motore → **proprio venv**, versione libera (target 3.12+), zero dipendenze dal Python di FreeCAD.

Questo è il punto su cui il principio 3 diventa concreto: i due strati non condividono interprete, non
condividono `site-packages`, non si importano a vicenda. Comunicano solo via ponte.

**Il ponte (addon ↔ motore) — decisione architetturale raccomandata.**
Confronto tra le opzioni:

| Opzione | Pro | Contro | Verdetto |
|---|---|---|---|
| **TCP socket locale + JSON-RPC 2.0** | Cross-platform identico, bidirezionale, nativo in stdlib (`socket`/`asyncio`), debuggabile | serve gestire porta/handshake | **SCELTA** |
| stdin/stdout (motore figlio dell'addon) | semplice | accoppia i cicli di vita; il motore "muore" con FreeCAD; difficile da ispezionare | scartato |
| HTTP REST localhost | familiare | overhead, niente push server→client per il ciclo agisci/osserva | scartato per ora |
| File/named pipe | — | frammentazione cross-platform (named pipe Windows ≠ Unix socket) | scartato |

**Raccomandazione: TCP socket su `127.0.0.1` (porta effimera, handshake con token) + JSON-RPC 2.0.**
È bidirezionale (il motore deve poter chiamare l'addon: "esegui questo comando", "dammi la percezione X"),
funziona identico sui tre OS, sta in stdlib, ed è ispezionabile. Il motore è un processo a sé con un suo
ciclo di vita: l'addon lo avvia/aggancia ma non lo possiede.

**Distribuzione cross-platform.** Pacchetto base leggero (KB/MB) = addon + motore. Tre canali, per fasi:
1. **Addon** → via **FreeCAD Addon Manager** (`package.xml`) + repo GitHub. Zero attrito per l'utente FreeCAD.
2. **Motore** → bootstrap al primo avvio che crea un venv isolato e installa le dipendenze del motore
   (con fallback a un eseguibile pre-impacchettato — PyInstaller/Briefcase — per chi non ha Python di sistema).
3. **Modello** → mai nel pacchetto. Primo avvio: download guidato di un modello locale **oppure** API key.

Il vincolo "non dipendere dal Python di FreeCAD" implica che il motore **non può** assumere alcun Python
sulla macchina: per questo prevediamo il fallback a eseguibile self-contained. È un rischio di distribuzione,
non di architettura — lo isoliamo nella Fase 5.

---

## 3. Governance degli agenti di sviluppo

**Modello a un coordinatore + sotto-agenti specializzati per dominio**, attivati su richiesta, non sempre
attivi (lo stesso principio dell'agente runtime: niente multi-agente prematuro).

- **Coordinatore (io)** — possiede il piano, la memoria e l'integrazione. Suddivido il lavoro, scrivo i
  contratti condivisi (`shared/`) *prima* di delegare, e verifico ogni output contro i principi.
- **Sotto-agenti per dominio**, ciascuno con un confine netto dato dai contratti:
  - *Addon/FreeCAD* — workbench, executor, transazioni, percezione (richiede conoscenza API FreeCAD).
  - *Motore/Agente* — loop, sessioni, marce.
  - *Presa universale* — adattatori + emulazione tool calling (il dominio più rischioso, isolato apposta).
  - *Verifica/QA* — test, prototipi di rischio, controllo di coerenza coi principi.
- **Regola di delega:** un sotto-agente riceve un task solo dopo che il *contratto* (schema in `shared/`)
  che lo delimita è scritto e approvato. I contratti sono il giunto che permette di parallelizzare senza
  che gli strati si rompano a vicenda.

**Gestione della memoria tra sessioni (protocollo tassativo).**
- `project_context.md` è la fonte di verità viva: obiettivo, principi, **decisioni architetturali (ADR)**,
  stato attuale, ultima azione, dati critici (path, porte, scelte), prossimi passi. Aggiornato a **ogni
  checkpoint** (fine operazione logica o pausa), sovrascrivendo l'obsoleto per restare conciso.
- Le decisioni importanti vengono congelate come **ADR numerati** in `docs/adr/` (immutabili), mentre
  `project_context.md` ne tiene solo l'indice e lo stato corrente. Così la memoria viva resta corta e la
  storia delle decisioni non si perde.
- All'inizio di ogni sessione: leggo `project_context.md` integralmente prima di agire. Mai richiedere a
  Marco un dato già salvato.

---

## 4. Roadmap a fasi

Principio guida dell'ordine: **costruire dal basso e dal più rischioso-fondante**. Prima lo scheletro che
esegue azioni reversibili in FreeCAD, poi gli occhi, poi la presa, poi il cervello. Ogni fase produce
qualcosa di dimostrabile e testabile da sola.

### Fase 1 — Lo scheletro: ponte + executor + transazioni *(senza AI)*
**Cosa:** addon minimo (workbench + pannello) che apre il ponte socket, riceve un comando strutturato
(es. JSON `{"cmd":"crea_box","params":{...}}`), lo esegue dentro una transazione annullabile e risponde
con esito + stato. Un client di test (script) impersona il "motore".
**Milestone:** un comando strutturato viaggia, esegue, ed è annullabile con Ctrl+Z in FreeCAD.
**Rischi:** *meccanica del ponte* (RISCHIO #2) — handshake, porta, riconnessione, threading nella UI di
FreeCAD (Qt). Mitigazione: prototipo del solo ponte come primissima cosa, isolato.

### Fase 2 — Vocabolario strutturato + Python libero trasparente
**Cosa:** catalogo iniziale di comandi sicuri (≈ box, cilindro, foro, estrusione, smusso, raccordo,
booleane) definiti in `shared/commands.schema.json` e implementati nell'executor; canale Python libero con
**banner di trasparenza** obbligatorio e codice ispezionabile; ciclo di autocorrezione base (leggo l'esito
del ricalcolo).
**Milestone:** ≥ 6 comandi strutturati + esecuzione Python libero segnalata; rollback su errore di ricalcolo.
**Rischi:** scelta del catalogo minimo (coprire troppo o troppo poco); sicurezza del Python libero. Mitigazione:
catalogo guidato dai casi d'uso reali; trasparenza > restrizione, dentro la rete di sicurezza delle transazioni.

### Fase 3 — Percezione del documento (gli occhi)
**Cosa:** `overview.py` (sguardo d'insieme economico, sempre primo passo) e `detail.py` (sguardo ravvicinato
su corpo/faccia scelto dall'agente); definizione di `context.schema.json`; verifica di fattibilità
(confronto desiderio↔realtà del documento).
**Milestone:** dato un documento, il sistema produce un contesto testuale conciso a due livelli e rifiuta con
grazia un'operazione impossibile (es. foro 50mm su piastra 5mm).
**Rischi:** *formato del contesto geometrico* (RISCHIO #3) — saturare il contesto dei modelli locali.
Mitigazione: misurare i token su modelli locali piccoli; insieme sempre economico, dettaglio on-demand (RAG).

### Fase 4 — La presa universale + emulazione del tool calling
**Cosa:** `interface.py` (contratto lato-agente invariante), `capability.py` (profilo + misura empirica),
`tool_calling.py` (nativo vs **emulato**), e i primi due adattatori: **Ollama** (locale) e **una API**
(Anthropic o OpenAI). Spia della privacy.
**Milestone:** lo stesso identico prompt-agente produce comandi validi sia via modello locale con tool
calling emulato, sia via API con tool calling nativo.
**Rischi:** **emulazione del tool calling (RISCHIO #1, il più alto).** Modelli deboli che non rispettano
l'output strutturato. Mitigazione: prototipo isolato già in Fase 4a su un modello locale piccolo, con
parsing robusto + retry guidato; la reversibilità (principio 6) ci lascia "provare" senza rischio.

### Fase 5 — Agente a due marce + bootstrap di distribuzione
**Cosa:** `agent.py` con marcia diretta e marcia progetto (piano a passi + loop agisci/osserva/correggi);
installer di primo avvio (venv motore o eseguibile self-contained, download modello / API key); `package.xml`
per l'Addon Manager.
**Milestone:** "smussa questo spigolo" (diretta) e "progetta una staffa semplice" (progetto) end-to-end su
almeno un OS; installazione pulita da zero.
**Rischi:** distribuzione cross-platform del motore senza Python di sistema; robustezza della marcia progetto.

### Fase 6 — Indurimento, degrado con grazia, cross-platform completo
**Cosa:** test su Windows/macOS/Linux; degrado con grazia sui modelli deboli; disambiguazione autonoma con
evidenziazione a schermo; tolleranza al nonsense; documentazione utente.
**Milestone:** release pubblica 0.1 su GitHub.

---

## 5. Prima fase eseguibile (cosa costruiamo per primo e perché)

**Costruiamo la Fase 1 — lo scheletro: ponte + executor + transazioni, senza alcuna AI.**

**Perché questa e non l'agente o gli adattatori:**
1. È il **giunto strutturale** su cui poggia tutto il resto: senza un ponte funzionante e un executor
   transazionale, né percezione né presa né agente hanno dove appoggiarsi.
2. Affronta subito il **RISCHIO #2 (meccanica del ponte)**, finora rimandato più volte nel brainstorming.
   Meglio scoprire ora i problemi di threading Qt / socket / riconnessione che dopo aver costruito l'agente.
3. È **dimostrabile e testabile senza modello**: un client di test invia comandi JSON; non dipendiamo da
   Ollama, da una GPU o da una API key per validare il cuore del sistema.
4. Rende immediatamente concreta la **reversibilità** (principio 6): la prima cosa che funziona è anche la
   prima rete di sicurezza.

**Sotto-passo di apertura (Fase 1a), il vero primo pezzo di codice:** un prototipo *standalone* del solo
ponte — server JSON-RPC nel motore-finto + client nell'addon — che fa viaggiare un "ping/pong" e un comando
banale (`crea_box`) dentro una transazione annullabile. Niente UI elaborata, niente vocabolario completo:
solo la prova che i due processi si parlano e che l'azione è reversibile in FreeCAD. Da lì cresciamo.

---

## 6. Riepilogo dei rischi principali (ordinati)

1. **Emulazione del tool calling (Fase 4)** — il punto tecnico più incerto. Isolato in prototipo dedicato.
2. **Meccanica del ponte (Fase 1)** — threading Qt + socket cross-platform. Affrontato per primo, da solo.
3. **Formato del contesto geometrico (Fase 3)** — saturazione del contesto dei modelli locali. Misurato empiricamente.
4. **Distribuzione del motore senza Python di sistema (Fase 5)** — fallback a eseguibile self-contained.
5. **Marcia progetto robusta (Fase 5)** — loop agisci/osserva/correggi che non diverge. Rete: reversibilità.

---

## 7. Decisioni in attesa di conferma di Marco

- **Ponte:** confermo TCP socket locale + JSON-RPC 2.0? (raccomandato)
- **Adattatore API da implementare per primo in Fase 4:** Anthropic o OpenAI?
- **OS bersaglio della prima validazione end-to-end (Fase 5):** Windows (la tua macchina) come default?
- **Modello locale di riferimento per i test** (es. via Ollama): ne hai già uno preferito/installato?

> **Nessun codice verrà scritto prima della tua approvazione di questo piano.**

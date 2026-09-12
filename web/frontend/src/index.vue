<template>
  <p v-if="fehler" class="fehler">{{ fehler }}</p>

  <!-- Suche: mittig, der Einstieg in die Seite -->
  <section class="suche">
    <h1>hostingdb</h1>
    <div class="feld">
      <input
        ref="eingabe"
        v-model="begriff"
        type="search"
        autocomplete="off"
        placeholder="Domain, Kunde, Anbieter, Dienst oder Nameserver suchen …"
        @input="sucheAnstossen"
        @keydown.enter="erstenTrefferOeffnen"
        @keydown.esc="treffer = []">
      <ul v-if="treffer.length" class="treffer">
        <li v-for="t in treffer" :key="t.typ + '/' + t.id" @click="detailOeffnen(t)">
          <span class="label">{{ t.label }}</span>
          <span class="art">{{ t.art }}</span>
        </li>
      </ul>
    </div>
    <p class="notiz">
      <template v-if="sucheLaeuft">sucht …</template>
      <template v-else-if="suche.cache">
        {{ treffer.length }} Treffer ·
        <span class="herkunft" :class="{ hit: suche.cache.treffer }">
          {{ suche.cache.treffer ? 'Redis' : 'PostgreSQL' }} {{ suche.ms }} ms
        </span>
      </template>
      <template v-else>
        Mindestens zwei Zeichen. Dieselbe Suche ein zweites Mal kommt aus Redis —
        die Millisekunden daneben zeigen den Unterschied.
      </template>
    </p>
  </section>

  <!-- Datenbank: ein Tab je Tabelle -->
  <section class="datenbank">
    <header>
      <h2>Datenbank</h2>
      <span v-if="tabellen_.cache" class="herkunft" :class="{ hit: tabellen_.cache.treffer }">
        {{ tabellen_.cache.treffer ? 'Redis' : 'PostgreSQL' }} {{ tabellen_.ms }} ms
      </span>
      <button class="rechts" @click="cacheLeeren">Cache leeren</button>
    </header>

    <nav class="tabs">
      <button
        v-for="t in tabellen"
        :key="t.name"
        :class="{ aktiv: t.name === aktiveTabelle }"
        @click="tabelleOeffnen(t.name)">
        {{ t.label }}
        <span class="zahl">{{ zahl(t.zeilen) }}</span>
      </button>
    </nav>

    <div v-if="tabelle" class="inhalt">
      <div class="blaettern">
        <button :disabled="tabelle.offset === 0" @click="blaettern(-1)">◀ zurück</button>
        <span>
          Zeile {{ zahl(tabelle.offset + 1) }}–{{ zahl(tabelle.offset + tabelle.zeilen.length) }}
          von {{ zahl(zeilenZahl(tabelle.name)) }}
        </span>
        <button :disabled="!weitereSeite" @click="blaettern(1)">weiter ▶</button>
        <span v-if="tabelle.cache" class="herkunft" :class="{ hit: tabelle.cache.treffer }">
          {{ tabelle.cache.treffer ? 'Redis' : 'PostgreSQL' }} {{ tabelleMs }} ms
        </span>
      </div>

      <div class="scroll">
        <table>
          <thead>
            <tr><th v-for="s in tabelle.spalten" :key="s">{{ s }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="(z, i) in tabelle.zeilen" :key="i">
              <td v-for="s in tabelle.spalten" :key="s">{{ z[s] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <p v-else class="notiz">Einen Tab wählen, um die Tabelle anzusehen.</p>
  </section>

  <!-- Output: alles zum gesuchten Element, und woher die Antwort kam -->
  <section v-if="detail" class="output">
    <header>
      <h2>{{ detail.titel }}</h2>
      <span class="art">{{ detail.art }}</span>
      <button class="rechts" @click="erneutLaden(false)">ohne Cache laden</button>
      <button @click="detail = null">schliessen</button>
    </header>

    <!-- Das ist die Zahl, um die es im Labor geht. -->
    <div class="messung" :class="{ hit: detail.cache.treffer }">
      <span class="gross">
        {{ detail.cache.treffer ? 'Redis' : 'PostgreSQL' }}
        <b>{{ detailMs }} ms</b>
      </span>
      <span v-if="detail.cache.treffer" class="vergleich">
        PostgreSQL brauchte dafür {{ detail.cache.ms_postgres }} ms
        — <b>{{ beschleunigung }}× schneller</b>
      </span>
      <span v-else class="vergleich">
        aus der Datenbank gelesen und für {{ ttlText }} in Redis abgelegt.
        Jetzt dieselbe Suche noch einmal.
      </span>
      <span v-if="detail.cache.hinweis" class="vergleich">({{ detail.cache.hinweis }})</span>
    </div>

    <div v-for="b in detail.bloecke" :key="b.titel" class="block">
      <h3>{{ b.titel }}</h3>
      <p v-if="!b.zeilen.length" class="notiz">keine Einträge</p>
      <div v-else class="scroll">
        <table>
          <thead>
            <tr><th v-for="s in b.spalten" :key="s">{{ s }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="(z, i) in b.zeilen" :key="i">
              <td v-for="s in b.spalten" :key="s">{{ z[s] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>

  <footer>
    <a href="/report">Cache-Aside-Bericht</a> ·
    <a href="/report?nocache">Bericht ohne Cache</a>
  </footer>
</template>


<script>
// Alle Daten kommen aus /api/* in app.py. Jede Antwort traegt zwei Angaben, um
// die es in diesem Labor geht: "ms" (wie lange der Aufruf gedauert hat) und
// "cache" (ob die Antwort aus Redis kam und wie lange PostgreSQL dafuer
// gebraucht hatte). Die Seite zeigt beides an.

// Jede API-Antwort hat entweder die Nutzdaten oder einen Schluessel "fehler".
// Einmal auspacken heisst: keine der Methoden unten braucht eigene Fehlerlogik.
async function hole(pfad) {
  const antwort = await fetch(pfad);
  const daten = await antwort.json();
  if (daten.fehler) throw new Error(daten.fehler);
  return daten;
}

// Dasselbe als POST. Den Cache zu leeren veraendert etwas und gehoert deshalb
// nicht auf ein GET.
async function sende(pfad) {
  const antwort = await fetch(pfad, { method: 'POST' });
  const daten = await antwort.json();
  if (daten.fehler) throw new Error(daten.fehler);
  return daten;
}

export default {
  name: 'DatenbankBrowser',

  data() {
    return {
      // Tabs. Der Unterstrich trennt die Kennzahlen von der Liste selbst.
      tabellen: [],
      tabellen_: { cache: null, ms: null },
      aktiveTabelle: null,
      tabelle: null,
      tabelleMs: null,
      // Suche
      begriff: '',
      treffer: [],
      suche: { cache: null, ms: null },
      sucheLaeuft: false,
      // Output
      detail: null,
      detailMs: null,
      detailTreffer: null,
      fehler: null,
      ttlSekunden: null,
    };
  },

  computed: {
    // Eine weitere Seite gibt es, solange die aktuelle voll war.
    weitereSeite() {
      return this.tabelle && this.tabelle.zeilen.length === this.tabelle.limit;
    },

    // Um welchen Faktor war Redis schneller. Der Nenner wird nach unten
    // begrenzt, weil ein Treffer durchaus unter 0,1 ms liegen kann.
    // Die TTL kommt aus ansible/group_vars/all.yml und wird mitgeliefert.
    ttlText() {
      if (!this.ttlSekunden) return 'die Dauer der TTL';
      const minuten = Math.round(this.ttlSekunden / 60);
      return minuten >= 1 ? `${minuten} Minuten` : `${this.ttlSekunden} Sekunden`;
    },

    beschleunigung() {
      if (!this.detail || !this.detail.cache.treffer) return null;
      return Math.round(this.detail.cache.ms_postgres / Math.max(this.detailMs, 0.1));
    },
  },

  mounted() {
    this.tabellenLaden();
    this.$refs.eingabe.focus();
  },

  methods: {
    zahl(wert) {
      return typeof wert === 'number' ? wert.toLocaleString('de-CH') : wert;
    },

    zeilenZahl(name) {
      const treffer = this.tabellen.find((t) => t.name === name);
      return treffer ? treffer.zeilen : 0;
    },

    // ?nocache haengt an jedem Endpunkt und geht an Redis vorbei.
    pfad(basis, mitCache) {
      if (mitCache) return basis;
      return basis + (basis.includes('?') ? '&' : '?') + 'nocache';
    },

    async tabellenLaden(mitCache = true) {
      try {
        const daten = await hole(this.pfad('/api/tables', mitCache));
        this.tabellen = daten.tabellen;
        this.tabellen_ = { cache: daten.cache, ms: daten.ms };
        this.ttlSekunden = daten.ttl_sekunden;
      } catch (fehler) {
        this.fehler = `Tabellen konnten nicht geladen werden: ${fehler.message}`;
      }
    },

    async tabelleOeffnen(name, offset = 0) {
      this.fehler = null;
      try {
        const daten = await hole(`/api/table/${name}?offset=${offset}`);
        this.aktiveTabelle = name;
        this.tabelle = daten;
        this.tabelleMs = daten.ms;
      } catch (fehler) {
        this.fehler = `Tabelle ${name}: ${fehler.message}`;
      }
    },

    blaettern(richtung) {
      const ziel = this.tabelle.offset + richtung * this.tabelle.limit;
      this.tabelleOeffnen(this.tabelle.name, Math.max(0, ziel));
    },

    // Jeder Tastendruck wuerde eine Suche ueber eine Million Zeilen ausloesen.
    // Darum erst 350 ms nach dem letzten Zeichen losschicken.
    sucheAnstossen() {
      clearTimeout(this.timer);
      if (this.begriff.trim().length < 2) {
        this.treffer = [];
        this.suche = { cache: null, ms: null };
        return;
      }
      this.timer = setTimeout(() => this.suchen(), 350);
    },

    async suchen() {
      const begriff = this.begriff.trim();
      this.sucheLaeuft = true;
      this.fehler = null;
      try {
        const daten = await hole(`/api/search?q=${encodeURIComponent(begriff)}`);
        // Eine aeltere, langsamere Antwort darf eine neuere nicht ueberschreiben.
        if (daten.begriff !== this.begriff.trim()) return;
        this.treffer = daten.treffer;
        this.suche = { cache: daten.cache, ms: daten.ms };
      } catch (fehler) {
        this.fehler = `Suche fehlgeschlagen: ${fehler.message}`;
      } finally {
        this.sucheLaeuft = false;
      }
    },

    erstenTrefferOeffnen() {
      clearTimeout(this.timer);
      if (this.treffer.length) {
        this.detailOeffnen(this.treffer[0]);
      } else {
        this.suchen();
      }
    },

    async detailOeffnen(treffer, mitCache = true) {
      this.treffer = [];
      this.fehler = null;
      this.detailTreffer = treffer;
      try {
        const basis = `/api/detail/${treffer.typ}/${encodeURIComponent(treffer.id)}`;
        const daten = await hole(this.pfad(basis, mitCache));
        this.detail = daten;
        this.detailMs = daten.ms;
        this.$nextTick(() => {
          document.querySelector('.output').scrollIntoView({ behavior: 'smooth' });
        });
      } catch (fehler) {
        this.fehler = `${treffer.label}: ${fehler.message}`;
      }
    },

    erneutLaden(mitCache) {
      if (this.detailTreffer) this.detailOeffnen(this.detailTreffer, mitCache);
    },

    // Leert den Cache, ohne die Seite zu verlassen, und laedt danach die
    // Zeilenzahlen neu -- dann ist der Effekt sofort an ihnen abzulesen.
    async cacheLeeren() {
      this.fehler = null;
      try {
        const daten = await sende('/api/cache/clear');
        this.detail = null;
        this.tabelle = null;
        this.aktiveTabelle = null;
        this.suche = { cache: null, ms: null };
        this.treffer = [];
        await this.tabellenLaden();
        this.fehler = `Cache geleert: ${daten.entfernt} Schlüssel entfernt. ` +
          'Der nächste Aufruf geht wieder an PostgreSQL.';
      } catch (fehler) {
        this.fehler = `Cache leeren fehlgeschlagen: ${fehler.message}`;
      }
    },
  },
};
</script>


<style>
/* Nicht scoped: die Regeln fuer body und :root gelten fuer die ganze Seite. */

:root {
  --rand: #dcdcdc;
  --grund: #ffffff;
  --dezent: #f6f6f6;
  --text: #1f1f1f;
  --still: #6b6b6b;
  --akzent: #1f5fa9;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  padding: 0 1rem 4rem;
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
  color: var(--text);
  background: var(--grund);
  line-height: 1.45;
}

h1, h2, h3 { margin: 0; font-weight: 600; }
h1 { font-size: 1.6rem; letter-spacing: 0.02em; }
h2 { font-size: 1.05rem; }
h3 { font-size: 0.9rem; color: var(--still); text-transform: uppercase; letter-spacing: 0.06em; }

.notiz { margin: 0; color: var(--still); font-size: 0.82rem; }
.rechts { margin-left: auto; }

.fehler {
  max-width: 60rem;
  margin: 1rem auto 0;
  padding: 0.7rem 1rem;
  border: 1px solid #e3b4b4;
  border-radius: 6px;
  background: #fdf1f1;
  font-size: 0.88rem;
}

/* ----------------------------------------------------------------- Suche */

.suche {
  max-width: 40rem;
  margin: 0 auto;
  padding: 3.5rem 0 2.5rem;
  text-align: center;
}

.suche .feld { position: relative; margin-top: 1.2rem; }

.suche input {
  width: 100%;
  padding: 0.8rem 1rem;
  border: 1px solid var(--rand);
  border-radius: 8px;
  font: inherit;
  font-size: 1rem;
  background: var(--grund);
}

.suche input:focus {
  outline: none;
  border-color: var(--akzent);
  box-shadow: 0 0 0 3px rgba(31, 95, 169, 0.12);
}

.treffer {
  position: absolute;
  z-index: 5;
  left: 0;
  right: 0;
  margin: 0.3rem 0 0;
  padding: 0.25rem;
  list-style: none;
  text-align: left;
  border: 1px solid var(--rand);
  border-radius: 8px;
  background: var(--grund);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.09);
}

.treffer li {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  padding: 0.45rem 0.6rem;
  border-radius: 5px;
  cursor: pointer;
}

.treffer li:hover { background: var(--dezent); }
.treffer .label { font-weight: 500; }

.art {
  color: var(--still);
  font-size: 0.78rem;
  white-space: nowrap;
}

.suche .notiz { margin-top: 0.8rem; }

/* ------------------------------------------------------------- Datenbank */

.datenbank, .output {
  max-width: 72rem;
  margin: 0 auto 2rem;
  border: 1px solid var(--rand);
  border-radius: 10px;
  overflow: hidden;
}

.datenbank > header, .output > header {
  display: flex;
  align-items: baseline;
  gap: 0.9rem;
  padding: 0.75rem 1rem;
  background: var(--dezent);
  border-bottom: 1px solid var(--rand);
}

.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--rand);
}

.tabs button {
  display: flex;
  align-items: baseline;
  gap: 0.45rem;
  padding: 0.4rem 0.75rem;
  border: 1px solid var(--rand);
  border-radius: 999px;
  background: var(--grund);
  font: inherit;
  font-size: 0.88rem;
  cursor: pointer;
}

.tabs button:hover { border-color: var(--akzent); }

.tabs button.aktiv {
  border-color: var(--akzent);
  background: var(--akzent);
  color: #fff;
}

.tabs .zahl {
  font-size: 0.75rem;
  font-variant-numeric: tabular-nums;
  opacity: 0.7;
}

.inhalt { padding: 0.9rem 1rem 1rem; }

.blaettern {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  margin-bottom: 0.7rem;
  font-size: 0.85rem;
}

button {
  padding: 0.3rem 0.7rem;
  border: 1px solid var(--rand);
  border-radius: 6px;
  background: var(--grund);
  font: inherit;
  font-size: 0.85rem;
  cursor: pointer;
}

button:disabled { opacity: 0.4; cursor: default; }

/* --------------------------------------------------------------- Tabellen */

/* Die Tabellen sind breiter als das Fenster; nur sie scrollen, nicht die Seite. */
.scroll { overflow-x: auto; }

table { border-collapse: collapse; font-size: 0.85rem; }

th, td {
  padding: 0.32rem 0.7rem;
  border: 1px solid var(--rand);
  text-align: left;
  white-space: nowrap;
}

th { background: var(--dezent); font-weight: 600; }
td { font-variant-numeric: tabular-nums; }
tbody tr:hover { background: #fafbfd; }

/* ------------------------------------------------------- Herkunft der Daten */

/* Der kompakte Hinweis neben Suche, Tabs und Tabelle. */
.herkunft {
  padding: 0.1rem 0.45rem;
  border-radius: 999px;
  background: #f0ead8;
  color: #6a5a20;
  font-size: 0.78rem;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.herkunft.hit {
  background: #dcf0e2;
  color: #1c5c33;
}

/* Die grosse Anzeige im Ausgabefeld: darum geht es im Labor. */
.messung {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.5rem 1rem;
  padding: 0.8rem 1rem;
  background: #fbf7ec;
  border-bottom: 1px solid var(--rand);
}

.messung.hit { background: #f0faf3; }

.messung .gross {
  font-size: 1.15rem;
  color: #6a5a20;
  font-variant-numeric: tabular-nums;
}

.messung.hit .gross { color: #1c5c33; }
.messung .gross b { font-weight: 700; }
.messung .vergleich { color: var(--still); font-size: 0.85rem; }
.messung .vergleich b { color: var(--text); }

/* ---------------------------------------------------------------- Output */

.output { border-color: var(--akzent); }
.output > header { background: rgba(31, 95, 169, 0.07); }
.output .block { padding: 0.9rem 1rem; border-top: 1px solid var(--rand); }
.output .block h3 { margin-bottom: 0.5rem; }

footer {
  max-width: 72rem;
  margin: 0 auto;
  font-size: 0.85rem;
}

footer a { color: var(--akzent); }
</style>

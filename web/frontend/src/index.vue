<template>
  <p v-if="meldung" class="meldung" :class="meldung.art">
    {{ meldung.text }}
    <button class="schliessen" @click="meldung = null">×</button>
  </p>

  <!-- Kopf: worum es geht, in einem Satz -->
  <header class="kopf">
    <h1>DB Cache Benchmark <span>PostgreSQL mit und ohne Redis-Cache</span></h1>
    <p class="notiz">
      {{ zahl(summeZeilen) }} Zeilen in PostgreSQL, keine Sekundärindizes.
      Dieselbe Auswertung links direkt aus der Datenbank, rechts über den Cache.
    </p>
    <div class="weg">
      <span>Browser</span><i>→</i><span>web</span><i>→</i>
      <span class="redis">Redis</span><i>→ bei Miss →</i><span class="pg">PostgreSQL</span>
    </div>
  </header>

  <!-- 1. Filter: jede Kombination ist ein eigener Cache-Eintrag -->
  <section class="karte filter">
    <!-- Filter und Aktionen in einer Zeile; der Cache-Schluessel darunter. -->
    <div class="zeile">
      <label>
        <span class="titel">Hoster</span>
        <select v-model="filter.hoster">
          <option value="">alle</option>
          <option v-for="a in anbieter" :key="a.id" :value="String(a.id)">{{ a.name }}</option>
        </select>
      </label>

      <div>
        <span class="titel">Dienste</span>
        <div class="pillen">
          <button
            v-for="d in dienste"
            :key="d.code"
            :class="{ aktiv: filter.dienste.includes(d.code) }"
            @click="dienstUmschalten(d.code)">
            {{ d.bezeichnung }}
          </button>
        </div>
      </div>

      <div class="dehnbar">
        <span class="titel">Ablauf</span>
        <div class="pillen">
          <button
            v-for="[wert, text] in ABLAUF"
            :key="wert"
            :class="{ aktiv: filter.ablauf === wert }"
            @click="filter.ablauf = wert">
            {{ text }}
          </button>
        </div>
      </div>

      <div class="aktionen">
        <!-- Beide Icons im selben Strichstil: 24er-Raster, Linie in Textfarbe. -->
        <button class="primaer mit-icon" :disabled="laeuft" @click="auswerten()">
          <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></svg>
          Auswerten
        </button>
        <button class="mit-icon" @click="cacheLeeren">
          <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="M19 6l-1 14H6L5 6" /><path d="M10 11v5M14 11v5" /></svg>
          Cache leeren
        </button>
      </div>
    </div>

    <p class="schluessel">
      Cache-Schlüssel <code>{{ cacheSchluessel }}</code>
      <span v-if="bekannt.has(cacheSchluessel)" class="herkunft hit">schon einmal abgefragt</span>
      <span v-else class="herkunft">neu, der erste Aufruf wird ein Miss</span>
    </p>
  </section>

  <!-- 2. Split-Screen: das Bild, um das es geht -->
  <p v-if="faktor" class="faktor">
    Redis war <b>{{ zahl(faktor) }}× schneller</b>
    <span>{{ zahl(seiten.ohne.ms) }} ms gegenüber {{ zahl(seiten.mit.ms) }} ms</span>
  </p>

  <section class="vergleich">
    <article
      v-for="(seite, key) in seiten"
      :key="key"
      class="karte spalte"
      :class="[key, { hit: seite.cache && seite.cache.treffer }]">
      <header>
        <h2>{{ seite.titel }}</h2>
        <span class="notiz">{{ seite.untertitel }}</span>
      </header>

      <div class="zeit">
        <template v-if="seite.laeuft">{{ zahl(seite.live) }} <small>ms …</small></template>
        <template v-else-if="seite.ms !== null">{{ zahl(seite.ms) }} <small>ms</small></template>
        <template v-else>– <small>ms</small></template>
      </div>
      <div class="balken">
        <div :class="{ laeuft: seite.laeuft }" :style="{ width: balkenBreite(seite) }"></div>
      </div>

      <p class="status">
        <template v-if="seite.laeuft">wartet auf die Antwort …</template>
        <template v-else-if="!seite.cache">noch nicht abgefragt</template>
        <template v-else-if="key === 'ohne'">
          <span class="herkunft">PostgreSQL</span> Cache übersprungen, jedes Mal der volle Weg
        </template>
        <template v-else-if="seite.cache.treffer">
          <span class="herkunft hit">Redis-Treffer</span>
          vor {{ seite.cache.alter_s }} s gespeichert, noch {{ seite.cache.rest_s }} s gültig
        </template>
        <template v-else>
          <span class="herkunft">Miss</span>
          aus PostgreSQL gelesen und für {{ ttlText }} in Redis abgelegt
        </template>
        <template v-if="key === 'mit' && seite.cache && seite.cache.hinweis"> ({{ seite.cache.hinweis }})</template>
      </p>

      <template v-if="seite.daten">
        <div class="kacheln">
          <div v-for="k in KENNZAHLEN" :key="k.feld" :class="{ anders: anders('k', k.feld) }">
            <b>{{ zahl(seite.daten.kennzahlen[k.feld], k.chf) }}</b>
            <span>{{ k.text }}</span>
          </div>
        </div>

        <div v-for="(b, bi) in seite.daten.bloecke" :key="b.titel" class="block">
          <h3>{{ b.titel }}</h3>
          <div class="scroll">
            <table>
              <thead>
                <tr><th v-for="s in b.spalten" :key="s">{{ s }}</th></tr>
              </thead>
              <tbody>
                <tr v-for="(z, zi) in b.zeilen" :key="zi">
                  <td v-for="s in b.spalten" :key="s" :class="{ anders: anders(bi, zi, s) }">
                    {{ zahl(z[s], s.endsWith('chf')) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </article>
  </section>

  <!-- 3. Konsistenz: was passiert, wenn jemand schreibt -->
  <p v-if="unterschiede.size" class="warnung">
    <span>
      <b>Die beiden Seiten widersprechen sich.</b>
      PostgreSQL hat einen neuen Preis, Redis liefert noch den Stand von vor
      {{ seiten.mit.cache.alter_s }} s, und zwar weitere {{ seiten.mit.cache.rest_s }} s lang.
    </span>
    <button @click="preiseInvalidieren">Betroffene Einträge invalidieren</button>
  </p>

  <section class="karte konsistenz">
    <header>
      <h2>Schreiben: einen Preis ändern</h2>
    </header>
    <p class="notiz">
      Cache-Aside liest nur. Wer in PostgreSQL schreibt, muss die betroffenen
      Einträge in Redis selbst verwerfen, sonst liefert der Cache bis zum Ablauf
      der TTL den alten Wert. Nach dem Speichern läuft die Auswertung oben neu.
    </p>

    <table class="preise">
      <thead>
        <tr><th>Dienst</th><th>Bezeichnung</th><th>Preis / Monat (CHF)</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="d in dienste" :key="d.code">
          <td>{{ d.code }}</td>
          <td>{{ d.bezeichnung }}</td>
          <td>
            <input v-model="neuePreise[d.code]" type="number" min="0" step="0.5"
                   @keydown.enter="preisSpeichern(d.code)">
            <span v-if="originalPreise[d.code] !== d.preis_monat" class="notiz">
              ursprünglich {{ zahl(originalPreise[d.code], true) }}
            </span>
          </td>
          <td>
            <button :disabled="Number(neuePreise[d.code]) === d.preis_monat"
                    @click="preisSpeichern(d.code)">speichern</button>
          </td>
        </tr>
      </tbody>
    </table>

    <div class="optionen">
      <label class="haken">
        <input v-model="invalidierenBeimSchreiben" type="checkbox">
        Cache beim Schreiben invalidieren
      </label>
      <button v-if="preiseGeaendert" @click="preiseZuruecksetzen">Preise zurücksetzen</button>
    </div>
  </section>

  <!-- 4. Die Rohdaten: ein Tab je Tabelle -->
  <section class="karte datenbank">
    <header>
      <h2>Datenbank</h2>
      <span v-if="tabellen_.cache" class="herkunft" :class="{ hit: tabellen_.cache.treffer }">
        {{ tabellen_.cache.treffer ? 'Redis' : 'PostgreSQL' }} {{ tabellen_.ms }} ms
      </span>
    </header>

    <nav class="tabs">
      <button
        v-for="t in tabellen"
        :key="t.name"
        :class="{ aktiv: t.name === aktiveTabelle }"
        @click="tabUmschalten(t.name)">
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
    <p v-else class="notiz inhalt">Einen Tab wählen, um die Tabelle anzusehen.</p>
  </section>
</template>


<script>
// Alle Daten kommen aus /api/* in app.py. Jede Antwort traegt zwei Angaben, um
// die es in diesem Labor geht: "ms" (wie lange der Aufruf gedauert hat) und
// "cache" (ob die Antwort aus Redis kam, wie lange PostgreSQL dafuer gebraucht
// hatte und wie alt der Eintrag ist).

// Jede API-Antwort hat entweder die Nutzdaten oder einen Schluessel "fehler".
// Einmal auspacken heisst: keine der Methoden unten braucht eigene Fehlerlogik.
async function hole(pfad) {
  const antwort = await fetch(pfad);
  const daten = await antwort.json();
  if (daten.fehler) throw new Error(daten.fehler);
  return daten;
}

// Dasselbe als POST. Was etwas veraendert, gehoert nicht auf ein GET.
async function sende(pfad, inhalt = {}) {
  const antwort = await fetch(pfad, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(inhalt),
  });
  const daten = await antwort.json();
  if (daten.fehler) throw new Error(daten.fehler);
  return daten;
}

function leereSeite(titel, untertitel) {
  return { titel, untertitel, laeuft: false, live: 0, ms: null, cache: null, daten: null };
}

export default {
  name: 'CacheVergleich',

  data() {
    return {
      // Filter und was sie anbieten
      anbieter: [],
      dienste: [],
      filter: { hoster: '', dienste: [], ablauf: 'alle' },
      // Die beiden Seiten des Vergleichs
      seiten: {
        ohne: leereSeite('Ohne Redis', 'direkt aus PostgreSQL, ?nocache'),
        mit: leereSeite('Mit Redis', 'Cache-Aside: zuerst Redis, bei Miss PostgreSQL'),
      },
      // Schluessel, die diese Seite schon einmal abgefragt hat. Nur eine
      // Orientierung fuer das Publikum; massgebend ist, was Redis antwortet.
      bekannt: new Set(),
      // Preise
      neuePreise: {},
      originalPreise: {},
      invalidierenBeimSchreiben: false,
      // Datenbank-Browser
      tabellen: [],
      tabellen_: { cache: null, ms: null },
      aktiveTabelle: null,
      tabelle: null,
      tabelleMs: null,
      // Allgemein
      meldung: null,
      ttlSekunden: null,
    };
  },

  created() {
    // Die Werte, die app.py fuer 'ablauf' annimmt. Eine Liste statt eines
    // Objekts, weil ein Objekt Zahlen-Schluessel vor die anderen sortiert.
    this.ABLAUF = [
      ['alle', 'alle'],
      ['abgelaufen', 'abgelaufen'],
      ['30', '30 Tage'],
      ['90', '90 Tage'],
      ['365', '1 Jahr'],
    ];
    this.KENNZAHLEN = [
      { feld: 'domains', text: 'Domains' },
      { feld: 'kunden', text: 'Kunden' },
      { feld: 'zuordnungen', text: 'Dienste' },
      { feld: 'monatlich_chf', text: 'CHF / Monat', chf: true },
    ];
  },

  computed: {
    laeuft() {
      return this.seiten.ohne.laeuft || this.seiten.mit.laeuft;
    },

    abfrage() {
      const teile = new URLSearchParams();
      if (this.filter.hoster) teile.set('hoster', this.filter.hoster);
      if (this.filter.dienste.length) teile.set('dienste', this.filter.dienste.join(','));
      teile.set('ablauf', this.filter.ablauf);
      return `/api/auswertung?${teile}`;
    },

    // Dieselbe Normalform wie in app.py, damit das Publikum den Schluessel
    // sieht, unter dem Redis die Antwort ablegt.
    cacheSchluessel() {
      const dienste = [...this.filter.dienste].sort().join(',') || 'alle';
      return `auswertung:${this.filter.hoster || 'alle'}:${dienste}:${this.filter.ablauf}`;
    },

    // Nur ein Treffer ist ein fairer Vergleich; ein Miss ist auf beiden Seiten
    // gleich langsam.
    faktor() {
      const { ohne, mit } = this.seiten;
      if (this.laeuft || !mit.cache || !mit.cache.treffer || ohne.ms === null) return null;
      return Math.round(ohne.ms / Math.max(mit.ms, 0.1));
    },

    // Jede Zelle, in der die beiden Seiten verschiedene Werte zeigen. Beide
    // Anfragen hatten denselben Filter, also dieselben Zeilen in derselben
    // Reihenfolge; ein Unterschied kann nur aus einem veralteten Eintrag kommen.
    unterschiede() {
      const a = this.seiten.ohne.daten;
      const b = this.seiten.mit.daten;
      const menge = new Set();
      if (!a || !b || this.laeuft) return menge;
      for (const feld in a.kennzahlen) {
        if (a.kennzahlen[feld] !== b.kennzahlen[feld]) menge.add(`k/${feld}`);
      }
      a.bloecke.forEach((block, bi) => {
        block.zeilen.forEach((zeile, zi) => {
          const andere = (b.bloecke[bi] && b.bloecke[bi].zeilen[zi]) || {};
          for (const spalte in zeile) {
            if (zeile[spalte] !== andere[spalte]) menge.add(`${bi}/${zi}/${spalte}`);
          }
        });
      });
      return menge;
    },

    preiseGeaendert() {
      return this.dienste.some((d) => this.originalPreise[d.code] !== d.preis_monat);
    },

    summeZeilen() {
      return this.tabellen.reduce((summe, t) => summe + t.zeilen, 0);
    },

    // Wie in der Datenbank-Ansicht: eine weitere Seite gibt es, solange die
    // aktuelle voll war.
    weitereSeite() {
      return this.tabelle && this.tabelle.zeilen.length === this.tabelle.limit;
    },

    // Die TTL kommt aus ansible/group_vars/all.yml und wird mitgeliefert.
    ttlText() {
      if (!this.ttlSekunden) return 'die Dauer der TTL';
      const minuten = Math.round(this.ttlSekunden / 60);
      return minuten >= 1 ? `${minuten} Minuten` : `${this.ttlSekunden} Sekunden`;
    },
  },

  async mounted() {
    await Promise.all([this.optionenLaden(true), this.tabellenLaden()]);
  },

  methods: {
    zahl(wert, chf = false) {
      if (typeof wert !== 'number') return wert;
      return chf
        ? wert.toLocaleString('de-CH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : wert.toLocaleString('de-CH');
    },

    zeige(text, art = 'info') {
      this.meldung = { text, art };
    },

    anders(...pfad) {
      return this.unterschiede.has(pfad.join('/'));
    },

    // Beide Balken auf derselben Skala: der langsamere fuellt die Breite, der
    // schnellere bekommt seinen Anteil, mindestens aber einen sichtbaren Strich.
    // Solange eine Seite noch laeuft, zaehlt ihre bisherige Wartezeit als
    // Massstab. So faellt der Balken der schnelleren Seite sofort auf seinen
    // Anteil zurueck, statt voll stehen zu bleiben, bis die andere fertig ist.
    balkenBreite(seite) {
      if (seite.laeuft) return '100%';
      if (seite.ms === null) return '0';
      const dauer = (s) => (s.laeuft ? s.live : s.ms || 0);
      const groesste = Math.max(dauer(this.seiten.ohne), dauer(this.seiten.mit));
      if (!groesste) return '0';
      return `${Math.min(Math.max((seite.ms / groesste) * 100, 0.6), 100)}%`;
    },

    dienstUmschalten(code) {
      const liste = this.filter.dienste;
      this.filter.dienste = liste.includes(code)
        ? liste.filter((d) => d !== code)
        : [...liste, code];
    },

    // ?nocache haengt an jedem Endpunkt und geht an Redis vorbei.
    pfad(basis, mitCache) {
      if (mitCache) return basis;
      return basis + (basis.includes('?') ? '&' : '?') + 'nocache';
    },

    // Beide Anfragen gehen gleichzeitig los. Bis die Antwort da ist, zaehlt die
    // Anzeige mit der Uhr des Browsers hoch; danach steht dort die Zeit, die
    // der Server gemessen hat -- ohne Netz und ohne Darstellung.
    // Nach dem Speichern eines Preises bleibt dessen Meldung stehen; ein Klick
    // auf 'Auswerten' raeumt sie weg.
    async auswerten(meldungBehalten = false) {
      if (this.laeuft) return;
      if (!meldungBehalten) this.meldung = null;
      const schluessel = this.cacheSchluessel;
      const abfrage = this.abfrage;

      const eineSeite = async (seite, mitCache) => {
        Object.assign(seite, { laeuft: true, live: 0, ms: null, cache: null, daten: null });
        const start = performance.now();
        const ticken = () => {
          if (!seite.laeuft) return;
          seite.live = Math.round(performance.now() - start);
          requestAnimationFrame(ticken);
        };
        requestAnimationFrame(ticken);
        try {
          const daten = await hole(this.pfad(abfrage, mitCache));
          Object.assign(seite, { ms: daten.ms, cache: daten.cache, daten });
        } catch (fehler) {
          this.zeige(`${seite.titel}: ${fehler.message}`, 'fehler');
        } finally {
          seite.laeuft = false;
        }
      };

      await Promise.all([
        eineSeite(this.seiten.ohne, false),
        eineSeite(this.seiten.mit, true),
      ]);
      this.bekannt = new Set([...this.bekannt, schluessel]);
    },

    async optionenLaden(ersterAufruf = false) {
      try {
        const daten = await hole('/api/optionen');
        this.anbieter = daten.anbieter;
        this.dienste = daten.dienste;
        this.ttlSekunden = daten.ttl_sekunden;
        for (const d of daten.dienste) {
          this.neuePreise[d.code] = d.preis_monat;
          if (ersterAufruf) this.originalPreise[d.code] = d.preis_monat;
        }
      } catch (fehler) {
        this.zeige(`Filter konnten nicht geladen werden: ${fehler.message}`, 'fehler');
      }
    },

    async preisSpeichern(code, neuLaden = true) {
      try {
        const daten = await sende(`/api/dienst/${encodeURIComponent(code)}/preis`, {
          preis: Number(this.neuePreise[code]),
          invalidieren: this.invalidierenBeimSchreiben,
        });
        if (!neuLaden) return;
        await this.optionenLaden();
        if (daten.invalidiert) {
          this.bekannt = new Set();
          this.zeige(`${code}: neuer Preis in PostgreSQL, ${daten.entfernt} Einträge in ` +
            'Redis verworfen. Beide Seiten zeigen wieder denselben Stand.', 'ok');
        } else {
          this.zeige(`${code}: neuer Preis nur in PostgreSQL. Redis weiss davon nichts ` +
            `und liefert rechts bis zum Ablauf der TTL den alten Wert.`, 'warn');
        }
        await this.auswerten(true);
      } catch (fehler) {
        this.zeige(`Preis speichern fehlgeschlagen: ${fehler.message}`, 'fehler');
      }
    },

    async preiseZuruecksetzen() {
      const vorher = this.invalidierenBeimSchreiben;
      this.invalidierenBeimSchreiben = true;
      try {
        for (const d of this.dienste) {
          if (this.originalPreise[d.code] === d.preis_monat) continue;
          this.neuePreise[d.code] = this.originalPreise[d.code];
          await this.preisSpeichern(d.code, false);
        }
        await sende('/api/cache/preise');
        this.bekannt = new Set();
        await this.optionenLaden();
        this.zeige('Ursprüngliche Preise wiederhergestellt und Cache invalidiert.', 'ok');
      } finally {
        this.invalidierenBeimSchreiben = vorher;
      }
    },

    async preiseInvalidieren() {
      try {
        const daten = await sende('/api/cache/preise');
        this.bekannt = new Set();
        this.zeige(`${daten.entfernt} Einträge mit Preisen aus Redis verworfen. ` +
          'Der nächste Aufruf liest wieder aus PostgreSQL.', 'ok');
        await this.auswerten(true);
      } catch (fehler) {
        this.zeige(`Invalidieren fehlgeschlagen: ${fehler.message}`, 'fehler');
      }
    },

    // Leert den Cache, ohne die Seite zu verlassen, und laedt danach die
    // Zeilenzahlen neu -- dann ist der Effekt sofort an ihnen abzulesen.
    async cacheLeeren() {
      try {
        const daten = await sende('/api/cache/clear');
        this.bekannt = new Set();
        this.tabelle = null;
        this.aktiveTabelle = null;
        this.seiten.ohne = leereSeite(this.seiten.ohne.titel, this.seiten.ohne.untertitel);
        this.seiten.mit = leereSeite(this.seiten.mit.titel, this.seiten.mit.untertitel);
        await this.tabellenLaden();
        this.zeige(`Cache geleert: ${daten.entfernt} Schlüssel entfernt. ` +
          'Der nächste Aufruf geht wieder an PostgreSQL.', 'ok');
      } catch (fehler) {
        this.zeige(`Cache leeren fehlgeschlagen: ${fehler.message}`, 'fehler');
      }
    },

    // ------------------------------------------------- Datenbank-Browser

    zeilenZahl(name) {
      const treffer = this.tabellen.find((t) => t.name === name);
      return treffer ? treffer.zeilen : 0;
    },

    async tabellenLaden(mitCache = true) {
      try {
        const daten = await hole(this.pfad('/api/tables', mitCache));
        this.tabellen = daten.tabellen;
        this.tabellen_ = { cache: daten.cache, ms: daten.ms };
      } catch (fehler) {
        this.zeige(`Tabellen konnten nicht geladen werden: ${fehler.message}`, 'fehler');
      }
    },

    // Ein Klick auf den aktiven Tab schliesst die Tabelle wieder.
    tabUmschalten(name) {
      if (name === this.aktiveTabelle) {
        this.aktiveTabelle = null;
        this.tabelle = null;
        return;
      }
      this.tabelleOeffnen(name);
    },

    async tabelleOeffnen(name, offset = 0) {
      try {
        const daten = await hole(`/api/table/${name}?offset=${offset}`);
        this.aktiveTabelle = name;
        this.tabelle = daten;
        this.tabelleMs = daten.ms;
      } catch (fehler) {
        this.zeige(`Tabelle ${name}: ${fehler.message}`, 'fehler');
      }
    },

    blaettern(richtung) {
      const ziel = this.tabelle.offset + richtung * this.tabelle.limit;
      this.tabelleOeffnen(this.tabelle.name, Math.max(0, ziel));
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
  --still: #111010;
  --akzent: #121313;
  --pg: #f0a21c;
  --pg-hell: #faaf46;
  --redis: #11e268;
  --redis-hell: #5af796;
  --rot: #df3019;
  --rot-hell: #ffb6ae;
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
h2 { font-size: 1.05rem; }
h3 { font-size: 0.8rem; color: var(--still); text-transform: none; }

.notiz { margin: 0; color: var(--still); font-size: 0.85rem; }
code { font-size: 0.85em; background: var(--dezent); padding: 0.1rem 0.35rem; border-radius: 4px; }

button {
  padding: 0.35rem 0.8rem;
  border: 1px solid var(--rand);
  border-radius: 6px;
  background: var(--grund);
  font: inherit;
  font-size: 0.88rem;
  cursor: pointer;
}

button:hover:not(:disabled) { border-color: var(--akzent); }
button:disabled { opacity: 0.4; cursor: default; }

button.primaer {
  border-color: var(--akzent);
  background: var(--akzent);
  color: #fff;
  font-weight: 600;
  padding: 0.5rem 1rem;
}

/* Icon links vom Text. stroke folgt der Schriftfarbe, darum passt dasselbe
   SVG auf den dunklen und den hellen Button. */
button.mit-icon {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  white-space: nowrap;
}

.icon {
  width: 1.05em;
  height: 1.05em;
  flex: none;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

select, input[type='number'] {
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--rand);
  border-radius: 6px;
  font: inherit;
  font-size: 0.9rem;
  background: var(--grund);
}

.karte {
  max-width: 76rem;
  margin: 0 auto 1.2rem;
  border: 1px solid var(--rand);
  border-radius: 10px;
  overflow: hidden;
}

.karte > header {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 0.4rem 0.9rem;
  padding: 0.75rem 1rem;
  background: var(--dezent);
  border-bottom: 1px solid var(--rand);
}

/* ------------------------------------------------------------ Meldungen */

.meldung, .warnung {
  max-width: 76rem;
  margin: 1rem auto;
  padding: 0.7rem 1rem;
  border: 1px solid #b9cde6;
  border-radius: 8px;
  background: #eef4fb;
  font-size: 0.9rem;
  display: flex;
  gap: 1rem;
  align-items: center;
}

.meldung .schliessen { margin-left: auto; border: 0; background: none; font-size: 1.1rem; }
.meldung.ok { border-color: #b5dcc3; background: var(--redis-hell); }
.meldung.warn { border-color: #ecd09a; background: var(--pg-hell); }
.meldung.fehler { border-color: #e3b4b4; background: var(--rot-hell); }

.warnung { border-color: var(--rot); background: var(--rot-hell); }
.warnung button { margin-left: auto; white-space: nowrap; border-color: var(--rot); }

/* ------------------------------------------------------------------ Kopf */

.kopf {
  max-width: 76rem;
  margin: 0 auto;
  padding: 2.2rem 0 1.4rem;
}

.kopf h1 { font-size: 1.7rem; }
.kopf h1 span { color: var(--still); font-weight: 400; margin-left: 0.4rem; }
.kopf .notiz { margin-top: 0.3rem; font-size: 0.95rem; }

.weg {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.8rem;
  font-size: 0.85rem;
}

.weg span {
  padding: 0.15rem 0.6rem;
  border: 1px solid var(--rand);
  border-radius: 999px;
}

.weg span.redis { border-color: var(--redis); color: var(--redis); }
.weg span.pg { border-color: var(--pg); color: var(--pg); }
.weg i { color: var(--still); font-style: normal; }

/* ---------------------------------------------------------------- Filter */

.filter { padding: 1rem; }

.filter .zeile {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 1rem 1.2rem;
}

/* Auf breiten Bildschirmen bleiben Filter und Buttons auf einer Linie. Wird
   es eng, bricht nur die Ablauf-Gruppe in sich um, nicht die ganze Zeile. */
@media (min-width: 64rem) {
  .filter .zeile { flex-wrap: nowrap; }
  .filter .zeile > * { flex: none; }
  .filter .zeile > .dehnbar { flex: 0 1 auto; min-width: 0; }
}

.filter .titel {
  display: block;
  margin-bottom: 0.35rem;
  font-size: 0.75rem;
  color: var(--still);
  text-transform: none;
  font-weight: 500;
}

.pillen { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.pillen button { border-radius: 999px; padding: 0.35rem 0.65rem; }
.pillen button.aktiv { border-color: var(--akzent); background: var(--akzent); color: #fff; }

.filter .aktionen { display: flex; flex: none; gap: 0.5rem; margin-left: auto; }

.filter .schluessel {
  margin: 1rem 0 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  color: var(--still);
}

/* ---------------------------------------------------------- Split-Screen */

.faktor {
  max-width: 76rem;
  margin: 0 auto 0.8rem;
  text-align: center;
  font-size: 1.5rem;
  color: #7a7a7a;
}

.faktor b { color: black; }
.faktor span { display: block; font-size: 0.85rem; color: var(--still); }

.vergleich {
  max-width: 76rem;
  margin: 0 auto 1.2rem;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
  gap: 1rem;
}

.vergleich .spalte { margin: 0; }
.spalte.ohne > header { background: var(--pg-hell); }
.spalte.mit > header { background: var(--pg-hell); }
.spalte.mit.hit > header { background: var(--redis-hell); }

.zeit {
  padding: 1rem 1rem 0.3rem;
  font-size: 2.8rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--pg);
  line-height: 1.1;
}

.spalte.hit .zeit { color: var(--redis); }
.zeit small { font-size: 1rem; font-weight: 400; color: var(--still); }

.balken {
  margin: 0 1rem;
  height: 0.7rem;
  border-radius: 999px;
  background: var(--dezent);
  overflow: hidden;
}

.balken > div {
  height: 100%;
  border-radius: 999px;
  background: var(--pg);
  transition: width 0.4s ease;
}

.spalte.hit .balken > div { background: var(--redis); }

.balken > div.laeuft {
  background: repeating-linear-gradient(-45deg, var(--pg) 0 10px, #ff8000 10px 20px);
  background-size: 28px 28px;
  animation: laufen 0.6s linear infinite;
  opacity: 0.6;
}

/* Beide Seiten laden in Orange: solange die Antwort fehlt, ist offen, ob es
   ein Treffer wird. Ein Treffer ist nach unter 1 ms da, sichtbar werden die
   Streifen rechts also praktisch nur bei einem Miss -- und der geht an
   PostgreSQL. Gruen wird der Balken erst mit .hit, wenn Redis geantwortet hat. */

@keyframes laufen { to { background-position: 28px 0; } }

.status {
  margin: 0;
  padding: 0.6rem 1rem 0.9rem;
  font-size: 0.85rem;
  color: var(--still);
  border-bottom: 1px solid var(--rand);
  min-height: 2.9rem;
}

.kacheln {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  border-bottom: 1px solid var(--rand);
}

.kacheln div {
  padding: 0.7rem 0.8rem;
  border-right: 1px solid var(--rand);
}

.kacheln div:last-child { border-right: 0; }
.kacheln b { display: block; font-size: 1.15rem; font-variant-numeric: tabular-nums; }
.kacheln span { font-size: 0.75rem; color: var(--still); }

.spalte .block { padding: 0.8rem 1rem; }
.spalte .block + .block { border-top: 1px solid var(--rand); }
.spalte .block h3 { margin-bottom: 0.45rem; }

/* Eine Zelle, in der Redis etwas anderes sagt als PostgreSQL. */
.anders {
  background: var(--rot-hell) !important;
  color: var(--rot);
  font-weight: 700;
}

/* ------------------------------------------------------------ Konsistenz */

.konsistenz > .notiz { padding: 0.8rem 1rem 0; max-width: 52rem; }
.konsistenz .preise { margin: 0.8rem 1rem; }
.konsistenz input[type='number'] { width: 7rem; margin-right: 0.5rem; }

.konsistenz .optionen {
  display: flex;
  align-items: center;
  gap: 1.2rem;
  padding: 0 1rem 1rem;
}

.haken { display: flex; align-items: center; gap: 0.4rem; font-size: 0.9rem; cursor: pointer; }

/* ------------------------------------------------------------- Datenbank */

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
  border-radius: 999px;
}

.tabs button.aktiv { border-color: var(--akzent); background: var(--akzent); color: #fff; }
.tabs .zahl { font-size: 0.75rem; font-variant-numeric: tabular-nums; opacity: 0.7; }

.inhalt { padding: 0.9rem 1rem 1rem; }

.blaettern {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  margin-bottom: 0.7rem;
  font-size: 0.85rem;
}

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

/* ------------------------------------------------------ Herkunft der Daten */

.herkunft {
  padding: 0.1rem 0.5rem;
  border-radius: 999px;
  background: #f0ead8;
  color: #6a5a20;
  font-size: 0.78rem;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.herkunft.hit { background: #dcf0e2; color: #1c5c33; }

</style>

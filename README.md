# db-cache-benchmark

Ein kleines Labor aus drei VMs, das zeigt, was ein **Cache-Aside-Muster mit
Redis** vor einer teuren Abfrage gegen **PostgreSQL** bewirkt.

![db-benchmark-scheme](/docs/db-benchmark-scheme.jpg)

Die Web-VM fragt zuerst Redis. Nur bei einem Cache-Miss geht sie an PostgreSQL 
und legt das Ergebnis auf dem Rückweg in Redis ab. **Jede** Antwort der Seite
nennt, woher sie kam und wie lange sie gebraucht hat und bei einem Treffer
zusätzlich, wie lange PostgreSQL dafür gebraucht hätte.

## Voraussetzungen

| Komponente | Anmerkung |
| ---------- | --------- |
| macOS auf Apple Silicon | arm64 |
| Parallels Desktop | Pro oder Business Edition |
| Vagrant + `vagrant-parallels` | `vagrant plugin install vagrant-parallels` |
| Ansible | läuft auf dem Host, nicht in den VMs |
| Collection `community.postgresql` | `ansible-galaxy collection install community.postgresql` |

Als Box dient `bento/debian-12`; deren Parallels-Image wird für arm64 veröffentlicht.

## Labor starten

```sh
vagrant up
```

Vagrant baut `pg`, `redis` und `web` in dieser Reihenfolge. Ansible läuft ein
einziges Mal, sobald `web` steht, und konfiguriert alle drei VMs. Darin auch
`npm ci` und `npm run build` für die Vue-Oberfläche.

Wer die Oberfläche häufig ändert, muss dafür nicht jedes Mal provisionieren. In `web/frontend/`,
`npm run dev` startet auf dem Host einen Vite-Server mit Hot Reload, der `/api`
an `192.168.56.12:8000` weiterleitet.

Danach im Browser:

```
http://192.168.56.12:8000
```

## Die Demo

![db-benchmark-demo](/docs/db-benchmark-demo.png)

Die Seite ist in drei Teile gegliedert: Filter, Split-Screen und Preis-Formular.

**Filter.** Hoster, Dienste und Ablaufzeitraum grenzen eine Auswertung über
`domain` und `domain_dienst` ein (1,5 Mio. Zeilen, keine Sekundärindizes).
Jede Kombination ist ein eigener Redis-Eintrag, und die Seite zeigt den
Schlüssel an, z. B. `auswertung:2:HOST,MAIL:30`.

**Split-Screen.** **Auswerten** schickt dieselbe Anfrage gleichzeitig zweimal:
links mit `?nocache` direkt an PostgreSQL, rechts über `cache_aside()`. Beide
Seiten zeigen die Zeit, einen Balken auf gemeinsamer Skala und das Ergebnis.

1. **Cache leeren**, dann **Auswerten**. Beide Seiten sind langsam, Redis erhätl ein MISS.
2. **Auswerten** noch einmal. Links bleibt es bei einigen Sekunden, rechts ist
   es zwischen 0.5 - 1.5ms. Darüber steht der Faktor („×8000 schneller“).
3. Einen Filter ändern: ein neuer Schlüssel, also wieder ein Miss.

**Konsistenz.** Unten lässt sich ein Preis direkt in PostgreSQL ändern.

4. Ohne Haken bei *Cache beim Schreiben invalidieren* den Preis für `HOST`
   ändern. Die Auswertung läuft neu: links steht der neue Umsatz, rechts der
   alte aus Redis. Die abweichenden Zellen werden rot markiert, und die Seite
   zeigt an, wie alt der Eintrag ist und wie lange er noch gilt.
5. **Betroffene Einträge invalidieren**, oder mit Haken erneut speichern: beide
   Seiten zeigen wieder denselben Stand.
6. **Preise zurücksetzen** stellt die Preise vom Laden der Seite wieder her.

Darunter lassen sich alle Tabellen blättern; auch diese Seiten gehen durch den
Cache.

## Aufbau

```
Vagrantfile              drei VMs, feste Adressen im Host-only-Netz
ansible/
  site.yml               ein Play je VM
  group_vars/all.yml     Adressen, Zugangsdaten, TTL
  roles/pg/              Datenbank, Rollen, db/*.sql einspielen
  roles/redis/           Cache, 128 MB, allkeys-lru
  roles/web/             Node.js, Vite-Build, Virtualenv, systemd-Dienst
db/                      schema.sql, seed.sql
web/app.py               Flask: die Vue-Seite und die JSON-Schnittstelle;
                         cache_aside() ist die einzige Stelle, die Redis liest
web/frontend/
  src/index.vue          die ganze Oberfläche: template, script, style
  vite.config.js         Basispfad /static/, Dev-Server mit Proxy auf die web-VM
```

## Die drei VMs

| VM | Adresse | Dienst | Erreichbar von |
| --- | --- | --- | --- |
| `pg` | 192.168.56.10 | PostgreSQL 15, Datenbank `hostingdb` | nur von `web` (`pg_hba.conf`) |
| `redis` | 192.168.56.11 | Redis, 128 MB, `allkeys-lru` | nur aus dem Labornetz |
| `web` | 192.168.56.12 | Flask auf Port 8000, Dienst `web` | vom Host |

Anmelden und nachsehen:

```sh
vagrant ssh pg     -c 'sudo -u postgres psql hostingdb'
vagrant ssh redis  -c 'redis-cli info memory'
vagrant ssh web    -c 'sudo journalctl -u web -f'
```

## Bewusste Entscheidungen

- **Cache-Aside steht genau einmal im Code.** `cache_aside()` in `web/app.py` ist
  die einzige Funktion, die Redis liest oder schreibt; `invalidieren()` die
  einzige, die löscht. Jeder Endpunkt der Seite geht durch sie hindurch.
- **Zugangsdaten im Klartext** in `ansible/group_vars/all.yml`. Die VMs hängen nur
  am Host-only-Netz. Alles, was ein echtes Netz sieht, müsste in Ansible Vault.
- **`protected-mode no`** in Redis, weil kein Passwort gesetzt ist. Aus demselben
  Grund vertretbar.
- **Flask-Entwicklungsserver** statt Gunicorn. Das Labor misst PostgreSQL und
  Redis, nicht den WSGI-Server.
- **`schema.sql` und `seed.sql` werden nur eingespielt, nicht erzeugt.**
- **Vue als Single-File-Component, gebaut mit Vite.** Der übliche Weg eines
  Vue-Projekts: `web/frontend/src/index.vue` enthält Vorlage, Logik und
  Gestaltung in einer Datei.
- **Der Build läuft in der `web`-VM, nicht auf dem Host.** Der Webteil gehört auf
  die Web-VM, und so braucht der Host nur Vagrant und Ansible (nicht zusätzlich
  die richtige Node-Version). 

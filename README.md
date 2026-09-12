# db-cache-benchmark

Ein kleines Labor aus drei VMs, das zeigt, was ein **Cache-Aside-Muster mit
Redis** vor einer teuren Abfrage gegen **PostgreSQL** bewirkt.

```
Browser  ──>  web  ──>  redis  ──>  pg
              192.168.56.12  .11    .10
```

Die Web-VM fragt zuerst Redis. Nur bei einem Cache-Miss geht sie an PostgreSQL 
und legt das Ergebnis auf dem Rückweg in Redis ab. **Jede** Antwort der Seite
nennt, woher sie kam und wie lange sie gebraucht hat — und bei einem Treffer
zusätzlich, wie lange PostgreSQL dafür gebraucht hatte.

## Voraussetzungen

| Komponente | Anmerkung |
| --- | --- |
| macOS auf Apple Silicon | arm64 |
| Parallels Desktop | Pro oder Business Edition |
| Vagrant + `vagrant-parallels` | `vagrant plugin install vagrant-parallels` |
| Ansible | läuft auf dem Host, nicht in den VMs |
| Collection `community.postgresql` | `ansible-galaxy collection install community.postgresql` |

Als Box dient `bento/debian-12`; deren Parallels-Image wird für arm64
veröffentlicht.

## Labor starten

```sh
vagrant up
```

Vagrant baut `pg`, `redis` und `web` in dieser Reihenfolge. Ansible läuft ein
einziges Mal, sobald `web` steht, und konfiguriert alle drei VMs. Darin auch
`npm ci` und `npm run build` für die Vue-Oberfläche. Das geschieht **in der
`web`-VM**: auf dem Host braucht es kein Node.js.

Wer die Oberfläche häufig ändert, muss dafür nicht jedes Mal provisionieren.
`npm run dev` startet auf dem Host einen Vite-Server mit Hot Reload, der `/api`
an `192.168.56.12:8000` weiterleitet — dafür, und nur dafür, wird Node.js auf
dem Host gebraucht.

Danach im Browser:

```
http://192.168.56.12:8000
```

## Die Demo

Die Suchleiste ist der Träger. Ein Begriff: Domain, Kunde, Anbieter, Dienst
oder Nameserver, und das Ausgabefeld zeigt alles, was damit zusammenhängt.
Diese Auswertung ist teuer, und genau daran lässt sich der Cache zeigen:

1. **Cache leeren** drücken. Redis ist leer, die Seite sagt wie viele Schlüssel entfernt wurden.
2. `ns1.hostpoint.ch` suchen und den Treffer anklicken.
   -> **PostgreSQL**. Die Suche allein braucht rund 300 ms, die Detailansicht
   danach noch einmal gut 20.
3. Dieselbe Suche noch einmal.
   -> **Redis**, weniger als eine Millisekunde. Die Anzeige stellt beide Zahlen
   nebeneinander und nennt den Faktor.
4. **ohne Cache laden** zeigt auf Knopfdruck wieder den langsamen Weg, ohne den
   Cache zu leeren, um den Unterschied zweimal hintereinander zu zeigen.
5. Nach `cache_ttl_seconds` läuft der Eintrag ab und der nächste Aufruf ist
   wieder ein Miss.

Idempotenz nachweisen, der zweite Lauf muss `changed=0` melden:

```sh
vagrant provision
```

Von vorn beginnen:

```sh
vagrant destroy -f && vagrant up
```

## Aufbau

```
Vagrantfile              drei VMs, feste Adressen im Host-only-Netz
ansible/
  site.yml               ein Play je VM
  group_vars/all.yml     Adressen, Zugangsdaten, TTL — an einer Stelle
  roles/pg/              Datenbank, Rollen, db/*.sql einspielen
  roles/redis/           Cache, 128 MB, allkeys-lru
  roles/web/             Node.js, Vite-Build, Virtualenv, systemd-Dienst
db/                      schema.sql, seed.sql, query.sql — siehe db/README.md
web/app.py               Flask: die zwei Seiten und die JSON-Schnittstelle;
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
  die einzige Funktion, die Redis liest oder schreibt; `cache_leeren()` die
  einzige, die löscht. Jeder Endpunkt der Seite geht durch sie hindurch.
- **Zugangsdaten im Klartext** in `ansible/group_vars/all.yml`. Die VMs hängen nur
  am Host-only-Netz. Alles, was ein echtes Netz sieht, gehört in Ansible Vault.
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

# db-cache-benchmark

A small lab of three VMs that shows what a **cache-aside pattern with Redis**
does in front of an expensive query against **PostgreSQL**.

![db-benchmark-scheme](/docs/db-benchmark-scheme.jpg)

The web VM asks Redis first. Only on a cache miss does it go to PostgreSQL,
storing the result in Redis on the way back. **Every** response of the page
states where it came from and how long it took, and on a hit also how long
PostgreSQL would have needed.

## Prerequisites

| Component | Note |
| --------- | ---- |
| macOS on Apple Silicon | arm64 |
| Parallels Desktop | Pro or Business Edition |
| Vagrant + `vagrant-parallels` | `vagrant plugin install vagrant-parallels` |
| Ansible | runs on the host, not inside the VMs |
| Collection `community.postgresql` | `ansible-galaxy collection install community.postgresql` |

The box is `bento/debian-12`; its Parallels image is published for arm64.

## Starting the lab

```sh
vagrant up
```

Vagrant builds `pg`, `redis` and `web` in that order. Ansible runs once, as
soon as `web` is up, and configures all three VMs. This includes `npm ci` and
`npm run build` for the Vue frontend.

If the frontend is changed often, it's not neccessary to provision every time. In
`web/frontend/`, `npm run dev` starts a Vite server with hot reload on the
host, which forwards `/api` to `192.168.56.12:8000`.

Then open in the browser:

```
http://192.168.56.12:8000
```

## The demo

![db-benchmark-demo](/docs/db-benchmark-demo.png)

The page is split into three parts: filter, split screen and price form. The
UI itself is in German; button labels are quoted as they appear.

**Filter.** Hoster, services and expiry period narrow down a report over
`domain` and `domain_dienst` (1.5 million rows, no secondary indexes). Every
combination is its own Redis entry, and the page shows the key, e.g.
`auswertung:2:HOST,MAIL:30`.

**Split screen.** **Auswerten** (evaluate) sends the same request twice at the
same time: on the left with `?nocache` straight to PostgreSQL, on the right
through `cache_aside()`. Both sides show the time, a bar on a shared scale and
the result.

1. **Cache leeren** (clear cache), then **Auswerten**. Both sides are slow,
   Redis gets a MISS.
2. **Auswerten** once more. The left side stays at a few seconds, the right
   side is between 0.5 and 1.5 ms. Above it, the factor is shown
   ("×8000 schneller", i.e. ×8000 faster).
3. Change a filter: a new key, so a miss again.

**Consistency.** At the bottom, a price can be changed directly in PostgreSQL.

4. With *Cache beim Schreiben invalidieren* (invalidate cache on write)
   unchecked, change the price for `HOST`. The report runs again: the left
   side shows the new revenue, the right side the old one from Redis. The
   differing cells are marked red, and the page shows how old the entry is
   and how long it remains valid.
5. **Betroffene Einträge invalidieren** (invalidate affected entries), or save
   again with the box checked: both sides show the same state again.
6. **Preise zurücksetzen** (reset prices) restores the prices from when the
   page was loaded.

Below that, all tables can be paged through; these pages also go through the
cache.

## Layout

```
Vagrantfile              three VMs, fixed addresses on the host-only network
ansible/
  site.yml               one play per VM
  group_vars/all.yml     addresses, credentials, TTL
  roles/pg/              database, roles, loading db/*.sql
  roles/redis/           cache, 128 MB, allkeys-lru
  roles/web/             Node.js, Vite build, virtualenv, systemd service
db/                      schema.sql, seed.sql
web/app.py               Flask: the Vue page and the JSON API;
                         cache_aside() is the only place that reads Redis
web/frontend/
  src/index.vue          the whole frontend: template, script, style
  vite.config.js         base path /static/, dev server proxying to the web VM
```

## The three VMs

| VM | Address | Service | Reachable from |
| --- | --- | --- | --- |
| `pg` | 192.168.56.10 | PostgreSQL 15, database `hostingdb` | only from `web` (`pg_hba.conf`) |
| `redis` | 192.168.56.11 | Redis, 128 MB, `allkeys-lru` | only from the lab network |
| `web` | 192.168.56.12 | Flask on port 8000, service `web` | from the host |

Log in and take a look:

```sh
vagrant ssh pg     -c 'sudo -u postgres psql hostingdb'
vagrant ssh redis  -c 'redis-cli info memory'
vagrant ssh web    -c 'sudo journalctl -u web -f'
```

## Deliberate decisions

- **Cache-aside appears exactly once in the code.** `cache_aside()` in
  `web/app.py` is the only function that reads or writes Redis;
  `invalidieren()` is the only one that deletes. Every endpoint of the page
  goes through it.
- **Plain-text credentials** in `ansible/group_vars/all.yml`. The VMs are only
  attached to the host-only network. Anything a real network sees would have
  to go into Ansible Vault.
- **`protected-mode no`** in Redis, because no password is set. Acceptable for
  the same reason.
- **Flask development server** instead of Gunicorn. The lab measures
  PostgreSQL and Redis, not the WSGI server.
- **`schema.sql` and `seed.sql` are only loaded, not generated.**
- **Vue as a single-file component, built with Vite.** The usual way for a Vue
  project: `web/frontend/src/index.vue` holds template, logic and styling in
  one file.
- **The build runs in the `web` VM, not on the host.** The web part belongs on
  the web VM, and this way the host only needs Vagrant and Ansible (not also
  the right Node version).

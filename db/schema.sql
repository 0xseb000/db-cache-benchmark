-- Schema in 3. Normalform, hergeleitet aus der unnormalisierten Tabelle
-- "ein Datensatz je Kombination aus Domain und bezogener Dienstleistung".
--
-- Absichtlich ohne zusaetzliche Indizes: PostgreSQL legt nur fuer PRIMARY KEY
-- und UNIQUE automatisch einen an, nicht fuer Fremdschluessel. Der teure
-- Report in query.sql soll langsam sein -- genau das misst dieses Labor, und
-- genau das faengt der Redis-Cache ab.


-- Kunden. Aus der Vorlage: kunde_nr -> kunde_name, kunde_kontakt.
-- Diese transitive Abhaengigkeit war der 3NF-Verstoss.
CREATE TABLE kunde (
    kunde_nr text PRIMARY KEY,
    name     text NOT NULL,
    kontakt  text NOT NULL
);


-- Registrar und Hoster sind in der Vorlage zwei Spalten mit denselben Werten
-- ("Infomaniak", "Hostpoint"). Beide sind Firmen, also eine Tabelle -- die
-- Domain verweist zweimal darauf. So bleibt darstellbar, dass eine Domain bei
-- Anbieter A registriert und bei Anbieter B gehostet ist.
--
-- hoster_support und hoster_rz hingen in der Vorlage am Hoster, nicht an der
-- Domain: der zweite 3NF-Verstoss.
CREATE TABLE anbieter (
    anbieter_id     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            text NOT NULL UNIQUE,
    support_telefon text NOT NULL,
    rechenzentrum   text NOT NULL
);


-- Dienstleistungen. dienst_bez und dienst_preis_monat hingen nur am
-- dienst_code, also nur an einem Teil des Schluessels: der 2NF-Verstoss.
CREATE TABLE dienst (
    dienst_code text PRIMARY KEY,
    bezeichnung text NOT NULL,
    preis_monat numeric(8, 2) NOT NULL CHECK (preis_monat >= 0)
);


-- Domains. Kuenstlicher Schluessel statt des Domainnamens, weil auf diese
-- Tabelle aus zwei Millionen-Zeilen-Tabellen verwiesen wird und ein integer
-- dort deutlich weniger Platz braucht als der Name. Der Name bleibt per
-- UNIQUE ein vollwertiger Kandidatenschluessel.
CREATE TABLE domain (
    domain_id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         text NOT NULL UNIQUE,
    kunde_nr     text NOT NULL REFERENCES kunde (kunde_nr),
    registrar_id integer NOT NULL REFERENCES anbieter (anbieter_id),
    hoster_id    integer NOT NULL REFERENCES anbieter (anbieter_id),
    ablauf_datum date NOT NULL
);


-- Eine Zeile je Nameserver statt einer kommagetrennten Liste: der 1NF-Verstoss.
-- Nameserver haengen an der Domain, nicht am Hoster. In den Beispieldaten sieht
-- es umgekehrt aus, weil dort jede Domain die Nameserver ihres Hosters nutzt --
-- das ist der Normalfall, aber keine Regel: eine Domain kann jederzeit auf
-- fremde Nameserver zeigen.
CREATE TABLE domain_nameserver (
    domain_id integer NOT NULL REFERENCES domain (domain_id) ON DELETE CASCADE,
    hostname  text    NOT NULL,
    PRIMARY KEY (domain_id, hostname)
);


-- Die eigentliche Zuordnung: welche Domain bezieht welchen Dienst. Das ist die
-- Zeile der Vorlage, nachdem alles Abgeleitete herausgezogen wurde.
CREATE TABLE domain_dienst (
    domain_id   integer NOT NULL REFERENCES domain (domain_id) ON DELETE CASCADE,
    dienst_code text    NOT NULL REFERENCES dienst (dienst_code),
    PRIMARY KEY (domain_id, dienst_code)
);

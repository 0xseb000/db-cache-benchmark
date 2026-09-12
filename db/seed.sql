-- Testdaten. Zuerst die acht Zeilen der Vorlage unveraendert, danach die
-- Massendaten, die den Report teuer machen.


-- ---------------------------------------------------------------- Stammdaten

INSERT INTO anbieter (name, support_telefon, rechenzentrum) VALUES
    ('Infomaniak', '022 820 35 40', 'Genf'),
    ('Hostpoint',  '0844 04 04 04', 'Rapperswil');

INSERT INTO dienst (dienst_code, bezeichnung, preis_monat) VALUES
    ('HOST', 'Webhosting',  19.00),
    ('MAIL', 'Mailhosting',  8.00),
    ('SSL',  'Zertifikat',   0.00);


-- ------------------------------------------------------ Die acht Beispielzeilen

INSERT INTO kunde (kunde_nr, name, kontakt) VALUES
    ('K-101', 'Beispiel AG',    'info@beispiel-ag.ch'),
    ('K-102', 'Muster GmbH',    'kontakt@muster-gmbh.ch'),
    ('K-103', 'Atelier du Lac', 'bonjour@atelier-lac.ch');

-- Registrar und Hoster sind hier ueberall derselbe Anbieter, darum a.anbieter_id
-- zweimal.
INSERT INTO domain (name, kunde_nr, registrar_id, hoster_id, ablauf_datum)
SELECT v.name, v.kunde_nr, a.anbieter_id, a.anbieter_id, v.ablauf_datum
FROM (VALUES
    ('beispiel-ag.ch', 'K-101', 'Infomaniak', DATE '2027-03-01'),
    ('muster-gmbh.ch', 'K-102', 'Hostpoint',  DATE '2026-11-15'),
    ('muster-shop.ch', 'K-102', 'Hostpoint',  DATE '2027-01-20'),
    ('atelier-lac.ch', 'K-103', 'Infomaniak', DATE '2026-09-30')
) AS v (name, kunde_nr, anbieter, ablauf_datum)
JOIN anbieter a ON a.name = v.anbieter;

-- Aus "ns1.infomaniak.ch, ns2.infomaniak.ch" wird eine Zeile je Nameserver.
INSERT INTO domain_nameserver (domain_id, hostname)
SELECT d.domain_id, v.hostname
FROM (VALUES
    ('beispiel-ag.ch', 'ns1.infomaniak.ch'),
    ('beispiel-ag.ch', 'ns2.infomaniak.ch'),
    ('muster-gmbh.ch', 'ns1.hostpoint.ch'),
    ('muster-gmbh.ch', 'ns2.hostpoint.ch'),
    ('muster-gmbh.ch', 'ns3.hostpoint.ch'),
    ('muster-shop.ch', 'ns1.hostpoint.ch'),
    ('muster-shop.ch', 'ns2.hostpoint.ch'),
    ('muster-shop.ch', 'ns3.hostpoint.ch'),
    ('atelier-lac.ch', 'ns1.infomaniak.ch'),
    ('atelier-lac.ch', 'ns2.infomaniak.ch')
) AS v (domain, hostname)
JOIN domain d ON d.name = v.domain;

-- Genau die acht Zeilen der Vorlage.
INSERT INTO domain_dienst (domain_id, dienst_code)
SELECT d.domain_id, v.dienst_code
FROM (VALUES
    ('beispiel-ag.ch', 'HOST'),
    ('beispiel-ag.ch', 'MAIL'),
    ('beispiel-ag.ch', 'SSL'),
    ('muster-gmbh.ch', 'HOST'),
    ('muster-gmbh.ch', 'MAIL'),
    ('muster-shop.ch', 'HOST'),
    ('atelier-lac.ch', 'HOST'),
    ('atelier-lac.ch', 'SSL')
) AS v (domain, dienst_code)
JOIN domain d ON d.name = v.domain;


-- -------------------------------------------------------------- Massendaten
--
-- 50'000 Kunden, 500'000 Domains und daraus genau eine Million Zeilen in
-- domain_dienst. Erzeugt statt ausgeschrieben: generate_series macht daraus
-- eine Datei von 20 Zeilen statt einer von einer Million.

INSERT INTO kunde (kunde_nr, name, kontakt)
SELECT
    'K-' || to_char(i, 'FM000000'),
    'Testkunde ' || i,
    'kunde' || i || '@example.ch'
FROM generate_series(1, 50000) AS i;

-- Abwechselnd bei beiden Anbietern, Ablaufdatum ueber gut zwei Jahre verteilt.
INSERT INTO domain (name, kunde_nr, registrar_id, hoster_id, ablauf_datum)
SELECT
    'domain-' || to_char(i, 'FM000000') || '.ch',
    'K-' || to_char((i % 50000) + 1, 'FM000000'),
    a.anbieter_id,
    a.anbieter_id,
    DATE '2026-01-01' + (i % 900)
FROM generate_series(1, 500000) AS i
JOIN anbieter a
  ON a.name = CASE WHEN i % 2 = 0 THEN 'Infomaniak' ELSE 'Hostpoint' END;

-- Zwei Nameserver je erzeugter Domain, passend zum Hoster.
INSERT INTO domain_nameserver (domain_id, hostname)
SELECT d.domain_id, 'ns' || n || '.' || lower(a.name) || '.ch'
FROM domain d
JOIN anbieter a ON a.anbieter_id = d.hoster_id
CROSS JOIN generate_series(1, 2) AS n
WHERE d.name LIKE 'domain-%';

-- 500'000 + 250'000 + 250'000 = 1'000'000 Dienst-Zuordnungen.
-- Webhosting hat jede Domain, Mail und SSL je die Haelfte.
INSERT INTO domain_dienst (domain_id, dienst_code)
SELECT domain_id, 'HOST' FROM domain WHERE name LIKE 'domain-%';

INSERT INTO domain_dienst (domain_id, dienst_code)
SELECT domain_id, 'MAIL' FROM domain WHERE name LIKE 'domain-%' AND domain_id % 2 = 0;

INSERT INTO domain_dienst (domain_id, dienst_code)
SELECT domain_id, 'SSL' FROM domain WHERE name LIKE 'domain-%' AND domain_id % 2 = 1;


-- Ohne aktuelle Statistiken waehlt der Planer schlechte Plaene, und der
-- Benchmark wuerde fehlende Statistik statt fehlender Indizes messen.
ANALYZE;

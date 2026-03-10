# Informationsschreiben: Nutzung des Lernmanagers

> **Hinweis:** Dies ist ein Entwurf / eine Vorlage. Vor dem Einsatz sollte der
> Datenschutzbeauftragte der Schule das Dokument prüfen. Platzhalter sind mit
> [eckigen Klammern] gekennzeichnet.

[Schulname]
[Adresse]
[Datum]

**Information gemäß Art. 13 DSGVO zur Nutzung der Lernplattform „Lernmanager"**

Sehr geehrte Erziehungsberechtigte,

im Unterricht der Klasse [Klasse] im Fach [Fach] setzen wir die digitale Lernplattform „Lernmanager" ein. Die Plattform unterstützt Schülerinnen und Schüler dabei, Lernaufgaben selbstständig zu bearbeiten und ihren Fortschritt nachzuverfolgen.

Gemäß Art. 13 der Datenschutz-Grundverordnung (DSGVO) informieren wir Sie über die Verarbeitung personenbezogener Daten:

### 1. Verantwortlicher

[Schulname], vertreten durch [Schulleiter/in], [Adresse]
E-Mail: [E-Mail-Adresse]

Datenschutzbeauftragte/r der Schule: [Name], [Kontakt]

### 2. Zweck der Verarbeitung

- Bereitstellung und Verwaltung von Lernaufgaben
- Nachverfolgung des individuellen Lernfortschritts
- Durchführung und Auswertung von Lernzielkontrollen (Quizzes)
- Erstellung von Fortschrittsberichten für die Lehrkraft

### 3. Rechtsgrundlage

Die Verarbeitung erfolgt auf Grundlage von **Art. 6 Abs. 1 lit. e DSGVO** in Verbindung mit dem schulischen Bildungs- und Erziehungsauftrag gemäß [Schulgesetz des Bundeslandes, z.B. „§ XX SchulG NRW"].

### 4. Verarbeitete Daten

| Datenkategorie | Beschreibung |
|---|---|
| Vor- und Nachname | Zur Identifikation durch die Lehrkraft erforderlich |
| Pseudonymisierter Benutzername | Automatisch generiert (z.B. „happypanda"), wird für den Login und als Anzeigename verwendet |
| Lernfortschritt | Bearbeitete Aufgaben, Ergebnisse von Übungsquizzes (nicht benotet) |
| Übungshistorie | Ergebnisse von Aufwärm-Quiz und Wiederholungsübungen (verteiltes Üben), gespeichert pro Frage und Schüler |
| Lernpfad | Zugewiesene Schwierigkeitsstufe (von der Lehrkraft vergeben) |
| Aktivitätsprotokoll | Zeitpunkte der Nutzung |

Vor- und Nachname werden auf dem Server gespeichert, da die Lehrkraft die Lernwege und optionalen Aufgaben einzelnen Schülerinnen und Schülern zuweisen muss. Die Speicherung erfolgt auf Grundlage des schulischen Bildungsauftrags (Art. 6 Abs. 1 lit. e DSGVO). Schülerinnen und Schüler melden sich mit ihrem Pseudonym an und sehen ihren Vornamen in der Plattform; der vollständige Klarname erscheint nur in der Verwaltungsansicht der Lehrkraft.

**Die erfassten Daten werden ausschließlich zur Lernbegleitung verwendet und fließen nicht in die Benotung ein.** Quizzes und Lernstandserhebungen in dieser Plattform sind Übungsformate ohne Notenrelevanz. Die Note setzt ausschließlich die Lehrkraft auf Basis des Unterrichts und ggf. abgegebener Arbeitsergebnisse fest.

**Folgende Daten werden ausdrücklich nicht gespeichert oder verarbeitet:**

- **IP-Adressen** -- Webserver-Zugriffsprotokolle sind deaktiviert
- **Passwörter im Klartext** -- Passwörter werden ausschließlich als kryptografischer Hash gespeichert
- **Geräteinformationen** -- keine Browser-, Geräte- oder Betriebssystemdaten
- **Standortdaten** -- keine Ortungsfeatures
- **Hochgeladene Dateien** -- beim optionalen KI-Aufgabencheck wird die Originaldatei nicht gespeichert; nur die Vollständigkeitsrückmeldung (Checkliste: Ja/Nein pro Kriterium) wird festgehalten
- **Kommunikation** -- die Plattform hat keine Nachrichten- oder Chatfunktion

*Hinweis: Quizantworten (Text und Auswahl) werden gespeichert, damit die Lehrkraft Lernstände nachvollziehen kann. Sie fließen nicht in die Benotung ein.*

### 5. Automatisierte Auswertung durch KI

#### 5a. Automatisierte Bewertung von Freitextantworten (Quiz)

Für bestimmte Aufgabentypen (Lückentext, Kurzantwort) wird eine automatisierte Auswertung eingesetzt. Dabei werden **ausschließlich die Aufgabenstellung und die Schülerantwort** -- ohne jeglichen Personenbezug -- an einen externen KI-Dienst (OVHcloud AI Endpoints, Frankreich) übermittelt.

#### 5b. Optionaler KI-Aufgabencheck für digitale Arbeitsergebnisse (sofern aktiviert)

Wenn die Lehrkraft diese Funktion für eine Klasse aktiviert hat, können Schülerinnen und Schüler ihre digitalen Arbeitsergebnisse (z.B. Präsentationen) freiwillig auf Vollständigkeit prüfen lassen. Der Ablauf:

1. Die App extrahiert den Text aus der Datei und entfernt alle erkennbaren Personenangaben (Name -> „[Schüler/in]")
2. Die Schülerinnen und Schüler sehen eine **Vorschau** des übermittelten Textes, bevor etwas gesendet wird
3. Erst nach der Bestätigung wird der anonymisierte Text an einen KI-Dienst übermittelt
4. Die Originaldatei wird nicht gespeichert; nur die Vollständigkeitsrückmeldung (Checkliste: Ja/Nein pro Kriterium) wird festgehalten
5. Die KI gibt eine Rückmeldung zur Vollständigkeit -- die Note setzt ausschließlich die Lehrkraft

Der KI-Dienst wird bei einem deutschen oder europäischen Anbieter betrieben (kein US-amerikanischer Dienst). Die Daten werden nicht für das Training von KI-Modellen verwendet. Die Verarbeitung erfolgt auf Grundlage von Art. 6 Abs. 1 lit. e DSGVO (Bildungsauftrag). Eltern und Erziehungsberechtigte können der Nutzung dieser Funktion für ihr Kind jederzeit widersprechen (Art. 21 DSGVO) -- wenden Sie sich dazu an die Lehrkraft.

- Es werden **keine** Namen, Pseudonyme, Klassenzugehörigkeiten oder sonstige personenbezogene Daten übermittelt
- Die übermittelten Daten sind **vollständig anonym** und unterliegen daher nicht der DSGVO (Erwägungsgrund 26)
- OVHcloud ist ein EU-Unternehmen mit Serverstandort in Frankreich -- keine Drittlandübermittlung
- Der Dienst wird nicht mit Schülerdaten trainiert

### 6. Speicherung und Löschung

- Daten werden auf einem Server von Strato AG gespeichert (Rechenzentren in Deutschland und der EU)
- Serverzugriff ausschließlich durch die zuständige Lehrkraft
- Daten werden am Ende des Schuljahres zuzüglich zwei Monate gelöscht, sofern kein berechtigtes Aufbewahrungsinteresse besteht
- Die Zuordnungsdatei auf dem Lehrergerät wird nach Abschluss der Notenvergabe gelöscht

### 7. Empfänger der Daten

| Empfänger | Zweck | Grundlage |
|---|---|---|
| Strato AG | Serverbetrieb | AV-Vertrag gem. Art. 28 DSGVO |
| OVHcloud (nur anonyme Daten) | Automatische Auswertung von Übungsantworten | Keine personenbezogenen Daten -- DSGVO nicht anwendbar |

Darüber hinaus werden keine Daten an Dritte weitergegeben.

### 8. Rechte der Betroffenen

Sie haben gemäß DSGVO folgende Rechte:

- **Auskunft** (Art. 15) -- Welche Daten sind gespeichert?
- **Berichtigung** (Art. 16) -- Korrektur falscher Daten
- **Löschung** (Art. 17) -- Löschung der Daten, soweit keine Aufbewahrungspflicht besteht
- **Einschränkung** (Art. 18) -- Einschränkung der Verarbeitung
- **Widerspruch** (Art. 21) -- Widerspruch gegen die Verarbeitung
- **Beschwerde** bei der zuständigen Aufsichtsbehörde: [Landesbeauftragter für Datenschutz, z.B. „LDI NRW, Postfach ..., Düsseldorf"]

Zur Ausübung Ihrer Rechte wenden Sie sich bitte an: [Kontakt der Lehrkraft oder der Schule]

*Dieses Schreiben dient der Information gemäß Art. 13 DSGVO. Eine Einwilligung ist nicht erforderlich, da die Datenverarbeitung auf dem schulischen Bildungsauftrag beruht.*

[Ort, Datum]
[Name der Lehrkraft]

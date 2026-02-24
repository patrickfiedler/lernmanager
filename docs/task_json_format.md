# Lernmanager — JSON-Format für Themen, Aufgaben und Quizfragen

Dieses Dokument beschreibt das JSON-Datenformat für den Import von Lerninhalten in den Lernmanager. Nutze es als Referenz, wenn du mit Claude Opus neue Themen, Aufgaben und Quizfragen erstellst.

## Überblick

Ein **Thema** (englisch: "Topic", Datenbank: `task`) enthält mehrere **Aufgaben** (englisch: "Tasks", Datenbank: `subtask`). Jede Aufgabe kann ein eigenes Quiz haben. Zusätzlich kann das Thema ein übergreifendes Abschluss-Quiz haben.

```
Thema (task)
├── Aufgabe 1 (subtask) + optionales Quiz
├── Aufgabe 2 (subtask) + optionales Quiz
├── Aufgabe 3 (subtask) + optionales Quiz
├── Materialien (links, dateien)
└── optionales Themen-Quiz (Abschlussquiz)
```

## Import-Formate

### Einzelnes Thema

```json
{
  "task": { ... }
}
```

### Mehrere Themen (Batch)

```json
{
  "tasks": [ { ... }, { ... } ]
}
```

## Vollständiges Beispiel

```json
{
  "task": {
    "name": "3 - Bilder und Pixel verstehen",
    "number": 3,
    "beschreibung": "Lerne, wie digitale Bilder aus Pixeln aufgebaut sind, erstelle eigene Pixel-Art und bearbeite Bilder mit Filtern.",
    "lernziel": "Schüler verstehen den Aufbau digitaler Bilder, können Bildgrößen berechnen und Bilder mit einfachen Werkzeugen bearbeiten.",
    "why_learn_this": "Jedes Foto auf deinem Handy, jedes Bild im Internet besteht aus winzigen Punkten — Pixeln. Wenn du verstehst, wie das funktioniert, kannst du Bilder besser bearbeiten und verstehst, warum manche Bilder scharf und andere unscharf sind.",
    "fach": "MBI",
    "stufe": "5/6",
    "kategorie": "pflicht",
    "subtask_quiz_required": true,
    "subtasks": [
      {
        "beschreibung": "### Pixel entdecken\n\n🎯 Ziel: Du verstehst, was Pixel sind und kannst sie sehen.\n\n📋 Aufgabe:\n1. Öffne ein beliebiges Bild am Computer\n2. Zoome stark hinein (400% oder mehr)\n3. Notiere deine Beobachtung",
        "fertig_wenn": "Du hast Pixel gesehen und erklärt was sie sind.",
        "reihenfolge": 0,
        "estimated_minutes": 15,
        "path": "wanderweg",
        "quiz": {
          "questions": [
            {
              "text": "Wofür steht das Wort 'Pixel'?",
              "type": "fill_blank",
              "answers": ["Picture Element", "picture element", "Bildpunkt", "bildpunkt"]
            },
            {
              "text": "Was passiert, wenn man ein digitales Bild sehr stark vergrößert?",
              "options": [
                "Das Bild wird automatisch schärfer",
                "Man sieht die einzelnen Pixel als kleine Quadrate",
                "Das Bild bekommt mehr Farben",
                "Die Datei wird größer"
              ],
              "correct": [1]
            }
          ]
        }
      },
      {
        "beschreibung": "### EVA-Prinzip\n\n🎯 Ziel: Du verstehst das Eingabe-Verarbeitung-Ausgabe-Prinzip.\n\n📋 Aufgabe:\n1. Recherchiere das EVA-Prinzip\n2. Finde 3 Beispiele aus dem Alltag\n3. Erstelle ein Schaubild",
        "fertig_wenn": "Dein Schaubild zeigt 3 EVA-Beispiele.",
        "reihenfolge": 1,
        "estimated_minutes": 45,
        "path": "bergweg",
        "path_model": "skip"
      },
      {
        "beschreibung": "### Computer-Steckbrief\n\n🎯 Ziel: Du kannst ein Dokument über deinen Computer erstellen.\n\n📋 Aufgabe:\n1. Erstelle ein Textdokument mit Infos über deinen Computer\n2. Beschreibe Hardware und Software\n\nFür eine bessere Note: Ergänze EVA-Beispiele und Netzwerk-Infos.\nFür die beste Note: Füge persönliche Reflexion und Zusatzwissen hinzu.",
        "fertig_wenn": "Dein Steckbrief hat mindestens 4 Abschnitte.",
        "reihenfolge": 2,
        "estimated_minutes": 45,
        "path": "wanderweg",
        "path_model": "depth",
        "graded_artifact": {
          "keyword": "computer-steckbrief",
          "format": [".docx", ".odt"],
          "rubric": "Prüfe: (1) Pflichtabschnitte vorhanden? (2) Detaillierte Beschreibungen? (3) EVA-Beispiele, Tabellen? (4) Persönliche Reflexion? Vergib Note 1–4."
        }
      }
    ],
    "materials": [
      {
        "typ": "link",
        "pfad": "https://de.wikipedia.org/wiki/Pixel",
        "beschreibung": "Wikipedia: Pixel",
        "subtask_indices": [0]
      }
    ],
    "quiz": {
      "questions": [
        {
          "text": "Warum wird eine Bilddatei größer, wenn sie mehr Pixel hat?",
          "type": "short_answer",
          "rubric": "Jedes Pixel speichert Farbinformationen. Mehr Pixel = mehr Daten = größere Datei."
        }
      ]
    },
  }
}
```

## Feld-Referenz

### Thema (task)

| Feld | Pflicht | Typ | Beschreibung |
|------|---------|-----|--------------|
| `name` | ja | string | Name des Themas, z.B. `"3 - Bilder und Pixel verstehen"` |
| `number` | nein | integer | Sortierungs-Nummer (Default: 0) |
| `beschreibung` | ja | string | Ausführliche Beschreibung. Markdown erlaubt. |
| `lernziel` | nein | string | Was Schüler nach Abschluss können sollen |
| `why_learn_this` | nein | string | Motivationstext für Schüler: Warum ist das Thema relevant? |
| `fach` | ja | string | Eines von: `Englisch`, `Chemie`, `MBI`, `Geographie` |
| `stufe` | ja | string | Eines von: `5/6`, `7/8`, `9/10`, `11s`, `11/12` |
| `kategorie` | nein | string | `pflicht` (Default) oder `bonus` |
| `subtask_quiz_required` | nein | boolean | Müssen Aufgaben-Quizzes bestanden werden? (Default: `true`) |
| `subtasks` | nein | array | Liste der Aufgaben (siehe unten) |
| `materials` | nein | array | Liste der Materialien (siehe unten) |
| `quiz` | nein | object | Abschluss-Quiz für das gesamte Thema (siehe Quiz-Format) |

### Aufgabe (subtask)

| Feld | Pflicht | Typ | Beschreibung |
|------|---------|-----|--------------|
| `beschreibung` | ja | string | Arbeitsauftrag. Markdown (siehe Formatierung). Beginne mit `### Titel` |
| `reihenfolge` | nein | integer | Position (0-basiert, Default: Index in der Liste) |
| `estimated_minutes` | nein | integer | Geschätzte Bearbeitungszeit in Minuten |
| `path` | ja | string | Niedrigster Lernpfad: `wanderweg`, `bergweg` oder `gipfeltour` |
| `path_model` | nein | string | `skip` (Default): niedrigere Pfade überspringen. `depth`: alle Pfade, unterschiedliche Erwartungen |
| `fertig_wenn` | nein | string | Abschluss-Kriterium. Markdown erlaubt. Wird als grüner Kasten direkt über dem Abhaken-Häkchen angezeigt. |
| `tipps` | nein | string | Hilfestellungen. Markdown erlaubt. Wird als ausklappbarer "💡 Hilfe"-Block unter der Aufgabe angezeigt. |
| `graded_artifact` | nein | object | Bewertetes Artefakt (siehe unten) |
| `quiz` | nein | object | Quiz für diese Aufgabe (siehe Quiz-Format) |

### Bewertetes Artefakt (graded_artifact)

Nur bei Aufgaben, die ein bewertetes digitales Produkt erzeugen (Dokument, Bild, Scratch-Projekt).

| Feld | Pflicht | Typ | Beschreibung |
|------|---------|-----|--------------|
| `keyword` | ja | string | Eindeutiger Bezeichner, muss im Dateinamen vorkommen |
| `format` | ja | array | Akzeptierte Dateiendungen, z.B. `[".docx", ".odt"]` |
| `rubric` | ja | string | Bewertungskriterien für KI-Bewertung (Note 1–4) |

### Material

| Feld | Pflicht | Typ | Beschreibung |
|------|---------|-----|--------------|
| `typ` | ja | string | `link` (URL) oder `datei` (Datei-Upload, nur manuell) |
| `pfad` | ja | string | URL oder Dateipfad |
| `beschreibung` | nein | string | Kurzbeschreibung des Materials |
| `subtask_indices` | nein | array | Zuordnung zu Aufgaben (Liste von `reihenfolge`-Werten). Ohne Angabe: Material ist bei allen Aufgaben sichtbar. |

## Lernpfade (Learning Paths)

Drei kumulative Schwierigkeitsstufen. Jeder Schüler wählt einen Pfad. Alle Aufgaben sind sichtbar, aber nur die des gewählten Pfads sind Pflicht. **Lernpfade sind der Standard** — ohne weitere Konfiguration bestimmt der Pfad, welche Aufgaben Pflicht sind. Schüler können ihren Pfad jederzeit einfach wechseln; der Pfad überschreibt eventuelle manuelle Sichtbarkeitseinstellungen.

| Pfad | Emoji | Anteil | Beschreibung |
|------|-------|--------|--------------|
| `wanderweg` | 🟢 🥾 | ~49% | Grundlagen. Reicht zum Bestehen. |
| `bergweg` | 🔵 ⛰️ | ~87% | Voller Lehrplan. Empfohlener Pfad. |
| `gipfeltour` | ⭐ 🏔️ | 100% | Alles. Für maximale Tiefe. |

### Regeln

- **Kumulativ:** Bergweg enthält alle Wanderweg-Aufgaben. Gipfeltour enthält alle Bergweg-Aufgaben.
- **`path`-Feld** = der niedrigste Pfad, der diese Aufgabe enthält.
- **`path_model: "skip"`** (Default): Niedrigere Pfade überspringen diese Aufgabe komplett.
- **`path_model: "depth"`**: Alle Pfade machen diese Aufgabe, aber mit unterschiedlichen Erwartungen. Die Aufgabenbeschreibung enthält gestufte Kriterien ("Für eine bessere Note:", "Für die beste Note:").

### Beispiel

```json
{"path": "wanderweg"}                          // Alle Pfade machen diese Aufgabe
{"path": "bergweg", "path_model": "skip"}      // Wanderweg überspringt, Bergweg + Gipfeltour machen es
{"path": "wanderweg", "path_model": "depth"}   // Alle machen es, Bewertung je nach Pfad unterschiedlich
```

## Quiz-Format

Quizzes können auf Thema-Ebene und/oder pro Aufgabe definiert werden. Das Format ist identisch:

```json
{
  "questions": [ ... ]
}
```

Schüler bestehen ein Quiz, wenn sie ca. 70% der Fragen richtig beantworten (abgerundet auf ganze Zahlen: bei 3 Fragen reichen 2 richtige).

### Fragetypen

#### 1. Multiple Choice (Standard)

```json
{
  "text": "Welches Dateiformat eignet sich für verlustfreie Speicherung?",
  "options": ["PNG", "JPG", "GIF", "TXT"],
  "correct": [0]
}
```

- `type` kann weggelassen werden (Default: `multiple_choice`)
- `options`: mindestens 2, empfohlen 3–4 Antwortmöglichkeiten
- `correct`: Liste der korrekten Indizes (0-basiert). Für eine richtige Antwort: `[1]`. Für mehrere richtige: `[0, 2]`
- Optional: `"image": "/pfad/zum/bild.png"` für ein Bild zur Frage

#### 2. Lückentext (fill_blank)

```json
{
  "type": "fill_blank",
  "text": "Die Hauptstadt von Deutschland ist ___.",
  "answers": ["Berlin", "berlin"]
}
```

- `answers`: Liste akzeptierter Antworten (exakter Textvergleich, Groß-/Kleinschreibung beachten!)
- Tipp: Mehrere Schreibweisen angeben (Groß/Klein, mit/ohne Einheit, Abkürzungen)
- Bei keinem Treffer wird die Antwort automatisch per KI bewertet (Fallback)

#### 3. Freitext (short_answer)

```json
{
  "type": "short_answer",
  "text": "Erkläre, warum Bilder mit mehr Pixeln größere Dateien haben.",
  "rubric": "Jedes Pixel speichert Farbinformationen (RGB-Werte). Mehr Pixel bedeuten mehr Datenpunkte, die gespeichert werden müssen, was zu einer größeren Dateigröße führt."
}
```

- `rubric`: Bewertungskriterium für die KI-Bewertung. Beschreibe die erwarteten Kernpunkte der Antwort.
- Die Bewertung erfolgt automatisch per KI (Claude Haiku). Bei Ausfall: Punkt wird gegeben + Hinweis auf Lehrerprüfung.

## Kodierung und Markdown-Formatierung

### Kodierung

- **JSON-Dateien müssen UTF-8 kodiert sein** (ohne BOM)
- Alle Textfelder (`beschreibung`, `lernziel`, `why_learn_this`, Quiz-Texte) unterstützen UTF-8 einschließlich Emojis

### Unterstütztes Markdown

Die App rendert alle Textfelder als Markdown mit folgenden Erweiterungen:

| Feature | Syntax | Ergebnis |
|---------|--------|----------|
| **Fett** | `**Text**` | Fettschrift |
| *Kursiv* | `*Text*` | Kursiv |
| Zeilenumbruch | Einfaches `\n` | `<br>` (Zeilenumbruch) |
| Nummerierte Liste | `1. Schritt eins` | Nummerierte Liste |
| Aufzählung | `- Punkt eins` | Aufzählung mit Punkt |
| Tabelle | `\| A \| B \|` | HTML-Tabelle |
| Überschrift | `## Titel` | Überschrift (h2) |
| Link | `[Text](URL)` | Klickbarer Link |
| Code | `` `code` `` | Inline-Code |
| Codeblock | ` ```code``` ` | Code-Block |
| Zitat | `> Text` | Eingerücktes Zitat |
| Trennlinie | `---` | Horizontale Linie |

**Wichtig:** Einfache Zeilenumbrüche (`\n`) werden als `<br>` gerendert. Du brauchst KEINE doppelten Leerzeilen oder zwei Leerzeichen am Zeilenende für Zeilenumbrüche. Schreibe einfach natürlich — jede neue Zeile wird im Browser als Zeilenumbruch angezeigt.

**Hinweis zu Listen:** Verwende Standard-Markdown (`-` oder `1.`) statt Unicode-Bullets (`•`). Markdown-Listen werden als semantisches HTML (`<ul>`, `<ol>`) gerendert und sind besser eingerückt.

### Aufgaben-Format (subtask `beschreibung`)

Jede Aufgabe folgt einer einheitlichen Struktur. `beschreibung` enthält den Arbeitsauftrag; `fertig_wenn` ist ein separates Feld (wird als grüner Kasten über dem Häkchen angezeigt):

**`beschreibung`-Struktur:**
```
### Titel der Aufgabe

🎯 Ziel: Kurze Beschreibung, was der Schüler lernt/kann.

📋 Aufgabe:
1. Erster Schritt
2. Zweiter Schritt
   - Unterpunkt
   - Unterpunkt
3. Dritter Schritt
```

**`tipps`-Feld (separat, optional):**
```
💡 Tipp: Hilfreicher Hinweis für den Schüler
💡 Tipp: Noch ein Hinweis — Mehrere Tipps im selben Feld sind erlaubt.
```
Wird als ausklappbarer "💡 Hilfe"-Block unterhalb der Aufgabenbeschreibung angezeigt. Schüler öffnen ihn bei Bedarf, er stört nicht den normalen Lesefluss.

**`fertig_wenn`-Feld (separat):**
```
Du hast alle Schritte erledigt und dein Ergebnis gespeichert.
```

#### Abschnittsmarker in `beschreibung`

| Marker | Inhalt | Pflicht? |
|--------|--------|----------|
| `🎯 Ziel:` | Was der Schüler nach dieser Aufgabe kann | Ja |
| `📋 Aufgabe:` | **Nur Pflicht-Handlungen** — ein Schritt, ein Verb, imperativisch | Ja |
| `💡 Tipp:` | Gehört ins **`tipps`-Feld**, nicht in `beschreibung` — ausklappbarer Hilfe-Block | Optional |

**Wichtige Trennregel: Aktionen vs. Hinweise**
`📋 Aufgabe:`-Schritte enthalten NUR, was der Schüler tun MUSS. Alles, was er überspringen könnte und die Aufgabe trotzdem erledigt wäre, gehört in `💡 Tipp:`.

- Schlecht: `3. Speichere die Datei — drücke dafür Strg+S oder klicke auf Datei → Speichern unter`
- Gut: `3. Speichere die Datei.` + `💡 Tipp: Strg+S oder Datei → Speichern unter`

**`✅ Fertig wenn:` gehört NICHT mehr in `beschreibung`** — stattdessen das `fertig_wenn`-Feld verwenden. Die App zeigt es als eigenen grünen Kasten an, damit Schüler das Kriterium lesen, bevor sie abhaken.

Die anderen Marker werden in der App automatisch **fettgedruckt** gerendert.

#### Titelzeile

- Erste Zeile ist der Titel als `###`-Überschrift (h3), da die Seite `<h1>` für das Thema verwendet
- Keine Nummerierung nötig (die Position ergibt sich aus `reihenfolge`)

#### Beispiel einer vollständigen Aufgabe

```json
{
  "beschreibung": "### Pixel entdecken\n\n🎯 Ziel: Du verstehst, was Pixel sind und kannst sie sehen.\n\n📋 Aufgabe:\n1. Öffne ein beliebiges Bild am Computer\n2. Zoome stark hinein (400% oder mehr)\n   - Windows: Strg + Mausrad\n   - Paint: Ansicht → Zoom → 800%\n3. Mache einen Screenshot vom vergrößerten Bild\n4. Erkläre mit eigenen Worten: Was ist ein Pixel?\n\n💡 Tipp: Pixel = Picture Element = Bildpunkt\n💡 Tipp: Ein Pixel ist wie ein kleines Quadrat mit einer Farbe",
  "fertig_wenn": "Du hast Pixel fotografiert und erklärt was sie sind.",
  "reihenfolge": 1,
  "estimated_minutes": 15
}
```

### Themen-Beschreibung (`beschreibung` des Themas)

Freier Text, der das Thema überblicksartig vorstellt. Kürzere, motivierende Sprache:

```
Wie entstehen Bilder auf dem Bildschirm? 🖼️

Jedes Bild am Computer besteht aus winzig kleinen Punkten — den Pixeln.
In dieser Aufgabe entdeckst du, wie digitale Bilder funktionieren!

🎯 Du lernst:
- Was sind Pixel?
- Wie speichert ein Computer Bilder?
- Wie kann man Bilder bearbeiten?

⏱️ Zeit: 5 Wochen (5 Schulstunden)
```

### Allgemeine Formatierungsregeln

1. **Sprache:** Deutsch, Du-Anrede, altersgerecht für die jeweilige Stufe
2. **Emojis:** Sparsam und gezielt einsetzen (Abschnittsmarker, Materialbeschreibungen)
3. **Länge:** Aufgaben-Beschreibungen ca. 10–25 Zeilen, nicht länger
4. **Arbeitsschritte:** Immer als nummerierte Liste, immer konkret und handlungsorientiert
5. **Ein Fertig-Kriterium:** Schüler muss wissen, wann die Aufgabe erledigt ist

## Richtlinien für gute Inhalte

### Aufgaben (subtasks)

- Formuliere klare, handlungsorientierte Arbeitsaufträge
- Verwende das oben beschriebene Aufgaben-Format mit Abschnittsmarkern
- Beschreibe konkret, was Schüler tun sollen
- Schätze die Bearbeitungszeit realistisch ein (10–30 Minuten pro Aufgabe)
- Ordne 3–8 Aufgaben pro Thema an

### Quizfragen

- Mische die Fragetypen: MC + Lückentext + Freitext
- 2–4 Fragen pro Aufgaben-Quiz, 3–5 Fragen für Themen-Quiz
- Multiple Choice: Eine klar richtige Antwort + plausible Distraktoren
- Lückentext: Mehrere akzeptierte Schreibweisen (mindestens Groß/Klein)
- Freitext: Rubric beschreibt die Kernpunkte, nicht die exakte Formulierung
- Sprache: Deutsch, altersgerecht für die jeweilige Stufe
- Fragen sollen Verständnis prüfen, nicht nur Faktenwissen abfragen

### Beispiel: Gute vs. schlechte Fragen

**Gut** (prüft Verständnis):
```json
{"text": "Warum wird ein Bild unscharf, wenn man es vergrößert?", "type": "short_answer", "rubric": "Die Anzahl der Pixel bleibt gleich, aber jeder Pixel wird größer dargestellt. Dadurch werden die einzelnen Pixel sichtbar und das Bild wirkt unscharf/verpixelt."}
```

**Schlecht** (reines Faktenwissen):
```json
{"text": "In welchem Jahr wurde das PNG-Format entwickelt?", "type": "fill_blank", "answers": ["1996"]}
```

## Import-Befehl

```bash
# Einzelne Datei importieren
python import_task.py thema.json

# Vorher prüfen (kein Import)
python import_task.py --dry-run thema.json

# Alle Dateien aus einem Ordner importieren
python import_task.py --batch ordner/

# Vorhandene Themen auflisten
python import_task.py --list
```

## Hinweise

- **JSON muss UTF-8 kodiert sein** (siehe Abschnitt "Kodierung und Markdown-Formatierung")
- Duplikate (gleicher Name + Fach + Stufe) werden automatisch übersprungen
- `voraussetzungen` field is ignored on import (deprecated — topic queue replaces progression logic)
- Materialien vom Typ `datei` können nur manuell über die Admin-Oberfläche hochgeladen werden; im JSON nur `link` verwenden
- **Dieses Dokument als Claude-Prompt:** Gib diese Datei als Kontext an Claude, wenn du neue Themen erstellen lässt. Claude kann das JSON-Format und die Formatierungsrichtlinien direkt als Vorlage verwenden.

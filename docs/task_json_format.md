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
        "beschreibung": "**Pixel entdecken:** Öffne ein beliebiges Bild am Computer und zoome stark hinein (400% oder mehr). Was siehst du? Notiere deine Beobachtung.",
        "reihenfolge": 0,
        "estimated_minutes": 15,
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
            },
            {
              "text": "Erkläre mit eigenen Worten: Was ist ein Pixel?",
              "type": "short_answer",
              "rubric": "Ein Pixel ist der kleinste Bildpunkt eines digitalen Bildes. Es ist ein kleines Quadrat mit einer einzigen Farbe. Viele Pixel nebeneinander ergeben ein Bild."
            }
          ]
        }
      },
      {
        "beschreibung": "**Bildgröße und Auflösung:** Recherchiere: Was bedeutet Auflösung? Berechne, wie viele Pixel ein Full-HD-Bild (1920×1080) hat.",
        "reihenfolge": 1,
        "estimated_minutes": 20,
        "quiz": {
          "questions": [
            {
              "text": "Ein Bild hat 1920 Pixel Breite und 1080 Pixel Höhe. Wie viele Pixel hat es insgesamt?",
              "type": "fill_blank",
              "answers": ["2073600", "2.073.600"]
            }
          ]
        }
      },
      {
        "beschreibung": "**Bilder bearbeiten:** Öffne ein Foto in Paint.NET oder GIMP. Schneide es zu, ändere die Größe und speichere es als PNG.",
        "reihenfolge": 2,
        "estimated_minutes": 25
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
    "voraussetzungen": ["2 - Dateien und Ordner"]
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
| `voraussetzungen` | nein | array | Liste von Themen-Namen, die vorher abgeschlossen sein müssen |

### Aufgabe (subtask)

| Feld | Pflicht | Typ | Beschreibung |
|------|---------|-----|--------------|
| `beschreibung` | ja | string | Arbeitsauftrag. Markdown erlaubt. Beginne mit `**Titel:**` |
| `reihenfolge` | nein | integer | Position (0-basiert, Default: Index in der Liste) |
| `estimated_minutes` | nein | integer | Geschätzte Bearbeitungszeit in Minuten |
| `quiz` | nein | object | Quiz für diese Aufgabe (siehe Quiz-Format) |

### Material

| Feld | Pflicht | Typ | Beschreibung |
|------|---------|-----|--------------|
| `typ` | ja | string | `link` (URL) oder `datei` (Datei-Upload, nur manuell) |
| `pfad` | ja | string | URL oder Dateipfad |
| `beschreibung` | nein | string | Kurzbeschreibung des Materials |
| `subtask_indices` | nein | array | Zuordnung zu Aufgaben (Liste von `reihenfolge`-Werten). Ohne Angabe: Material ist bei allen Aufgaben sichtbar. |

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

## Richtlinien für gute Inhalte

### Aufgaben (subtasks)

- Formuliere klare, handlungsorientierte Arbeitsaufträge
- Beginne mit einem fettgedruckten Titel: `**Pixel entdecken:**`
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

- Duplikate (gleicher Name + Fach + Stufe) werden automatisch übersprungen
- `voraussetzungen` verweisen auf Themen-Namen — das referenzierte Thema muss bereits importiert sein
- Materialien vom Typ `datei` können nur manuell über die Admin-Oberfläche hochgeladen werden; im JSON nur `link` verwenden
- Das JSON muss UTF-8 kodiert sein

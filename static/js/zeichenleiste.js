/* Character-insert bar for free-text answer fields.
 *
 * Students on iPads cannot reach the characters their subject needs -- in the
 * 2026-08-26 chemistry run, not one of thirty half-equation answers contained a
 * reaction arrow. window.ZEICHENLEISTE maps a Fach to its characters, set by
 * base.html from config.CHARACTER_SETS.
 *
 * Zeichenleiste.attach(field, fach) puts a bar above `field` if that Fach defines
 * one. A subject with no entry -- which is every subject but Chemie -- is a no-op,
 * as is a missing or empty fach, so callers never have to check first. Safe to call
 * twice on the same field.
 *
 * An entry is either a character, or an object {char, anchor, name}: `anchor` is a
 * dimmed letter shown next to the character so a raised digit can be told apart
 * from a lowered one, and `name` is what a screen reader reads. Only `char` is
 * inserted -- the anchor is decoration and never reaches the answer.
 */
(function () {
    'use strict';

    function insert(field, char) {
        // setRangeText keeps the browser's own undo stack intact; rebuilding
        // field.value by hand loses it, and a student who mistypes a subscript
        // would have no way back except deleting the whole answer.
        var start = field.selectionStart;
        if (typeof field.setRangeText === 'function' && start !== null) {
            field.setRangeText(char, start, field.selectionEnd, 'end');
        } else {
            field.value += char;
        }
        field.focus();
        // The field's own 'input' listeners drive the check button's enabled
        // state; a programmatic value change does not fire that on its own.
        field.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function attach(field, fach) {
        var chars = (window.ZEICHENLEISTE || {})[fach] || [];
        if (!field || !chars.length || field.dataset.zeichenleiste === 'on') return;
        field.dataset.zeichenleiste = 'on';

        var bar = document.createElement('div');
        bar.className = 'zeichenleiste';
        bar.setAttribute('role', 'group');
        bar.setAttribute('aria-label', 'Sonderzeichen einfügen');

        chars.forEach(function (entry) {
            var spec = typeof entry === 'string' ? { char: entry } : entry;
            var char = spec.char;

            var btn = document.createElement('button');
            btn.type = 'button';           // inside a <form>, the default is submit
            btn.className = 'zeichenleiste-btn';
            if (spec.anchor) {
                var anchor = document.createElement('span');
                anchor.className = 'zeichenleiste-anchor';
                anchor.textContent = spec.anchor;
                // The anchor is there to be looked at, not read out: the button
                // already says "hochgestellte 2", and "x hochgestellte 2" would
                // announce a letter the student is not inserting.
                anchor.setAttribute('aria-hidden', 'true');
                btn.appendChild(anchor);
            }
            btn.appendChild(document.createTextNode(char));
            btn.setAttribute('aria-label', 'Zeichen ' + (spec.name || char) + ' einfügen');
            // mousedown, not click: click fires after the field has already lost
            // focus and dropped its selection, so the character would land at the
            // start of the text instead of at the cursor.
            btn.addEventListener('mousedown', function (e) {
                e.preventDefault();
                insert(field, char);
            });
            bar.appendChild(btn);
        });

        field.parentNode.insertBefore(bar, field);
    }

    window.Zeichenleiste = { attach: attach };

    // Server-rendered fields (student/quiz.html) name their Thema's Fach in the
    // attribute. JS-built fields call attach() themselves once they exist.
    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-zeichenleiste-fach]').forEach(function (field) {
            attach(field, field.dataset.zeichenleisteFach);
        });
    });
}());

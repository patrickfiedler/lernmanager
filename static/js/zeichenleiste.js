/* Character-insert bar for free-text answer fields.
 *
 * Students on iPads cannot reach the characters their subject needs -- in the
 * 2026-08-26 chemistry run, not one of thirty half-equation answers contained a
 * reaction arrow. window.ZEICHENLEISTE holds the characters for the logged-in
 * student's classes (empty for everyone else), set by base.html.
 *
 * Zeichenleiste.attach(field) puts a bar directly above `field`. Safe to call on
 * a field that already has one, and a no-op when the student has no character set,
 * so callers never have to check first.
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

    function attach(field) {
        var chars = window.ZEICHENLEISTE || [];
        if (!field || !chars.length || field.dataset.zeichenleiste === 'on') return;
        field.dataset.zeichenleiste = 'on';

        var bar = document.createElement('div');
        bar.className = 'zeichenleiste';
        bar.setAttribute('role', 'group');
        bar.setAttribute('aria-label', 'Sonderzeichen einfügen');

        chars.forEach(function (char) {
            var btn = document.createElement('button');
            btn.type = 'button';           // inside a <form>, the default is submit
            btn.className = 'zeichenleiste-btn';
            btn.textContent = char;
            btn.setAttribute('aria-label', 'Zeichen ' + char + ' einfügen');
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

    // Server-rendered fields (student/quiz.html). JS-built fields call attach()
    // themselves once they exist.
    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-zeichenleiste-auto]').forEach(attach);
    });
}());
